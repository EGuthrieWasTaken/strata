"""Integration tests for the read-only `/history` screen:
docs/spec/11-web-ui.md §2, reusing `core.logcmd.domain_log` (`strata
log`'s own data path -- `Strata-` commit trailers, never raw commit
messages)."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from strata.core.init import init_repository
from strata.core.repo import open_repo
from strata.protocol.criteria import add_criterion
from strata.web.app import create_app

_TOKEN = "test-session-token-0123456789"


def _repo_with_a_criterion_commit(tmp_path: Path):  # type: ignore[no-untyped-def]
    root = tmp_path / "review"
    init_repository(root, title="History Test", actor_handle="ethan", actor_name="Ethan")
    repo = open_repo(root)
    add_criterion(
        repo,
        kind="exclusion",
        label="Not empirical",
        definition="Not an empirical study.",
        applies_at=["title-abstract"],
        actor="ethan",
        rationale="Establishing the initial protocol criteria.",
        criterion_id="EXC-01",
    )
    # add_criterion is the pure protocol-layer call the CLI commits after
    # (cli.main._commit_criteria_op) -- commit here too, matching real usage.
    from strata import gitio

    gitio.add_all(root)
    gitio.commit(
        root,
        "criteria(EXC-01): add criterion EXC-01\n\n"
        "Establishing the initial protocol criteria.\n\n"
        "Strata-Op: criteria-add\nStrata-Criterion: EXC-01\nStrata-Actor: ethan\n",
    )
    return open_repo(root)


def _client(repo) -> TestClient:  # type: ignore[no-untyped-def]
    app = create_app(repo_root=repo.root, actor="ethan", session_token=_TOKEN)
    client = TestClient(app, base_url="http://127.0.0.1:8000")
    r = client.get(f"/?token={_TOKEN}")
    assert r.status_code == 200
    return client


def test_history_shows_every_commit(tmp_path: Path) -> None:
    repo = _repo_with_a_criterion_commit(tmp_path)
    client = _client(repo)
    r = client.get("/history")
    assert r.status_code == 200
    assert "criteria-add" in r.text
    assert "EXC-01" in r.text
    assert "2 commits" in r.text  # init + the criteria-add above


def test_history_filters_by_actor(tmp_path: Path) -> None:
    repo = _repo_with_a_criterion_commit(tmp_path)
    client = _client(repo)
    r = client.get("/history?actor=ethan")
    assert r.status_code == 200
    assert "criteria-add" in r.text


def test_history_filters_by_actor_with_no_matches(tmp_path: Path) -> None:
    repo = _repo_with_a_criterion_commit(tmp_path)
    client = _client(repo)
    r = client.get("/history?actor=nobody")
    assert r.status_code == 200
    assert "0 commits" in r.text


def test_history_filters_by_stage(tmp_path: Path) -> None:
    repo = _repo_with_a_criterion_commit(tmp_path)
    client = _client(repo)
    r = client.get("/history?stage=title-abstract")
    assert r.status_code == 200
    # The criteria-add commit has no Strata-Stage trailer, so a stage
    # filter matches nothing here -- confirms the filter is real, not a
    # no-op, matching core.logcmd.domain_log's own behavior.
    assert "0 commits" in r.text
