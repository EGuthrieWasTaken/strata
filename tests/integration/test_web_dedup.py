"""Integration tests for the duplicate review queue (`/dedup`):
docs/spec/05-workflow-import.md §3, docs/spec/11-web-ui.md §2.

`GET /dedup` is backed by `dedup.engine.preview_dedup`, a non-mutating dry
run -- these tests lean on that by asserting the repo is untouched after a
plain `GET`, the same discipline `test_web_criteria.py` applies to the
criteria editor's impact preview."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from strata import gitio
from strata.core.init import init_repository
from strata.core.records import read_records, write_records
from strata.core.repo import open_repo
from strata.dedup.engine import judged_pairs
from strata.web.app import create_app

_TOKEN = "test-session-token-0123456789"


def _record(record_id: str, **fields: Any) -> dict[str, Any]:
    return {
        "id": record_id,
        "type": "article-journal",
        "title": fields.pop("title", "A Title"),
        "strata": {
            "canonical_key": f"sig:{record_id}",
            "canonical": True,
            "sources": [{"import": "imp_01arz3ndektsv4rrffq69g5fav"}],
        },
        **fields,
    }


def _init(tmp_path: Path, *, require_rationale: bool = True):  # type: ignore[no-untyped-def]
    root = tmp_path / "review"
    init_repository(root, title="Dedup Test", actor_handle="ethan", actor_name="Ethan")
    if not require_rationale:
        manifest = root / "strata.toml"
        manifest.write_text(
            manifest.read_text(encoding="utf-8").replace(
                "require_rationale = true", "require_rationale = false"
            ),
            encoding="utf-8",
        )
    return root


def _commit_fixture(root: Path) -> None:
    gitio.add_all(root)
    gitio.commit(root, "chore: test fixture setup\n\nStrata-Op: fixture\n")


def _repo_with_nothing_pending(tmp_path: Path):  # type: ignore[no-untyped-def]
    root = _init(tmp_path)
    return open_repo(root)


def _repo_with_review_pair(tmp_path: Path, *, require_rationale: bool = True):  # type: ignore[no-untyped-def]
    root = _init(tmp_path, require_rationale=require_rationale)
    repo = open_repo(root)
    a = _record(
        "rec_0000000000000001",
        title="Spacing effects in learning: A meta-analysis",
        author=[{"family": "Cepeda"}, {"family": "Vul"}],
        issued={"date-parts": [[2008]]},
    )
    b = _record(
        "rec_0000000000000002",
        title="Spacing effects in learning - A meta analysis",
        author=[{"family": "Cepeda"}, {"family": "Vul"}],
        issued={"date-parts": [[2008]]},
    )
    write_records(repo, [a, b])
    _commit_fixture(root)
    return open_repo(root)


def _repo_with_auto_merge_pair(tmp_path: Path):  # type: ignore[no-untyped-def]
    root = _init(tmp_path)
    repo = open_repo(root)
    a = _record("rec_0000000000000001", DOI="10.1000/aaa")
    b = _record("rec_0000000000000002", DOI="10.1000/aaa", author=[{"family": "Cepeda"}])
    write_records(repo, [a, b])
    _commit_fixture(root)
    return open_repo(root)


def _client(repo) -> TestClient:  # type: ignore[no-untyped-def]
    app = create_app(repo_root=repo.root, actor="ethan", session_token=_TOKEN)
    client = TestClient(app, base_url="http://127.0.0.1:8000")
    r = client.get(f"/?token={_TOKEN}")
    assert r.status_code == 200
    return client


def test_dedup_with_nothing_pending(tmp_path: Path) -> None:
    repo = _repo_with_nothing_pending(tmp_path)
    client = _client(repo)
    r = client.get("/dedup")
    assert r.status_code == 200
    assert "Nothing pending review" in r.text


def test_dedup_shows_a_review_candidate(tmp_path: Path) -> None:
    repo = _repo_with_review_pair(tmp_path)
    client = _client(repo)
    r = client.get("/dedup")
    assert r.status_code == 200
    assert "rec_0000000000000001" in r.text
    assert "rec_0000000000000002" in r.text
    assert "1 pending" in r.text


def test_dedup_get_is_non_mutating(tmp_path: Path) -> None:
    """The whole reason `preview_dedup` exists: a plain `GET /dedup` must
    never write `records.ndjson`, an event, or an alias, and must leave
    the working tree clean."""
    repo = _repo_with_auto_merge_pair(tmp_path)
    client = _client(repo)
    r = client.get("/dedup")
    assert r.status_code == 200
    assert "would auto-merge" in r.text

    repo2 = open_repo(repo.root)
    records = {r["id"]: r for r in read_records(repo2)}
    assert records["rec_0000000000000001"]["strata"]["canonical"] is True
    assert records["rec_0000000000000002"]["strata"]["canonical"] is True
    assert judged_pairs(repo2) == set()
    assert not gitio.is_dirty(repo2.root)


def test_dedup_shows_candidate_pairs_considered_summary(tmp_path: Path) -> None:
    repo = _repo_with_nothing_pending(tmp_path)
    client = _client(repo)
    r = client.get("/dedup")
    assert r.status_code == 200
    assert "0 candidate pairs considered" in r.text


def test_dedup_decide_merge_commits_and_resolves(tmp_path: Path) -> None:
    repo = _repo_with_review_pair(tmp_path)
    client = _client(repo)
    r = client.post(
        "/dedup/decide",
        data={
            "csrf_token": _TOKEN,
            "record_a": "rec_0000000000000001",
            "record_b": "rec_0000000000000002",
            "decision": "merge",
            "rationale": "These are clearly the same study, merging them.",
            "skip": "",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/dedup"

    repo2 = open_repo(repo.root)
    records = {r["id"]: r for r in read_records(repo2)}
    canonical = [r for r in records.values() if r["strata"]["canonical"]]
    assert len(canonical) == 1
    assert not gitio.is_dirty(repo2.root)

    r2 = client.get("/dedup")
    assert "Nothing pending review" in r2.text


def test_dedup_decide_keep_both_is_sticky(tmp_path: Path) -> None:
    repo = _repo_with_review_pair(tmp_path)
    client = _client(repo)
    r = client.post(
        "/dedup/decide",
        data={
            "csrf_token": _TOKEN,
            "record_a": "rec_0000000000000001",
            "record_b": "rec_0000000000000002",
            "decision": "keep",
            "rationale": "These are two distinct studies despite the similar titles.",
            "skip": "",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303

    repo2 = open_repo(repo.root)
    records = {r["id"]: r for r in read_records(repo2)}
    assert records["rec_0000000000000001"]["strata"]["canonical"] is True
    assert records["rec_0000000000000002"]["strata"]["canonical"] is True
    assert judged_pairs(repo2) == {("rec_0000000000000001", "rec_0000000000000002")}
    assert not gitio.is_dirty(repo2.root)

    r2 = client.get("/dedup")
    assert "Nothing pending review" in r2.text


def test_dedup_decide_no_longer_pending_is_rejected(tmp_path: Path) -> None:
    repo = _repo_with_review_pair(tmp_path)
    client = _client(repo)
    r = client.post(
        "/dedup/decide",
        data={
            "csrf_token": _TOKEN,
            "record_a": "rec_0000000000000098",
            "record_b": "rec_0000000000000099",
            "decision": "merge",
            "rationale": "This pair is not actually in the queue.",
            "skip": "",
        },
    )
    assert r.status_code == 422
    assert "no longer pending review" in r.text


def test_dedup_decide_unknown_decision_is_rejected(tmp_path: Path) -> None:
    repo = _repo_with_review_pair(tmp_path)
    client = _client(repo)
    r = client.post(
        "/dedup/decide",
        data={
            "csrf_token": _TOKEN,
            "record_a": "rec_0000000000000001",
            "record_b": "rec_0000000000000002",
            "decision": "not-a-real-decision",
            "rationale": "Trying an invalid decision.",
            "skip": "",
        },
    )
    assert r.status_code == 422
    assert "unknown decision" in r.text


def test_dedup_decide_without_rationale_is_rejected_by_default(tmp_path: Path) -> None:
    repo = _repo_with_review_pair(tmp_path)
    client = _client(repo)
    r = client.post(
        "/dedup/decide",
        data={
            "csrf_token": _TOKEN,
            "record_a": "rec_0000000000000001",
            "record_b": "rec_0000000000000002",
            "decision": "merge",
            "rationale": "",
            "skip": "",
        },
    )
    assert r.status_code == 422
    repo2 = open_repo(repo.root)
    assert judged_pairs(repo2) == set()


def test_dedup_decide_without_rationale_is_allowed_when_not_required(tmp_path: Path) -> None:
    repo = _repo_with_review_pair(tmp_path, require_rationale=False)
    client = _client(repo)
    r = client.post(
        "/dedup/decide",
        data={
            "csrf_token": _TOKEN,
            "record_a": "rec_0000000000000001",
            "record_b": "rec_0000000000000002",
            "decision": "keep",
            "rationale": "",
            "skip": "",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    repo2 = open_repo(repo.root)
    assert judged_pairs(repo2) == {("rec_0000000000000001", "rec_0000000000000002")}


def test_dedup_decide_requires_csrf(tmp_path: Path) -> None:
    repo = _repo_with_review_pair(tmp_path)
    client = _client(repo)
    r = client.post(
        "/dedup/decide",
        data={
            "record_a": "rec_0000000000000001",
            "record_b": "rec_0000000000000002",
            "decision": "merge",
            "rationale": "Trying without a CSRF token.",
            "skip": "",
        },
    )
    assert r.status_code == 403


def test_dedup_decide_carries_skip_list_into_redirect(tmp_path: Path) -> None:
    repo = _repo_with_review_pair(tmp_path)
    client = _client(repo)
    r = client.post(
        "/dedup/decide",
        data={
            "csrf_token": _TOKEN,
            "record_a": "rec_0000000000000001",
            "record_b": "rec_0000000000000002",
            "decision": "keep",
            "rationale": "These are two distinct studies.",
            "skip": "rec_0000000000000098:rec_0000000000000099",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "skip=rec_0000000000000098:rec_0000000000000099" in r.headers["location"]


def test_dedup_skip_moves_past_a_pair_without_resolving(tmp_path: Path) -> None:
    repo = _repo_with_review_pair(tmp_path)
    client = _client(repo)
    r = client.get("/dedup?skip=rec_0000000000000001%3Arec_0000000000000002")
    assert "Nothing pending review" in r.text
    repo2 = open_repo(repo.root)
    assert judged_pairs(repo2) == set()


def test_dedup_run_auto_merges_for_real_and_commits(tmp_path: Path) -> None:
    repo = _repo_with_auto_merge_pair(tmp_path)
    client = _client(repo)
    r = client.post(
        "/dedup/run",
        data={"csrf_token": _TOKEN, "rationale": "Running the auto-merge pass before review."},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/dedup"

    repo2 = open_repo(repo.root)
    records = {r["id"]: r for r in read_records(repo2)}
    canonical = [r for r in records.values() if r["strata"]["canonical"]]
    assert len(canonical) == 1
    assert not gitio.is_dirty(repo2.root)


def test_dedup_run_with_nothing_to_merge_does_not_commit(tmp_path: Path) -> None:
    repo = _repo_with_review_pair(tmp_path)  # only a review candidate, no auto-merge
    client = _client(repo)
    r = client.post(
        "/dedup/run",
        data={"csrf_token": _TOKEN, "rationale": "Nothing should actually happen here."},
        follow_redirects=False,
    )
    assert r.status_code == 303
    repo2 = open_repo(repo.root)
    assert not gitio.is_dirty(repo2.root)


def test_dedup_run_requires_csrf(tmp_path: Path) -> None:
    repo = _repo_with_auto_merge_pair(tmp_path)
    client = _client(repo)
    r = client.post("/dedup/run", data={"rationale": "Trying without a CSRF token."})
    assert r.status_code == 403


def test_dedup_run_without_rationale_is_rejected_by_default(tmp_path: Path) -> None:
    repo = _repo_with_auto_merge_pair(tmp_path)
    client = _client(repo)
    r = client.post(
        "/dedup/run",
        data={"csrf_token": _TOKEN, "rationale": ""},
    )
    assert r.status_code == 422
    repo2 = open_repo(repo.root)
    assert not gitio.is_dirty(repo2.root)
    records = {r["id"]: r for r in read_records(repo2)}
    assert records["rec_0000000000000001"]["strata"]["canonical"] is True
    assert records["rec_0000000000000002"]["strata"]["canonical"] is True
