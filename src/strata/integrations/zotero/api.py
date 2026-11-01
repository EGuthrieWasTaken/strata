"""A client for the Zotero API v3, as served by the local app or by `api.zotero.org`.

Implements the polite-use half of openspec:zotero-integration#transport-selection: Zotero tells a
busy client to wait, in two ways, and this client does as it is told.

- ``Backoff: <seconds>`` arrives on an otherwise successful response and means *do not send the next
  request for that long*.
- ``Retry-After: <seconds>`` arrives on a 429 or 503 and means *this request was not served; send it
  again after that long*.

A wait longer than `max_wait` is not slept through: the call fails and says how long Zotero asked
for, so a person is never left looking at a frozen terminal.
"""

from __future__ import annotations

import json
import time
import urllib.parse
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from typing import Any

from strata import __version__
from strata.integrations.reference_manager import (
    ReferenceManagerError,
    ReferenceManagerUnavailableError,
)
from strata.integrations.zotero.http import HttpTransport, TransportError

LOCAL_BASE_URL = "http://127.0.0.1:23119/api"
WEB_BASE_URL = "https://api.zotero.org"
API_VERSION = "3"
PAGE_SIZE = 100

_RETRY_STATUSES = frozenset({429, 503})


class ZoteroError(ReferenceManagerError):
    """Zotero answered, but not with what was asked for."""

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class ZoteroUnavailableError(ReferenceManagerUnavailableError):
    """Zotero could not be reached."""


class ZoteroNotFoundError(ZoteroError):
    """404: the library, collection or item is not there."""


class ZoteroPreconditionError(ZoteroError):
    """412: the item changed since the version the request was conditional on."""


@dataclass(frozen=True)
class ApiResponse:
    status: int
    headers: dict[str, str]
    body: bytes

    def json(self) -> Any:
        try:
            return json.loads(self.body)
        except json.JSONDecodeError:
            raise ZoteroError("Zotero sent a reply that is not JSON", status=self.status) from None


def _seconds(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        seconds = float(value)
    except ValueError:
        return None
    return seconds if seconds >= 0 else None


class ZoteroApi:
    """One connection to one Zotero API root (local or web), with an optional key."""

    def __init__(
        self,
        base_url: str,
        transport: HttpTransport,
        *,
        api_key: str | None = None,
        sleep: Callable[[float], None] = time.sleep,
        max_retries: int = 4,
        max_wait: float = 120.0,
        timeout: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.transport = transport
        self.api_key = api_key
        self.sleep = sleep
        self.max_retries = max_retries
        self.max_wait = max_wait
        self.timeout = timeout
        self._backoff = 0.0

    def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        body: Any = None,
        headers: Mapping[str, str] | None = None,
    ) -> ApiResponse:
        """Send one request, waiting out `Backoff` first and retrying a 429 or 503 after
        `Retry-After`. Returns any response below 400; anything else raises."""
        url = self.base_url + path
        if params:
            url += "?" + urllib.parse.urlencode(params, safe=",", quote_via=urllib.parse.quote)
        sent_headers = {
            "Zotero-API-Version": API_VERSION,
            "User-Agent": f"strata/{__version__}",
            "Accept": "application/json",
            **(headers or {}),
        }
        if self.api_key:
            sent_headers["Zotero-API-Key"] = self.api_key
        payload: bytes | None = None
        if body is not None:
            payload = json.dumps(body).encode("utf-8")
            sent_headers["Content-Type"] = "application/json"

        attempt = 0
        while True:
            self._wait_out_backoff()
            try:
                raw = self.transport.request(method, url, sent_headers, payload, self.timeout)
            except TransportError as exc:
                raise ZoteroUnavailableError(
                    f"could not reach Zotero at {self.base_url}: {exc}"
                ) from None
            response = ApiResponse(raw.status, raw.headers, raw.body)
            self._backoff = _seconds(response.headers.get("backoff")) or 0.0

            if response.status in _RETRY_STATUSES:
                if attempt >= self.max_retries:
                    raise ZoteroError(
                        f"Zotero is still busy after {attempt + 1} attempts "
                        f"(status {response.status}); try again later",
                        status=response.status,
                    )
                wait = _seconds(response.headers.get("retry-after"))
                self._sleep_for_server(2.0**attempt if wait is None else wait)
                attempt += 1
                continue
            if response.status >= 400:
                raise self._error(response, method, path)
            return response

    def get_json(self, path: str, params: Mapping[str, Any] | None = None) -> Any:
        return self.request("GET", path, params=params).json()

    def get_pages(
        self, path: str, params: Mapping[str, Any] | None = None, *, page_size: int = PAGE_SIZE
    ) -> Iterator[list[Any]]:
        """Each page of a list endpoint, until a page comes back short."""
        start = 0
        while True:
            page = self.get_json(path, {**(params or {}), "limit": page_size, "start": start})
            if not isinstance(page, list):
                raise ZoteroError(f"Zotero answered {path} with something other than a list")
            if page:
                yield page
            if len(page) < page_size:
                return
            start += page_size

    def _wait_out_backoff(self) -> None:
        if self._backoff > 0:
            wait, self._backoff = self._backoff, 0.0
            self._sleep_for_server(wait)

    def _sleep_for_server(self, seconds: float) -> None:
        if seconds > self.max_wait:
            raise ZoteroError(
                f"Zotero asked for a wait of {seconds:.0f} s, longer than the "
                f"{self.max_wait:.0f} s strata will wait; try again later"
            )
        self.sleep(seconds)

    def _error(self, response: ApiResponse, method: str, path: str) -> ZoteroError:
        detail = response.body.decode("utf-8", errors="replace").strip()[:200]
        suffix = f": {detail}" if detail else ""
        status = response.status
        if status == 404:
            return ZoteroNotFoundError(f"Zotero has no {path}{suffix}", status=status)
        if status == 412:
            return ZoteroPreconditionError(
                f"{method} {path} refused: the item changed since the version it was "
                f"based on{suffix}",
                status=status,
            )
        if status in (401, 403):
            return ZoteroError(
                f"Zotero refused {method} {path} ({status}): the API key is missing, wrong, or "
                f"lacks permission, or the local API is switched off{suffix}",
                status=status,
            )
        return ZoteroError(f"Zotero answered {method} {path} with {status}{suffix}", status=status)
