"""Integration tests for the web criteria editor (`/criteria`):
openspec:web-ui#criteria-editor-impact-preview, the one web-UI piece the M2 roadmap acceptance
checklist names outright ("The criteria editor's impact preview is
correct and non-mutating," docs/roadmap.md)."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from strata import gitio
from strata.core.init import init_repository
from strata.core.records import write_records
from strata.core.repo import open_repo
from strata.protocol.criteria import add_criterion, read_criteria_doc
from strata.protocol.screening import all_screen_events, record_screen_decision
from strata.web.app import create_app

_TOKEN = "test-session-token-0123456789"


def _repo(tmp_path: Path):  # type: ignore[no-untyped-def]
    root = tmp_path / "review"
    init_repository(root, title="Criteria Test Review", actor_handle="ethan", actor_name="Ethan")
    return open_repo(root)


def _record(record_id: str) -> dict:
    return {
        "id": record_id,
        "type": "article-journal",
        "title": f"Title for {record_id}",
        "abstract": "An abstract.",
        "strata": {
            "canonical_key": f"sig:{record_id}",
            "canonical": True,
            "sources": [{"import": "imp_01arz3ndektsv4rrffq69g5fav"}],
        },
    }


def _client(repo) -> TestClient:  # type: ignore[no-untyped-def]
    app = create_app(repo_root=repo.root, actor="ethan", session_token=_TOKEN)
    client = TestClient(app, base_url="http://127.0.0.1:8000")
    r = client.get(f"/?token={_TOKEN}")
    assert r.status_code == 200
    return client


def _repo_with_one_stale_candidate(tmp_path: Path):  # type: ignore[no-untyped-def]
    """A repo with EXC-03 cited by one exclusion, ready to preview a
    loosen/retire of EXC-03."""
    repo = _repo(tmp_path)
    add_criterion(
        repo,
        kind="exclusion",
        label="Not in English",
        definition="Not in English.",
        applies_at=["title-abstract"],
        actor="ethan",
        rationale="Establishing the initial protocol criteria.",
        criterion_id="EXC-03",
    )
    repo = open_repo(repo.root)
    write_records(repo, [_record("rec_0000000000000001")])
    repo = open_repo(repo.root)
    record_screen_decision(
        repo,
        stage="title-abstract",
        record_id="rec_0000000000000001",
        decision="exclude",
        actor="ethan",
        cited=["EXC-03"],
    )
    repo = open_repo(repo.root)
    # add_criterion/write_records/record_screen_decision are the pure
    # protocol-layer calls the CLI itself commits after (see
    # cli.main._commit_criteria_op) -- commit the fixture setup here too,
    # so a test's own is_dirty() assertions measure the route under test,
    # not leftover fixture state.
    gitio.add_all(repo.root)
    gitio.commit(repo.root, "chore: test fixture setup\n\nStrata-Op: fixture\n")
    return open_repo(repo.root)


def test_criteria_list_shows_active_criteria(tmp_path: Path) -> None:
    repo = _repo_with_one_stale_candidate(tmp_path)
    client = _client(repo)
    r = client.get("/criteria")
    assert r.status_code == 200
    assert "EXC-03" in r.text
    assert "Not in English" in r.text


def test_criteria_edit_view_unknown_criterion_is_404(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    client = _client(repo)
    r = client.get("/criteria/EXC-99/edit")
    assert r.status_code == 404


def test_criteria_retire_view_unknown_criterion_is_404(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    client = _client(repo)
    r = client.get("/criteria/EXC-99/retire")
    assert r.status_code == 404


def test_criteria_edit_view_with_no_direction_has_no_preview(tmp_path: Path) -> None:
    repo = _repo_with_one_stale_candidate(tmp_path)
    client = _client(repo)
    r = client.get("/criteria/EXC-03/edit")
    assert r.status_code == 200
    assert "impact-preview" not in r.text


def test_criteria_edit_view_previews_loosened_impact(tmp_path: Path) -> None:
    repo = _repo_with_one_stale_candidate(tmp_path)
    client = _client(repo)
    r = client.get("/criteria/EXC-03/edit?direction=loosened")
    assert r.status_code == 200
    assert "1 decision" in r.text
    assert "criterion-loosened" in r.text
    assert "rec_0000000000000001" in r.text


def test_criteria_edit_view_previews_tightened_as_no_impact_for_an_exclusion(
    tmp_path: Path,
) -> None:
    """Tightening EXC-03 doesn't stale the exclusion that cited it (only
    loosening/retiring an exclusion's own cited criterion does, per
    openspec:staleness#the-staleness-rules) -- the preview must say so, not just "not zero"."""
    repo = _repo_with_one_stale_candidate(tmp_path)
    client = _client(repo)
    r = client.get("/criteria/EXC-03/edit?direction=tightened")
    assert r.status_code == 200
    assert "No currently-resolved decisions would become stale" in r.text


def test_criteria_edit_preview_never_mutates_the_repository(tmp_path: Path) -> None:
    repo = _repo_with_one_stale_candidate(tmp_path)
    version_before = read_criteria_doc(repo)["version"]
    client = _client(repo)
    for direction in ("tightened", "loosened", "both", "editorial"):
        client.get(f"/criteria/EXC-03/edit?direction={direction}")
    repo = open_repo(repo.root)
    assert read_criteria_doc(repo)["version"] == version_before


def test_criteria_edit_preview_carries_forward_typed_definition_and_rationale(
    tmp_path: Path,
) -> None:
    """The "Preview" button is a plain GET resubmit (no-JS baseline);
    without carrying the in-progress edit forward, refreshing the preview
    would silently discard whatever the reviewer had already typed."""
    repo = _repo_with_one_stale_candidate(tmp_path)
    client = _client(repo)
    r = client.get(
        "/criteria/EXC-03/edit"
        "?direction=loosened&definition=A+draft+definition&rationale=still+typing"
    )
    assert "A draft definition" in r.text
    assert "still typing" in r.text


def test_criteria_edit_post_saves_and_commits(tmp_path: Path) -> None:
    repo = _repo_with_one_stale_candidate(tmp_path)
    client = _client(repo)
    r = client.post(
        "/criteria/EXC-03/edit",
        data={
            "csrf_token": _TOKEN,
            "direction": "loosened",
            "definition": "Not in English, translations excepted.",
            "rationale": "Relaxing the language criterion to include translations.",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/criteria"

    repo = open_repo(repo.root)
    doc = read_criteria_doc(repo)
    assert doc["version"] == 2
    (criterion,) = [c for c in doc["criteria"] if c["id"] == "EXC-03"]
    assert criterion["definition"] == "Not in English, translations excepted."

    assert not gitio.is_dirty(repo.root)


def test_criteria_edit_post_without_rationale_is_rejected_and_non_mutating(
    tmp_path: Path,
) -> None:
    repo = _repo_with_one_stale_candidate(tmp_path)
    version_before = read_criteria_doc(repo)["version"]
    client = _client(repo)
    r = client.post(
        "/criteria/EXC-03/edit",
        data={"csrf_token": _TOKEN, "direction": "loosened", "definition": "x"},
    )
    assert r.status_code == 422
    assert "rationale" in r.text.lower()

    repo = open_repo(repo.root)
    assert read_criteria_doc(repo)["version"] == version_before


def test_criteria_edit_post_unknown_criterion_is_404(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    client = _client(repo)
    r = client.post(
        "/criteria/EXC-99/edit",
        data={
            "csrf_token": _TOKEN,
            "direction": "loosened",
            "rationale": "Doesn't matter, this criterion doesn't exist.",
        },
    )
    assert r.status_code == 404


def test_criteria_edit_post_requires_csrf(tmp_path: Path) -> None:
    repo = _repo_with_one_stale_candidate(tmp_path)
    client = _client(repo)
    r = client.post(
        "/criteria/EXC-03/edit",
        data={
            "direction": "loosened",
            "definition": "x",
            "rationale": "A long enough rationale for this edit.",
        },
    )
    assert r.status_code == 403


def test_criteria_retire_view_previews_as_loosened_regardless_of_query(tmp_path: Path) -> None:
    repo = _repo_with_one_stale_candidate(tmp_path)
    client = _client(repo)
    r = client.get("/criteria/EXC-03/retire")
    assert r.status_code == 200
    assert "criterion-retired" in r.text
    assert "rec_0000000000000001" in r.text


def test_criteria_retire_post_retires_and_commits(tmp_path: Path) -> None:
    repo = _repo_with_one_stale_candidate(tmp_path)
    client = _client(repo)
    r = client.post(
        "/criteria/EXC-03/retire",
        data={"csrf_token": _TOKEN, "rationale": "No longer part of the protocol."},
        follow_redirects=False,
    )
    assert r.status_code == 303

    repo = open_repo(repo.root)
    doc = read_criteria_doc(repo)
    (criterion,) = [c for c in doc["criteria"] if c["id"] == "EXC-03"]
    assert criterion["status"] == "retired"

    assert not gitio.is_dirty(repo.root)


def test_criteria_retire_post_already_retired_is_rejected(tmp_path: Path) -> None:
    repo = _repo_with_one_stale_candidate(tmp_path)
    client = _client(repo)
    client.post(
        "/criteria/EXC-03/retire",
        data={"csrf_token": _TOKEN, "rationale": "No longer part of the protocol."},
    )
    r = client.post(
        "/criteria/EXC-03/retire",
        data={"csrf_token": _TOKEN, "rationale": "Trying to retire it again."},
    )
    assert r.status_code == 422
    assert "already retired" in r.text.lower()


def test_criteria_retire_post_unknown_criterion_is_404(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    client = _client(repo)
    r = client.post(
        "/criteria/EXC-99/retire",
        data={"csrf_token": _TOKEN, "rationale": "Doesn't matter."},
    )
    assert r.status_code == 404


def test_criteria_editing_leaves_screen_events_untouched(tmp_path: Path) -> None:
    """A sanity check that the preview/save cycle above only ever touches
    criteria.yaml + derived views, never the screen event log itself."""
    repo = _repo_with_one_stale_candidate(tmp_path)
    events_before = all_screen_events(repo, "title-abstract")
    client = _client(repo)
    client.get("/criteria/EXC-03/edit?direction=loosened")
    client.post(
        "/criteria/EXC-03/edit",
        data={
            "csrf_token": _TOKEN,
            "direction": "loosened",
            "definition": "Not in English, translations excepted.",
            "rationale": "Relaxing the language criterion to include translations.",
        },
    )
    repo = open_repo(repo.root)
    assert all_screen_events(repo, "title-abstract") == events_before
