"""Unit tests for strata.core.provenance ("strata why"), docs/spec/10-cli.md §2."""

from __future__ import annotations

from pathlib import Path

from strata.core.events import append_event, append_new_event, build_envelope
from strata.core.init import init_repository
from strata.core.provenance import build_provenance
from strata.core.repo import Repo, open_repo
from strata.protocol import searches as searches_mod


def _repo(tmp_path: Path) -> Repo:
    root = tmp_path / "review"
    init_repository(root, title="T", actor_handle="ethan", actor_name="Ethan")
    return open_repo(root)


def test_build_provenance_empty_for_untouched_record(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    assert build_provenance(repo, "rec_0000000000000001") == []


def test_build_provenance_record_add_only(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    events_path = repo.path("events", "import", "ethan.ndjson")
    append_new_event(
        events_path,
        ev="record-add",
        actor="ethan",
        body={"record": "rec_0000000000000001", "import_id": "imp_x", "raw_row_digest": "sha256:x"},
    )
    entries = build_provenance(repo, "rec_0000000000000001")
    assert [e.kind for e in entries] == ["record-add"]
    assert entries[0].actor == "ethan"
    assert entries[0].detail["import_id"] == "imp_x"


def test_build_provenance_full_chain_with_search_and_import(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    searches_mod.add_search(
        repo,
        database="MEDLINE",
        platform="Ovid",
        executed="2026-01-01",
        executed_by="ethan",
        search_id="S-01-medline",
        query="1 exp Learning/",
    )
    events_path = repo.path("events", "import", "ethan.ndjson")
    append_new_event(
        events_path,
        ev="record-add",
        actor="ethan",
        body={"record": "rec_0000000000000001", "import_id": "imp_x", "raw_row_digest": "sha256:x"},
    )
    append_new_event(
        events_path,
        ev="import",
        actor="ethan",
        body={
            "import_id": "imp_x",
            "search_id": "S-01-medline",
            "source": "export.ris",
            "count": 1,
            "file_digest": "sha256:y",
        },
    )

    entries = build_provenance(repo, "rec_0000000000000001")
    assert [e.kind for e in entries] == ["search", "import", "record-add"]
    assert entries[0].detail["id"] == "S-01-medline"
    assert entries[1].detail["source"] == "export.ris"
    assert entries[2].detail["import_id"] == "imp_x"


def test_build_provenance_includes_dedup_merge_for_canonical_and_absorbed(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    events_path = repo.path("events", "dedup", "ethan.ndjson")
    append_new_event(
        events_path,
        ev="dedup-merge",
        actor="ethan",
        body={
            "canonical": "rec_0000000000000001",
            "absorbed": "rec_0000000000000002",
            "score": 1.0,
            "method": "auto-threshold",
            "features": {},
        },
    )
    for record_id in ("rec_0000000000000001", "rec_0000000000000002"):
        entries = build_provenance(repo, record_id)
        assert [e.kind for e in entries] == ["dedup-merge"]
        assert entries[0].detail["canonical"] == "rec_0000000000000001"


def test_build_provenance_includes_dedup_distinct_for_either_side(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    events_path = repo.path("events", "dedup", "ethan.ndjson")
    append_new_event(
        events_path,
        ev="dedup-distinct",
        actor="ethan",
        body={
            "a": "rec_0000000000000001",
            "b": "rec_0000000000000002",
            "score": 0.5,
            "method": "manual-review",
        },
    )
    assert [e.kind for e in build_provenance(repo, "rec_0000000000000001")] == ["dedup-distinct"]
    assert [e.kind for e in build_provenance(repo, "rec_0000000000000002")] == ["dedup-distinct"]
    assert build_provenance(repo, "rec_0000000000000003") == []


def test_build_provenance_includes_dedup_unmerge_for_restored(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    events_path = repo.path("events", "dedup", "ethan.ndjson")
    append_new_event(
        events_path,
        ev="dedup-unmerge",
        actor="ethan",
        body={"canonical": "rec_0000000000000001", "restored": "rec_0000000000000002"},
    )
    assert [e.kind for e in build_provenance(repo, "rec_0000000000000002")] == ["dedup-unmerge"]


def test_build_provenance_includes_amendments(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    events_path = repo.path("events", "fix", "ethan.ndjson")
    append_new_event(
        events_path,
        ev="record-amend",
        actor="ethan",
        body={
            "record": "rec_0000000000000001",
            "field": "title",
            "old": "A",
            "new": "B",
            "source": "manual",
        },
    )
    entries = build_provenance(repo, "rec_0000000000000001")
    assert [e.kind for e in entries] == ["record-amend"]
    assert entries[0].detail["new"] == "B"


def test_build_provenance_dedup_and_amend_events_sorted_chronologically(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    dedup_path = repo.path("events", "dedup", "ethan.ndjson")
    fix_path = repo.path("events", "fix", "ethan.ndjson")
    append_event(
        dedup_path,
        build_envelope(
            ev="dedup-merge",
            actor="ethan",
            seq=1,
            ts="2026-01-02T00:00:00Z",
            body={
                "canonical": "rec_0000000000000001",
                "absorbed": "rec_0000000000000002",
                "score": 1.0,
                "method": "auto-threshold",
                "features": {},
            },
        ),
    )
    append_event(
        fix_path,
        build_envelope(
            ev="record-amend",
            actor="ethan",
            seq=1,
            ts="2026-01-01T00:00:00Z",
            body={
                "record": "rec_0000000000000001",
                "field": "title",
                "old": "A",
                "new": "B",
                "source": "manual",
            },
        ),
    )
    entries = build_provenance(repo, "rec_0000000000000001")
    assert [e.kind for e in entries] == ["record-amend", "dedup-merge"]
