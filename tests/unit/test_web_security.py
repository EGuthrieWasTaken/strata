"""Unit tests for strata.web.security: openspec:web-ui#localhost-security."""

from __future__ import annotations

import pytest

from strata.web.security import (
    InactivityClock,
    allowed_hosts,
    generate_token,
    is_host_allowed,
    is_origin_allowed,
    parse_public_url,
)


def test_generate_token_is_random_and_url_safe() -> None:
    a = generate_token()
    b = generate_token()
    assert a != b
    assert len(a) > 32
    assert all(c.isalnum() or c in "-_" for c in a)


def test_allowed_hosts_loopback_accepts_both_names() -> None:
    allowed = allowed_hosts("127.0.0.1", 8000)
    assert allowed == {"127.0.0.1:8000", "localhost:8000"}


def test_allowed_hosts_non_loopback_is_just_itself() -> None:
    allowed = allowed_hosts("192.168.1.5", 8000)
    assert allowed == {"192.168.1.5:8000"}


def test_is_host_allowed() -> None:
    allowed = allowed_hosts("127.0.0.1", 8000)
    assert is_host_allowed("127.0.0.1:8000", allowed)
    assert is_host_allowed("localhost:8000", allowed)
    assert not is_host_allowed("evil.example:8000", allowed)
    assert not is_host_allowed(None, allowed)


def test_is_origin_allowed_absent_header_passes() -> None:
    """No `Origin` header at all (a same-origin navigation or non-browser
    client) is allowed through -- only a *present, wrong* one is rejected."""
    assert is_origin_allowed(None, "127.0.0.1", 8000)


def test_is_origin_allowed_matching_origin() -> None:
    assert is_origin_allowed("http://127.0.0.1:8000", "127.0.0.1", 8000)
    assert is_origin_allowed("http://localhost:8000", "127.0.0.1", 8000)


def test_is_origin_allowed_rejects_mismatched_origin() -> None:
    assert not is_origin_allowed("http://evil.example", "127.0.0.1", 8000)
    assert not is_origin_allowed("http://127.0.0.1:9999", "127.0.0.1", 8000)
    assert not is_origin_allowed("https://127.0.0.1:8000", "127.0.0.1", 8000)


def test_is_origin_allowed_non_loopback_host_has_no_localhost_alias() -> None:
    assert is_origin_allowed("http://192.168.1.5:8000", "192.168.1.5", 8000)
    assert not is_origin_allowed("http://localhost:8000", "192.168.1.5", 8000)


def test_inactivity_clock_not_expired_before_timeout() -> None:
    clock = InactivityClock(60.0, now=0.0)
    assert not clock.is_expired(now=59.0)


def test_inactivity_clock_expired_at_timeout() -> None:
    clock = InactivityClock(60.0, now=0.0)
    assert clock.is_expired(now=60.0)


def test_inactivity_clock_touch_resets_the_timer() -> None:
    clock = InactivityClock(60.0, now=0.0)
    clock.touch(now=50.0)
    assert not clock.is_expired(now=100.0)
    assert clock.is_expired(now=111.0)


def test_inactivity_clock_uses_real_clock_when_now_omitted() -> None:
    clock = InactivityClock(3600.0)
    assert not clock.is_expired()
    clock.touch()
    assert not clock.is_expired()


# --- openspec:web-ui#configurable-public-url ---------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "host_header", "origin"),
    [
        ("http://localhost:8765", "localhost:8765", "http://localhost:8765"),
        ("https://strata.example.edu", "strata.example.edu", "https://strata.example.edu"),
        ("https://strata.example.edu:443/", "strata.example.edu", "https://strata.example.edu"),
        ("http://strata.example.edu:80", "strata.example.edu", "http://strata.example.edu"),
        ("https://strata.example.edu:8443", "strata.example.edu:8443", "https://strata.example.edu:8443"),
        ("http://[::1]:8765", "[::1]:8765", "http://[::1]:8765"),
        ("https://strata.example.edu/team/reviews", "strata.example.edu", "https://strata.example.edu"),
    ],
)  # fmt: skip
def test_parse_public_url_gives_the_host_and_origin_a_browser_sends(
    raw: str, host_header: str, origin: str
) -> None:
    parsed = parse_public_url(raw)
    assert parsed.host_header == host_header
    assert parsed.origin == origin


@pytest.mark.parametrize(
    "raw", ["localhost", "localhost:8765", "ftp://example.org", "//example.org", "http://", "", "http://x:99999"]
)  # fmt: skip
def test_parse_public_url_rejects_anything_that_is_not_an_absolute_http_url(raw: str) -> None:
    with pytest.raises(ValueError, match="scheme|host|port"):
        parse_public_url(raw)


def test_the_scheme_hint_names_the_fix() -> None:
    with pytest.raises(ValueError, match=r"http://localhost:8765"):
        parse_public_url("localhost")


def test_a_public_url_replaces_the_bind_address_for_host_validation() -> None:
    public = parse_public_url("http://localhost:8765")
    allowed = allowed_hosts("0.0.0.0", 8765, public)  # noqa: S104 - the bind address in a container
    assert allowed == frozenset({"localhost:8765"})
    assert is_host_allowed("localhost:8765", allowed)
    assert not is_host_allowed("attacker.example:8765", allowed)
    # exactly that host, not the loopback aliases the bind-derived list would add
    assert not is_host_allowed("127.0.0.1:8765", allowed)


def test_a_public_url_replaces_the_bind_address_for_origin_validation() -> None:
    public = parse_public_url("https://strata.example.edu")
    assert is_origin_allowed("https://strata.example.edu", "0.0.0.0", 8765, public)  # noqa: S104
    assert is_origin_allowed(None, "0.0.0.0", 8765, public)  # noqa: S104
    assert not is_origin_allowed("http://strata.example.edu", "0.0.0.0", 8765, public)  # noqa: S104
    assert not is_origin_allowed("https://attacker.example", "0.0.0.0", 8765, public)  # noqa: S104
    # without a public URL nothing changes
    assert is_origin_allowed("http://127.0.0.1:8000", "127.0.0.1", 8000)
