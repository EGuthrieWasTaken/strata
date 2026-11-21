"""Warn once when `X-Forwarded-For` arrives from an address that is not a trusted proxy
(openspec:hosted-deployment#hosted-security-baseline; tasks 4.10 and 4.14). Behind a proxy that is
not listed, every request comes from the proxy's address, so the per-client sign-in limit would
lock everyone out together."""

# ruff: noqa: E501

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from strata.hosted import accounts
from strata.web.hosted import create_served_app, run_hosted
from tests.integration._hosted import PASSWORD, PUBLIC_URL, csrf_from, hosted

PROXY = "10.0.0.2"
STRANGER = "203.0.113.7"


def _client(app: Any, address: str) -> TestClient:
    return TestClient(app, base_url=PUBLIC_URL, client=(address, 50000), follow_redirects=False)


def _warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in caplog.records if "X-Forwarded-For" in r.getMessage()]


def test_a_forwarded_for_header_from_an_untrusted_address_is_warned_about_once(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING, logger="strata.hosted")
    h = hosted(tmp_path)
    app = create_served_app(h.server, trusted_proxies=PROXY)
    behind = _client(app, STRANGER)

    for _ in range(3):
        assert behind.get("/signin", headers={"X-Forwarded-For": "198.51.100.1"}).status_code == 200

    (message,) = _warnings(caplog)  # once, however many requests
    assert STRANGER in message and "not" in message and "trusted" in message  # what, and why
    assert "ignored" in message  # what was done about it
    assert str(accounts.MAX_FAILURES_PER_CLIENT) in message  # what it costs
    assert f"--trusted-proxy {STRANGER}" in message and "STRATA_TRUSTED_PROXY" in message  # the fix
    assert PROXY in message  # what it is trusting now
    # A different untrusted address does not make it say so again.
    _client(app, "203.0.113.99").get("/signin", headers={"X-Forwarded-For": "198.51.100.2"})
    assert len(_warnings(caplog)) == 1


def test_requests_without_the_header_or_from_a_trusted_proxy_say_nothing(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING, logger="strata.hosted")
    h = hosted(tmp_path)
    app = create_served_app(h.server, trusted_proxies=f"127.0.0.1, {PROXY}")

    assert _client(app, STRANGER).get("/signin").status_code == 200  # no header
    assert (
        _client(app, PROXY).get("/signin", headers={"X-Forwarded-For": "198.51.100.1"}).status_code
        == 200
    )
    assert _warnings(caplog) == []


def test_a_network_or_a_star_counts_as_trusted(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING, logger="strata.hosted")
    h = hosted(tmp_path)
    for trusted in ("10.0.0.0/24", "*"):
        app = create_served_app(h.server, trusted_proxies=trusted)
        _client(app, PROXY).get("/signin", headers={"X-Forwarded-For": "198.51.100.1"})
    assert _warnings(caplog) == []


def test_a_trusted_proxys_header_still_decides_which_client_signed_in(tmp_path: Path) -> None:
    h = hosted(tmp_path)
    app = create_served_app(h.server, trusted_proxies=PROXY)
    through_proxy = _client(app, PROXY)
    headers = {"X-Forwarded-For": "198.51.100.9"}
    page = through_proxy.get("/signin", headers=headers)
    through_proxy.post(
        "/signin",
        headers=headers,
        data={
            "csrf_token": csrf_from(page.text),
            "username": "sam.okonkwo",
            "password": "wrong password!",
        },
    )
    assert accounts.signin_log(h.instance.store)[0]["client"] == "198.51.100.9"

    # From an address that is not trusted, the same header is not believed.
    stranger = _client(app, STRANGER)
    page = stranger.get("/signin")
    stranger.post(
        "/signin",
        headers=headers,
        data={
            "csrf_token": csrf_from(page.text),
            "username": "sam.okonkwo",
            "password": PASSWORD + "!",
        },
    )
    assert accounts.signin_log(h.instance.store)[0]["client"] == STRANGER


def test_the_running_server_is_the_watched_app_and_leaves_forwarded_headers_to_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    import uvicorn

    caplog.set_level(logging.WARNING, logger="strata.hosted")
    h = hosted(tmp_path)
    captured: dict[str, Any] = {}
    monkeypatch.setattr(uvicorn, "run", lambda app, **kwargs: captured.update(kwargs, app=app))

    run_hosted(h.server, bind="127.0.0.1", port=8765, trusted_proxies=PROXY)

    # uvicorn must not also rewrite the client first, or the watcher could not tell a proxy from a
    # stranger.
    assert captured["proxy_headers"] is False and captured["access_log"] is False
    assert (
        _client(captured["app"], STRANGER)
        .get("/signin", headers={"X-Forwarded-For": "1.2.3.4"})
        .status_code
        == 200
    )
    assert len(_warnings(caplog)) == 1
