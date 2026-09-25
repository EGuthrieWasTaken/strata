"""Integration tests for the web adjudication surface
(`/adjudicate/<stage>`): docs/spec/06-workflow-screening.md §8."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from strata import gitio
from strata.core.actor import add_actor
from strata.core.init import init_repository
from strata.core.records import write_records
from strata.core.repo import open_repo
from strata.protocol.adjudication import is_adjudicator
from strata.protocol.criteria import add_criterion
from strata.protocol.screening import all_adjudicate_events, record_screen_decision
from strata.web.app import create_app

_TOKEN = "test-session-token-0123456789"


def _record(record_id: str) -> dict:
    return {
        "id": record_id,
        "type": "article-journal",
        "title": "A conflicted record",
        "abstract": "An abstract.",
        "strata": {
            "canonical_key": f"sig:{record_id}",
            "canonical": True,
            "sources": [{"import": "imp_01arz3ndektsv4rrffq69g5fav"}],
        },
    }


def _repo_with_one_conflict(tmp_path: Path):  # type: ignore[no-untyped-def]
    root = tmp_path / "review"
    init_repository(root, title="Adjudicate Test", actor_handle="ethan", actor_name="Ethan")
    repo = open_repo(root)
    add_actor(repo, handle="sam", name="Sam", role="screener")
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
    repo = open_repo(root)
    write_records(repo, [_record("rec_0000000000000001")])
    repo = open_repo(root)
    record_screen_decision(
        repo,
        stage="title-abstract",
        record_id="rec_0000000000000001",
        decision="include",
        actor="sam",
    )
    repo = open_repo(root)
    record_screen_decision(
        repo,
        stage="title-abstract",
        record_id="rec_0000000000000001",
        decision="exclude",
        actor="ethan",
        cited=["EXC-01"],
    )
    repo = open_repo(root)
    gitio.add_all(root)
    gitio.commit(root, "chore: test fixture setup\n\nStrata-Op: fixture\n")
    return open_repo(root)


def _client(repo, *, actor: str = "ethan") -> TestClient:  # type: ignore[no-untyped-def]
    app = create_app(repo_root=repo.root, actor=actor, session_token=_TOKEN)
    client = TestClient(app, base_url="http://127.0.0.1:8000")
    r = client.get(f"/?token={_TOKEN}")
    assert r.status_code == 200
    return client


def test_adjudicate_unknown_stage_is_404(tmp_path: Path) -> None:
    repo = _repo_with_one_conflict(tmp_path)
    client = _client(repo)
    r = client.get("/adjudicate/not-a-stage")
    assert r.status_code == 404


def test_adjudicate_with_no_conflicts(tmp_path: Path) -> None:
    root = tmp_path / "review"
    init_repository(root, title="T", actor_handle="ethan", actor_name="Ethan")
    client = _client(open_repo(root))
    r = client.get("/adjudicate/title-abstract")
    assert r.status_code == 200
    assert "No conflicts" in r.text


def test_adjudicate_shows_both_opinions(tmp_path: Path) -> None:
    repo = _repo_with_one_conflict(tmp_path)
    client = _client(repo)
    r = client.get("/adjudicate/title-abstract")
    assert r.status_code == 200
    assert "sam" in r.text
    assert "ethan" in r.text
    assert "INCLUDE" in r.text
    assert "EXCLUDE" in r.text
    assert "1 conflict" in r.text


def test_adjudicate_view_hides_form_for_a_non_adjudicator(tmp_path: Path) -> None:
    repo = _repo_with_one_conflict(tmp_path)
    assert not is_adjudicator(repo, "sam")
    client = _client(repo, actor="sam")
    r = client.get("/adjudicate/title-abstract")
    assert r.status_code == 200
    assert "not an adjudicator" in r.text
    assert 'name="rationale"' not in r.text


def test_adjudicate_post_resolves_and_commits(tmp_path: Path) -> None:
    repo = _repo_with_one_conflict(tmp_path)
    client = _client(repo)
    r = client.post(
        "/adjudicate/title-abstract",
        data={
            "csrf_token": _TOKEN,
            "record_id": "rec_0000000000000001",
            "decision": "exclude",
            "criteria": "EXC-01",
            "rationale": "The lead reviewer applied the criterion correctly.",
            "skip": "",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/adjudicate/title-abstract"

    repo = open_repo(repo.root)
    events = all_adjudicate_events(repo, "title-abstract")
    assert len(events) == 1
    assert events[0]["body"]["decision"] == "exclude"
    assert events[0]["body"]["criteria"] == ["EXC-01"]
    assert not gitio.is_dirty(repo.root)

    r2 = client.get("/adjudicate/title-abstract")
    assert "No conflicts" in r2.text


def test_adjudicate_post_by_a_non_adjudicator_is_rejected(tmp_path: Path) -> None:
    repo = _repo_with_one_conflict(tmp_path)
    client = _client(repo, actor="sam")
    r = client.post(
        "/adjudicate/title-abstract",
        data={
            "csrf_token": _TOKEN,
            "record_id": "rec_0000000000000001",
            "decision": "exclude",
            "criteria": "EXC-01",
            "rationale": "Trying to adjudicate without the role.",
            "skip": "",
        },
    )
    assert r.status_code == 422
    assert "not an adjudicator" in r.text.lower()


def test_adjudicate_post_without_rationale_is_rejected(tmp_path: Path) -> None:
    repo = _repo_with_one_conflict(tmp_path)
    client = _client(repo)
    r = client.post(
        "/adjudicate/title-abstract",
        data={
            "csrf_token": _TOKEN,
            "record_id": "rec_0000000000000001",
            "decision": "exclude",
            "criteria": "EXC-01",
            "skip": "",
        },
    )
    assert r.status_code == 422


def test_adjudicate_post_requires_csrf(tmp_path: Path) -> None:
    repo = _repo_with_one_conflict(tmp_path)
    client = _client(repo)
    r = client.post(
        "/adjudicate/title-abstract",
        data={
            "record_id": "rec_0000000000000001",
            "decision": "exclude",
            "criteria": "EXC-01",
            "rationale": "Trying without a CSRF token.",
            "skip": "",
        },
    )
    assert r.status_code == 403


def test_adjudicate_skip_moves_past_a_conflict_without_resolving(tmp_path: Path) -> None:
    repo = _repo_with_one_conflict(tmp_path)
    client = _client(repo)
    r = client.get("/adjudicate/title-abstract?skip=rec_0000000000000001")
    assert "No conflicts" in r.text
    repo = open_repo(repo.root)
    assert all_adjudicate_events(repo, "title-abstract") == []


def test_adjudicate_post_success_carries_skip_list_into_redirect(tmp_path: Path) -> None:
    repo = _repo_with_one_conflict(tmp_path)
    client = _client(repo)
    r = client.post(
        "/adjudicate/title-abstract",
        data={
            "csrf_token": _TOKEN,
            "record_id": "rec_0000000000000001",
            "decision": "exclude",
            "criteria": "EXC-01",
            "rationale": "The lead reviewer applied the criterion correctly.",
            "skip": "rec_0000000000000099",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "skip=rec_0000000000000099" in r.headers["location"]
