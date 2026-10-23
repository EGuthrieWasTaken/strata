"""Unpaywall: surface a legal open-access link for a DOI.

Implements openspec:full-text-retrieval#legal-open-access-links-only and the polite-use rules of
openspec:privacy-and-security#polite-api-use. Nothing here downloads a document.
"""

from __future__ import annotations

import hashlib
import json
import time
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from strata import __version__
from strata.core.ids import normalise_doi


class EnrichmentError(RuntimeError):
    """Raised when an enrichment operation fails."""


@dataclass(frozen=True)
class HttpResponse:
    """Represents a raw HTTP response."""

    status: int
    headers: dict[str, str]
    body: bytes


class Transport(Protocol):
    """Protocol for network transport."""

    def get(self, url: str, headers: dict[str, str], timeout: float) -> HttpResponse: ...


@dataclass(frozen=True)
class OpenAccessLink:
    """Represents a discovered open-access link."""

    url: str
    version: str | None
    license: str | None
    host_type: str | None


def enrichment_enabled(config: Mapping[str, Any], provider: str) -> bool:
    """Check if enrichment is enabled for a specific provider."""
    try:
        enrichment = config["enrichment"]
        return enrichment["enabled"] is True and provider in enrichment["providers"]
    except (KeyError, TypeError):
        return False


class UrllibTransport:
    """Real network transport using urllib."""

    # pragma: no cover
    def get(self, url: str, headers: dict[str, str], timeout: float) -> HttpResponse:
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return HttpResponse(
                    status=response.getcode(),
                    headers=dict(response.info().items()),
                    body=response.read(),
                )
        except urllib.error.HTTPError as e:
            return HttpResponse(
                status=e.code,
                headers=dict(e.headers.items()),
                body=e.read(),
            )
        except Exception as e:
            raise EnrichmentError(f"Network failure: {e}") from None


class UnpaywallClient:
    """Client to interact with the Unpaywall API."""

    def __init__(
        self,
        contact_email: str,
        cache_dir: Path,
        log_path: Path,
        *,
        transport: Transport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], datetime] = lambda: datetime.now(),
        max_retries: int = 4,
        timeout: float = 30.0,
    ) -> None:
        if not contact_email.strip():
            raise EnrichmentError("Contact email cannot be blank.")
        self.contact_email = contact_email
        self.cache_dir = cache_dir
        self.log_path = log_path
        self.transport = transport or UrllibTransport()
        self.sleep = sleep
        self.now = now
        self.max_retries = max_retries
        self.timeout = timeout

    def find(self, doi: str) -> OpenAccessLink | None:
        """Find an open-access link for the given DOI."""
        norm_doi = normalise_doi(doi)
        if norm_doi is None:
            raise EnrichmentError(f"Invalid DOI: {doi}")

        self.cache_dir.mkdir(parents=True, exist_ok=True)
        cache_path = self.cache_dir / f"{hashlib.sha256(norm_doi.encode()).hexdigest()}.json"
        if cache_path.exists():
            try:
                with open(cache_path, encoding="utf-8") as f:
                    data = json.load(f)
                    if data.get("is_oa"):
                        return self._parse_response(data)
                    return None
            except (OSError, json.JSONDecodeError):
                pass

        doi_quoted = urllib.parse.quote(norm_doi, safe="/")
        email_quoted = urllib.parse.quote(self.contact_email, safe="")
        url = f"https://api.unpaywall.org/v2/{doi_quoted}?email={email_quoted}"
        headers = {
            "User-Agent": f"strata/{__version__} (mailto:{self.contact_email})",
            "Accept": "application/json",
        }

        attempt = 0
        while True:
            self._log(f"api.unpaywall.org/v2/{doi_quoted}", "find open-access full text")
            resp = self.transport.get(url, headers, self.timeout)

            # Normalize headers to lowercase for case-insensitive access
            resp_headers = {k.lower(): v for k, v in resp.headers.items()}

            if resp.status == 200:
                try:
                    data = json.loads(resp.body)
                    if not isinstance(data, dict):
                        raise EnrichmentError("Invalid JSON response")
                    with open(cache_path, "w", encoding="utf-8") as f:
                        json.dump(data, f)
                    return self._parse_response(data)
                except (json.JSONDecodeError, EnrichmentError) as e:
                    raise EnrichmentError(f"Failed to parse response: {e}") from None

            if resp.status == 404:
                with open(cache_path, "w", encoding="utf-8") as f:
                    json.dump({"is_oa": False}, f)
                return None

            if resp.status in (429, 503):
                if attempt >= self.max_retries:
                    raise EnrichmentError(f"Max retries exceeded for status {resp.status}")

                retry_after = resp_headers.get("retry-after")
                try:
                    wait = float(retry_after) if retry_after is not None else 2.0**attempt
                except ValueError:
                    wait = 2.0**attempt

                self.sleep(wait)
                attempt += 1
                continue

            raise EnrichmentError(f"Unexpected status code: {resp.status}")

    def _log(self, endpoint: str, purpose: str) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        ts = self.now().strftime("%Y-%m-%dT%H:%M:%SZ")
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(f"{ts}\t{endpoint}\t{purpose}\n")

    def _parse_response(self, data: dict[str, Any]) -> OpenAccessLink | None:
        if not data.get("is_oa"):
            return None

        loc = data.get("best_oa_location")
        if not isinstance(loc, dict):
            return None

        url = loc.get("url_for_pdf") or loc.get("url")
        if not isinstance(url, str) or not url:
            return None

        version_map = {
            "publishedVersion": "version-of-record",
            "acceptedVersion": "accepted-manuscript",
            "submittedVersion": "preprint",
        }
        raw_version = loc.get("version")
        version = version_map.get(raw_version) if isinstance(raw_version, str) else None

        def text(value: object) -> str | None:
            return value if isinstance(value, str) and value else None

        return OpenAccessLink(
            url=url,
            version=version,
            license=text(loc.get("license")),
            host_type=text(loc.get("host_type")),
        )
