"""Integration tests for the web rescreen surface (`/rescreen/<stage>`):
docs/spec/06-workflow-screening.md §6, docs/spec/11-web-ui.md §3.2."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from strata import gitio
from strata.core.init import init_repository
from strata.core.records import write_records
from strata.core.repo import open_repo
from strata.protocol.criteria import add_criterion
from strata.protocol.screening import all_screen_events, record_screen_decision
from strata.web.app import create_app

_TOKEN = "test-session-token-0123456789"


def _record(record_id: str, title: str = "A test record") -> dict:
    return {
        "id": record_id,
        "type": "article-journal",
        "title": title,
        "abstract": "An abstract.",
        "strata": {
            "canonical_key": f"sig:{record_id}",
            "canonical": True,
            "sources": [{"import": "imp_01arz3ndektsv4rrffq69g5fav"}],
        },
    }


def _repo_with_one_stale_record(tmp_path: Path):  # type: ignore[no-untyped-def]
    root = tmp_path / "review"
    init_repository(root, title="Rescreen Test", actor_handle="ethan", actor_name="Ethan")
    repo = open_repo(root)
    write_records(repo, [_record("rec_0000000000000001")])
    repo = open_repo(root)
    record_screen_decision(
        repo,
        stage="title-abstract",
        record_id="rec_0000000000000001",
        decision="include",
        actor="ethan",
    )
    repo = open_repo(root)
    add_criterion(
        repo,
        kind="exclusion",
        label="Under 18",
        definition="Mean sample age under 18.",
        applies_at=["title-abstract"],
        actor="ethan",
        rationale="Pilot extraction showed several child samples.",
        criterion_id="EXC-07",
    )
    repo = open_repo(root)
    gitio.add_all(root)
    gitio.commit(root, "chore: test fixture setup\n\nStrata-Op: fixture\n")
    return open_repo(root)


def _client(repo) -> TestClient:  # type: ignore[no-untyped-def]
    app = create_app(repo_root=repo.root, actor="ethan", session_token=_TOKEN)
    client = TestClient(app, base_url="http://127.0.0.1:8000")
    r = client.get(f"/?token={_TOKEN}")
    assert r.status_code == 200
    return client


def test_rescreen_unknown_stage_is_404(tmp_path: Path) -> None:
    repo = _repo_with_one_stale_record(tmp_path)
    client = _client(repo)
    r = client.get("/rescreen/not-a-stage")
    assert r.status_code == 404


def test_rescreen_with_nothing_stale(tmp_path: Path) -> None:
    root = tmp_path / "review"
    init_repository(root, title="T", actor_handle="ethan", actor_name="Ethan")
    client = _client(open_repo(root))
    r = client.get("/rescreen/title-abstract")
    assert r.status_code == 200
    assert "Nothing stale" in r.text


def test_rescreen_shows_prior_decision_and_reason(tmp_path: Path) -> None:
    repo = _repo_with_one_stale_record(tmp_path)
    client = _client(repo)
    r = client.get("/rescreen/title-abstract")
    assert r.status_code == 200
    assert "A test record" in r.text
    assert "INCLUDE" in r.text
    assert "criterion-added" in r.text
    assert "1 stale" in r.text


def test_rescreen_post_keep_previous_reaffirms_the_same_decision(tmp_path: Path) -> None:
    repo = _repo_with_one_stale_record(tmp_path)
    client = _client(repo)
    r = client.post(
        "/rescreen/title-abstract",
        data={
            "csrf_token": _TOKEN,
            "record_id": "rec_0000000000000001",
            "decision": "keep",
            "skip": "",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303

    repo = open_repo(repo.root)
    events = all_screen_events(repo, "title-abstract")
    assert len(events) == 2
    assert events[-1]["body"]["decision"] == "include"
    # Rescreen decisions batch the same way screen decisions do (this
    # module's docstring on the deferred commit policy) -- appended and
    # fsynced immediately, but not committed by this one request.
    assert gitio.is_dirty(repo.root)


def test_rescreen_post_new_decision_with_citation(tmp_path: Path) -> None:
    repo = _repo_with_one_stale_record(tmp_path)
    client = _client(repo)
    r = client.post(
        "/rescreen/title-abstract",
        data={
            "csrf_token": _TOKEN,
            "record_id": "rec_0000000000000001",
            "decision": "exclude",
            "criteria": "EXC-07",
            "skip": "",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303

    repo = open_repo(repo.root)
    events = all_screen_events(repo, "title-abstract")
    assert events[-1]["body"]["decision"] == "exclude"
    assert events[-1]["body"]["criteria"] == ["EXC-07"]

    r2 = client.get("/rescreen/title-abstract")
    assert "Nothing stale" in r2.text


def test_rescreen_post_requires_csrf(tmp_path: Path) -> None:
    repo = _repo_with_one_stale_record(tmp_path)
    client = _client(repo)
    r = client.post(
        "/rescreen/title-abstract",
        data={"record_id": "rec_0000000000000001", "decision": "keep", "skip": ""},
    )
    assert r.status_code == 403


def test_rescreen_post_keep_on_a_record_no_longer_stale_is_rejected(tmp_path: Path) -> None:
    repo = _repo_with_one_stale_record(tmp_path)
    client = _client(repo)
    client.post(
        "/rescreen/title-abstract",
        data={
            "csrf_token": _TOKEN,
            "record_id": "rec_0000000000000001",
            "decision": "keep",
            "skip": "",
        },
    )
    r = client.post(
        "/rescreen/title-abstract",
        data={
            "csrf_token": _TOKEN,
            "record_id": "rec_0000000000000001",
            "decision": "keep",
            "skip": "",
        },
    )
    assert r.status_code == 422
    assert "no longer in the stale queue" in r.text


def test_rescreen_skip_moves_past_a_record_without_deciding(tmp_path: Path) -> None:
    repo = _repo_with_one_stale_record(tmp_path)
    client = _client(repo)
    r = client.get("/rescreen/title-abstract?skip=rec_0000000000000001")
    assert "Nothing stale" in r.text
    events = all_screen_events(repo, "title-abstract")
    assert len(events) == 1  # only the original include, nothing new decided


def test_rescreen_redo_reopens_a_specific_stale_record(tmp_path: Path) -> None:
    repo = _repo_with_one_stale_record(tmp_path)
    client = _client(repo)
    r = client.get("/rescreen/title-abstract?redo=rec_0000000000000001")
    assert r.status_code == 200
    assert "A test record" in r.text


def test_rescreen_post_keep_on_unknown_stage_is_404(tmp_path: Path) -> None:
    repo = _repo_with_one_stale_record(tmp_path)
    client = _client(repo)
    r = client.post(
        "/rescreen/not-a-stage",
        data={
            "csrf_token": _TOKEN,
            "record_id": "rec_0000000000000001",
            "decision": "keep",
            "skip": "",
        },
    )
    assert r.status_code == 404


def test_rescreen_post_invalid_criterion_is_rejected(tmp_path: Path) -> None:
    repo = _repo_with_one_stale_record(tmp_path)
    client = _client(repo)
    r = client.post(
        "/rescreen/title-abstract",
        data={
            "csrf_token": _TOKEN,
            "record_id": "rec_0000000000000001",
            "decision": "exclude",
            "criteria": "EXC-99",
            "skip": "",
        },
    )
    assert r.status_code == 422


def test_rescreen_post_success_carries_skip_list_into_redirect(tmp_path: Path) -> None:
    repo = _repo_with_one_stale_record(tmp_path)
    client = _client(repo)
    r = client.post(
        "/rescreen/title-abstract",
        data={
            "csrf_token": _TOKEN,
            "record_id": "rec_0000000000000001",
            "decision": "keep",
            "skip": "rec_0000000000000099",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "skip=rec_0000000000000099" in r.headers["location"]
