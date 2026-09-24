"""Unit tests for strata.web.server's process-wiring logic (actor/host/token
resolution, ephemeral port selection) -- everything short of actually
running uvicorn, which tests/e2e/test_e2e_10_serve.py exercises for real."""

from __future__ import annotations

from pathlib import Path

from strata.core.init import init_repository
from strata.core.repo import open_repo
from strata.web.security import DEFAULT_INACTIVITY_TIMEOUT_SECONDS
from strata.web.server import (
    ServeConfigError,
    ServeParams,
    is_loopback_host,
    opened_url,
    pick_ephemeral_port,
    resolve_actor,
    resolve_token,
)


def _repo(tmp_path: Path):  # type: ignore[no-untyped-def]
    root = tmp_path / "review"
    init_repository(root, title="T", actor_handle="ethan", actor_name="Ethan")
    return open_repo(root)


def test_is_loopback_host() -> None:
    assert is_loopback_host("127.0.0.1")
    assert is_loopback_host("localhost")
    assert is_loopback_host("::1")
    assert not is_loopback_host("192.168.1.5")
    assert not is_loopback_host("0.0.0.0")


def test_resolve_actor_auto_selects_the_only_active_actor(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    assert resolve_actor(repo, None) == "ethan"


def test_resolve_actor_accepts_an_explicit_known_handle(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    assert resolve_actor(repo, "ethan") == "ethan"


def test_resolve_actor_rejects_an_unknown_handle(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    try:
        resolve_actor(repo, "nobody")
        raise AssertionError("expected ServeConfigError")
    except ServeConfigError as exc:
        assert "unknown actor" in str(exc)


def test_resolve_actor_requires_a_choice_with_multiple_active_actors(tmp_path: Path) -> None:
    from strata.core.actor import add_actor

    repo = _repo(tmp_path)
    add_actor(repo, handle="sam", name="Sam", role="screener")
    repo = open_repo(repo.root)
    try:
        resolve_actor(repo, None)
        raise AssertionError("expected ServeConfigError")
    except ServeConfigError as exc:
        assert "multiple actors" in str(exc)


def test_resolve_actor_ignores_inactive_actors_for_auto_select(tmp_path: Path) -> None:
    from strata.core.actor import add_actor, deactivate_actor

    repo = _repo(tmp_path)
    add_actor(repo, handle="sam", name="Sam", role="screener")
    repo = open_repo(repo.root)
    deactivate_actor(repo, "sam")
    repo = open_repo(repo.root)
    assert resolve_actor(repo, None) == "ethan"


def test_resolve_actor_reports_when_no_actors_are_active(tmp_path: Path) -> None:
    from strata.core.actor import deactivate_actor

    repo = _repo(tmp_path)
    deactivate_actor(repo, "ethan")
    repo = open_repo(repo.root)
    try:
        resolve_actor(repo, None)
        raise AssertionError("expected ServeConfigError")
    except ServeConfigError as exc:
        assert "no active actors" in str(exc)


def test_resolve_token_generates_one_for_loopback_host() -> None:
    token = resolve_token("127.0.0.1", None)
    assert len(token) > 32


def test_resolve_token_accepts_a_supplied_token_for_loopback_host() -> None:
    assert resolve_token("127.0.0.1", "fixed-token") == "fixed-token"


def test_resolve_token_requires_a_token_for_non_loopback_host() -> None:
    try:
        resolve_token("0.0.0.0", None)
        raise AssertionError("expected ServeConfigError")
    except ServeConfigError as exc:
        assert "requires --token" in str(exc)


def test_resolve_token_accepts_a_supplied_token_for_non_loopback_host() -> None:
    assert resolve_token("0.0.0.0", "fixed-token") == "fixed-token"


def test_pick_ephemeral_port_returns_a_usable_port() -> None:
    port = pick_ephemeral_port("127.0.0.1")
    assert 1 <= port <= 65535


def test_pick_ephemeral_port_returns_different_ports_across_calls() -> None:
    # Not guaranteed by the OS, but overwhelmingly likely, and a useful
    # sanity check that this isn't hardcoded.
    ports = {pick_ephemeral_port("127.0.0.1") for _ in range(5)}
    assert len(ports) > 1


def test_opened_url() -> None:
    params = ServeParams(
        repo_root=Path("/tmp/review"),
        actor="ethan",
        host="127.0.0.1",
        port=8123,
        session_token="abc123",
        inactivity_timeout=DEFAULT_INACTIVITY_TIMEOUT_SECONDS,
    )
    assert opened_url(params) == "http://127.0.0.1:8123/?token=abc123"
