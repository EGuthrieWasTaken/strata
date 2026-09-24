"""Unit tests for strata.web.security: docs/spec/11-web-ui.md §7."""

from __future__ import annotations

from strata.web.security import (
    InactivityClock,
    allowed_hosts,
    generate_token,
    is_host_allowed,
    is_origin_allowed,
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
