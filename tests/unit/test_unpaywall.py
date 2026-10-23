"""Acceptance tests for strata.ingest.enrich.unpaywall."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from strata import __version__
from strata.ingest.enrich import unpaywall as up

DOI = "10.1111/j.1467-9280.2008.02209.x"
EMAIL = "me@example.org"


class FakeTransport:
    def __init__(self, responses: list[up.HttpResponse]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, dict[str, str], float]] = []

    def get(self, url: str, headers: dict[str, str], timeout: float) -> up.HttpResponse:
        self.calls.append((url, dict(headers), timeout))
        return self.responses.pop(0)


def _ok(payload: dict[str, Any]) -> up.HttpResponse:
    return up.HttpResponse(200, {}, json.dumps(payload).encode())


def _client(
    tmp_path: Path, responses: list[up.HttpResponse], **kwargs: Any
) -> tuple[up.UnpaywallClient, FakeTransport, list[float]]:
    transport = FakeTransport(responses)
    sleeps: list[float] = []
    client = up.UnpaywallClient(
        EMAIL,
        tmp_path / "cache",
        tmp_path / "log" / "network.log",
        transport=transport,
        sleep=sleeps.append,
        now=lambda: datetime(2026, 3, 28, 12, 30, 5, tzinfo=UTC),
        **kwargs,
    )
    return client, transport, sleeps


OA = {
    "is_oa": True,
    "best_oa_location": {
        "url_for_pdf": "https://repo.example/paper.pdf",
        "url": "https://repo.example/paper",
        "version": "publishedVersion",
        "license": "cc-by",
        "host_type": "publisher",
    },
}


def test_enrichment_enabled_needs_the_flag_and_the_provider() -> None:
    on = {"enrichment": {"enabled": True, "providers": ["unpaywall", "crossref"]}}
    assert up.enrichment_enabled(on, "unpaywall") is True
    assert up.enrichment_enabled(on, "openalex") is False
    assert (
        up.enrichment_enabled(
            {"enrichment": {"enabled": False, "providers": ["unpaywall"]}}, "unpaywall"
        )
        is False
    )
    assert up.enrichment_enabled({"enrichment": {"enabled": True}}, "unpaywall") is False
    assert up.enrichment_enabled({}, "unpaywall") is False


def test_blank_contact_email_is_refused(tmp_path: Path) -> None:
    with pytest.raises(up.EnrichmentError):
        up.UnpaywallClient("  ", tmp_path / "c", tmp_path / "l")


def test_finds_an_open_access_link(tmp_path: Path) -> None:
    client, _, _ = _client(tmp_path, [_ok(OA)])
    link = client.find(DOI)
    assert link == up.OpenAccessLink(
        url="https://repo.example/paper.pdf",
        version="version-of-record",
        license="cc-by",
        host_type="publisher",
    )


@pytest.mark.parametrize(
    ("raw", "mapped"),
    [
        ("acceptedVersion", "accepted-manuscript"),
        ("submittedVersion", "preprint"),
        ("somethingElse", None),
        (None, None),
    ],
)
def test_version_mapping(tmp_path: Path, raw: str | None, mapped: str | None) -> None:
    location: dict[str, Any] = {"url": "https://repo.example/p"}
    if raw is not None:
        location["version"] = raw
    client, _, _ = _client(tmp_path, [_ok({"is_oa": True, "best_oa_location": location})])
    link = client.find(DOI)
    assert link is not None
    assert link.version == mapped
    assert link.url == "https://repo.example/p"  # falls back to the landing page
    assert link.license is None
    assert link.host_type is None


@pytest.mark.parametrize(
    "payload",
    [
        {"is_oa": False, "best_oa_location": None},
        {"is_oa": True},
        {"is_oa": True, "best_oa_location": {"version": "publishedVersion"}},
        {"is_oa": True, "best_oa_location": {"url_for_pdf": "", "url": ""}},
    ],
)
def test_no_usable_link_means_none(tmp_path: Path, payload: dict[str, Any]) -> None:
    client, _, _ = _client(tmp_path, [_ok(payload)])
    assert client.find(DOI) is None


def test_unknown_doi_is_not_open_access(tmp_path: Path) -> None:
    client, transport, _ = _client(tmp_path, [up.HttpResponse(404, {}, b"{}")])
    assert client.find(DOI) is None
    assert client.find(DOI) is None  # the 404 was cached
    assert len(transport.calls) == 1


def test_request_url_and_headers(tmp_path: Path) -> None:
    client, transport, _ = _client(tmp_path, [_ok(OA)], timeout=12.5)
    client.find("https://doi.org/10.1111/J.1467-9280.2008.02209.X")
    [(url, headers, timeout)] = transport.calls
    assert url == (
        "https://api.unpaywall.org/v2/10.1111/j.1467-9280.2008.02209.x?email=me%40example.org"
    )
    assert headers["User-Agent"] == f"strata/{__version__} (mailto:{EMAIL})"
    assert timeout == 12.5


def test_invalid_doi_is_refused(tmp_path: Path) -> None:
    client, transport, _ = _client(tmp_path, [])
    with pytest.raises(up.EnrichmentError):
        client.find("not a doi")
    assert transport.calls == []


def test_every_request_is_logged_without_the_email(tmp_path: Path) -> None:
    client, _, _ = _client(tmp_path, [_ok(OA)])
    client.find(DOI)
    lines = (tmp_path / "log" / "network.log").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    ts, endpoint, purpose = lines[0].split("\t")
    assert ts == "2026-03-28T12:30:05Z"
    assert endpoint == "api.unpaywall.org/v2/10.1111/j.1467-9280.2008.02209.x"
    assert purpose == "find open-access full text"
    assert EMAIL not in lines[0]


def test_cached_responses_are_reused_across_clients(tmp_path: Path) -> None:
    first, transport, _ = _client(tmp_path, [_ok(OA)])
    first.find(DOI)
    second, transport2, _ = _client(tmp_path, [])
    link = second.find(DOI.upper())
    assert link is not None and link.url == "https://repo.example/paper.pdf"
    assert len(transport.calls) == 1
    assert transport2.calls == []
    assert len((tmp_path / "log" / "network.log").read_text(encoding="utf-8").splitlines()) == 1


def test_rate_limit_honours_retry_after(tmp_path: Path) -> None:
    limited = up.HttpResponse(429, {"Retry-After": "30"}, b"")
    client, transport, sleeps = _client(tmp_path, [limited, _ok(OA)])
    assert client.find(DOI) is not None
    assert sleeps == [30.0]
    assert len(transport.calls) == 2
    assert len((tmp_path / "log" / "network.log").read_text(encoding="utf-8").splitlines()) == 2


def test_retry_after_header_name_is_case_insensitive(tmp_path: Path) -> None:
    limited = up.HttpResponse(503, {"retry-after": "7"}, b"")
    client, _, sleeps = _client(tmp_path, [limited, _ok(OA)])
    client.find(DOI)
    assert sleeps == [7.0]


def test_backs_off_exponentially_without_retry_after(tmp_path: Path) -> None:
    busy = up.HttpResponse(503, {}, b"")
    client, _, sleeps = _client(tmp_path, [busy, busy, _ok(OA)])
    assert client.find(DOI) is not None
    assert sleeps == [1.0, 2.0]


def test_a_non_numeric_retry_after_falls_back_to_backoff(tmp_path: Path) -> None:
    odd = up.HttpResponse(429, {"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}, b"")
    client, _, sleeps = _client(tmp_path, [odd, _ok(OA)])
    client.find(DOI)
    assert sleeps == [1.0]


def test_gives_up_after_max_retries(tmp_path: Path) -> None:
    busy = up.HttpResponse(503, {}, b"")
    client, transport, sleeps = _client(tmp_path, [busy, busy, busy], max_retries=2)
    with pytest.raises(up.EnrichmentError):
        client.find(DOI)
    assert sleeps == [1.0, 2.0]
    assert len(transport.calls) == 3


def test_other_errors_are_not_retried(tmp_path: Path) -> None:
    client, transport, sleeps = _client(tmp_path, [up.HttpResponse(500, {}, b"")])
    with pytest.raises(up.EnrichmentError):
        client.find(DOI)
    assert sleeps == []
    assert len(transport.calls) == 1


@pytest.mark.parametrize("body", [b"<html>", b"[1, 2]", b""])
def test_malformed_success_bodies_are_errors(tmp_path: Path, body: bytes) -> None:
    client, _, _ = _client(tmp_path, [up.HttpResponse(200, {}, body)])
    with pytest.raises(up.EnrichmentError):
        client.find(DOI)


def test_failed_lookups_are_not_cached(tmp_path: Path) -> None:
    client, transport, _ = _client(tmp_path, [up.HttpResponse(500, {}, b""), _ok(OA)])
    with pytest.raises(up.EnrichmentError):
        client.find(DOI)
    assert client.find(DOI) is not None
    assert len(transport.calls) == 2
