import json
import tomllib
from pathlib import Path

import pytest

from strata.core.events import append_new_event
from strata.core.repo import Repo
from strata.core.verify import verify_repository

_VALID_MANIFEST = """\
schema_version = 1
created_with = "strata/0.1.0"

[project]
id = "prj_x"
title = "T"
slug = "t"
created = "2026-01-01"

[[actors]]
handle = "ethan"
name = "Ethan"
role = "lead"
"""


def _make_repo(tmp_path: Path, manifest_text: str = _VALID_MANIFEST) -> Repo:
    (tmp_path / "strata.toml").write_text(manifest_text, encoding="utf-8")
    config = tomllib.loads(manifest_text)
    return Repo(root=tmp_path, config=config)


def _valid_record(record_id: str, **overrides: object) -> dict:
    record = {
        "id": record_id,
        "type": "article-journal",
        "title": "x",
        "strata": {
            "canonical_key": f"sig:{record_id}",
            "canonical": True,
            "sources": [{"import": "imp_01arz3ndektsv4rrffq69g5fav"}],
        },
    }
    record.update(overrides)
    return record


def test_verify_passes_on_minimal_valid_repo(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    report = verify_repository(repo)
    assert report.ok
    assert report.issues == []


def test_verify_reports_manifest_schema_errors(tmp_path: Path) -> None:
    (tmp_path / "strata.toml").write_text(_VALID_MANIFEST, encoding="utf-8")
    repo = Repo(root=tmp_path, config={"schema_version": 1})  # missing required fields
    report = verify_repository(repo)
    assert not report.ok
    assert any(i.code == "E_SCHEMA" and i.path == "strata.toml" for i in report.issues)


def test_verify_reports_event_schema_errors(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    bad_event_path = repo.path("events", "screen", "title-abstract.ethan.ndjson")
    bad_event_path.parent.mkdir(parents=True)
    bad_event_path.write_text('{"ev":"screen","id":"not-a-valid-id"}\n', encoding="utf-8")
    report = verify_repository(repo, fast=True)
    assert any(i.code == "E_SCHEMA" for i in report.issues)


@pytest.mark.req("E_CHAIN")
def test_verify_reports_chain_violations_unless_fast(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    path = repo.path("events", "note", "ethan.ndjson")
    append_new_event(path, ev="note", actor="ethan", body={"subject": "s", "text": "t"})
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace('"text":"t"', '"text":"TAMPERED"'), encoding="utf-8")

    fast_report = verify_repository(repo, fast=True)
    assert not any(i.code == "E_CHAIN" for i in fast_report.issues)

    full_report = verify_repository(repo, fast=False)
    assert any(i.code == "E_CHAIN" for i in full_report.issues)


@pytest.mark.req("E_DANGLING_REF")
def test_verify_reports_dangling_record_reference(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    path = repo.path("events", "screen", "title-abstract.ethan.ndjson")
    append_new_event(
        path,
        ev="screen",
        actor="ethan",
        body={
            "stage": "title-abstract",
            "record": "rec_doesnotexist000000",
            "decision": "include",
            "criteria": [],
            "criteria_version": 1,
        },
    )
    report = verify_repository(repo)
    assert any(
        i.code == "E_DANGLING_REF" and "rec_doesnotexist000000" in i.message for i in report.issues
    )


def test_verify_accepts_reference_to_known_record(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    records_path = repo.path("records", "records.ndjson")
    records_path.parent.mkdir(parents=True, exist_ok=True)
    records_path.write_text(
        json.dumps(_valid_record("rec_0000000000000001")) + "\n", encoding="utf-8"
    )
    path = repo.path("events", "screen", "title-abstract.ethan.ndjson")
    append_new_event(
        path,
        ev="screen",
        actor="ethan",
        body={
            "stage": "title-abstract",
            "record": "rec_0000000000000001",
            "decision": "include",
            "criteria": [],
            "criteria_version": 1,
        },
    )
    report = verify_repository(repo)
    assert not any(i.code == "E_DANGLING_REF" for i in report.issues)


def test_verify_accepts_dedup_merge_referencing_alias(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    records_path = repo.path("records", "records.ndjson")
    aliases_path = repo.path("records", "aliases.ndjson")
    records_path.parent.mkdir(parents=True, exist_ok=True)
    records_path.write_text(
        json.dumps(_valid_record("rec_0000000000000002")) + "\n", encoding="utf-8"
    )
    aliases_path.write_text(
        json.dumps({"alias": "rec_0000000000000003", "canonical": "rec_0000000000000002"}) + "\n",
        encoding="utf-8",
    )
    path = repo.path("events", "dedup", "ethan.ndjson")
    append_new_event(
        path,
        ev="dedup-merge",
        actor="ethan",
        body={
            "canonical": "rec_0000000000000002",
            "absorbed": ["rec_0000000000000003"],
            "score": 1.0,
            "method": "exact-doi",
        },
    )
    report = verify_repository(repo)
    assert not any(i.code == "E_DANGLING_REF" for i in report.issues)


@pytest.mark.req("E_ALIAS_CYCLE")
def test_verify_detects_alias_cycle(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    aliases_path = repo.path("records", "aliases.ndjson")
    aliases_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        json.dumps({"alias": "rec_aaaaaaaaaaaaaaaa", "canonical": "rec_bbbbbbbbbbbbbbbb"}),
        json.dumps({"alias": "rec_bbbbbbbbbbbbbbbb", "canonical": "rec_aaaaaaaaaaaaaaaa"}),
    ]
    aliases_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    report = verify_repository(repo)
    assert any(i.code == "E_ALIAS_CYCLE" for i in report.issues)


def test_verify_reports_invalid_search_file(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    searches_path = repo.path("protocol", "searches", "S-01-medline.yaml")
    searches_path.parent.mkdir(parents=True, exist_ok=True)
    # Missing the required `query` field.
    searches_path.write_text(
        "id: S-01-medline\ndatabase: MEDLINE\nplatform: Ovid\n"
        "executed: '2026-03-04'\nexecuted_by: ethan\n",
        encoding="utf-8",
    )
    report = verify_repository(repo)
    assert any(
        i.code == "E_SCHEMA" and i.path == "protocol/searches/S-01-medline.yaml"
        for i in report.issues
    )


def test_verify_accepts_valid_search_file(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    searches_path = repo.path("protocol", "searches", "S-01-medline.yaml")
    searches_path.parent.mkdir(parents=True, exist_ok=True)
    searches_path.write_text(
        "id: S-01-medline\ndatabase: MEDLINE\nplatform: Ovid\n"
        "executed: '2026-03-04'\nexecuted_by: ethan\nquery: |\n  1 exp Learning/\n",
        encoding="utf-8",
    )
    report = verify_repository(repo)
    assert not any(i.code == "E_SCHEMA" and "searches" in (i.path or "") for i in report.issues)


def test_verify_ignores_blank_search_file(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    searches_path = repo.path("protocol", "searches", "S-01-blank.yaml")
    searches_path.parent.mkdir(parents=True, exist_ok=True)
    searches_path.write_text("", encoding="utf-8")
    report = verify_repository(repo)
    assert not any("searches" in (i.path or "") for i in report.issues)


def test_verify_accepts_valid_record(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    records_path = repo.path("records", "records.ndjson")
    records_path.parent.mkdir(parents=True, exist_ok=True)
    records_path.write_text(
        json.dumps(_valid_record("rec_0000000000000001")) + "\n", encoding="utf-8"
    )
    report = verify_repository(repo)
    assert not any(i.code == "E_SCHEMA" and "records" in (i.path or "") for i in report.issues)


@pytest.mark.req("E_SCHEMA")
def test_verify_reports_invalid_record_schema(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    records_path = repo.path("records", "records.ndjson")
    records_path.parent.mkdir(parents=True, exist_ok=True)
    invalid = _valid_record("rec_0000000000000001")
    del invalid["strata"]
    records_path.write_text(json.dumps(invalid) + "\n", encoding="utf-8")
    report = verify_repository(repo)
    assert any(i.code == "E_SCHEMA" and i.path == "records/records.ndjson" for i in report.issues)


def test_verify_ignores_blank_lines_in_records_ndjson(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    records_path = repo.path("records", "records.ndjson")
    records_path.parent.mkdir(parents=True, exist_ok=True)
    records_path.write_text(
        json.dumps(_valid_record("rec_0000000000000001")) + "\n\n", encoding="utf-8"
    )
    report = verify_repository(repo)
    assert not any(i.code == "E_SCHEMA" and "records" in (i.path or "") for i in report.issues)


def test_verify_missing_records_file_is_not_an_error(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    report = verify_repository(repo)
    assert report.ok


def test_verify_reports_invalid_criteria_file(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    criteria_path = repo.path("protocol", "criteria.yaml")
    criteria_path.parent.mkdir(parents=True, exist_ok=True)
    # `id` does not match the INC-nn/EXC-nn pattern.
    criteria_path.write_text(
        "version: 1\n"
        'digest: "sha256:' + "0" * 64 + '"\n'
        "criteria:\n"
        "  - id: NOT-VALID\n"
        "    kind: exclusion\n"
        "    label: x\n"
        "    definition: x\n"
        "    applies_at: [title-abstract]\n"
        "    since_version: 1\n"
        "    status: active\n",
        encoding="utf-8",
    )
    report = verify_repository(repo)
    assert any(i.code == "E_SCHEMA" and i.path == "protocol/criteria.yaml" for i in report.issues)


def test_verify_ignores_blank_criteria_file(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    criteria_path = repo.path("protocol", "criteria.yaml")
    criteria_path.parent.mkdir(parents=True, exist_ok=True)
    criteria_path.write_text("", encoding="utf-8")
    report = verify_repository(repo)
    assert not any("criteria" in (i.path or "") for i in report.issues)


@pytest.mark.req("E_CRITERION_REUSE")
def test_verify_detects_criterion_id_reuse(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    path = repo.path("events", "criteria", "ethan.ndjson")
    common_delta = {
        "id": "EXC-01",
        "origin": "added",
        "direction": "tightened",
        "kind": "exclusion",
        "label": "x",
        "definition": "x",
        "applies_at": ["title-abstract"],
        "since_version": 1,
        "status": "active",
    }
    append_new_event(
        path,
        ev="criteria-change",
        actor="ethan",
        body={"from_version": 0, "to_version": 1, "deltas": [common_delta], "rationale": "r1"},
    )
    reused_delta = {**common_delta, "since_version": 3}
    append_new_event(
        path,
        ev="criteria-change",
        actor="ethan",
        body={"from_version": 2, "to_version": 3, "deltas": [reused_delta], "rationale": "r2"},
    )
    report = verify_repository(repo)
    assert any(i.code == "E_CRITERION_REUSE" and "EXC-01" in i.message for i in report.issues)


def test_verify_does_not_flag_edit_or_retire_as_reuse(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    path = repo.path("events", "criteria", "ethan.ndjson")
    added = {
        "id": "EXC-01",
        "origin": "added",
        "direction": "tightened",
        "kind": "exclusion",
        "label": "x",
        "definition": "x",
        "applies_at": ["title-abstract"],
        "since_version": 1,
        "status": "active",
    }
    edited = {**added, "origin": "edited", "direction": "loosened", "definition": "x, relaxed"}
    retired = {**edited, "origin": "retired", "status": "retired"}
    append_new_event(
        path,
        ev="criteria-change",
        actor="ethan",
        body={"from_version": 0, "to_version": 1, "deltas": [added], "rationale": "r1"},
    )
    append_new_event(
        path,
        ev="criteria-change",
        actor="ethan",
        body={"from_version": 1, "to_version": 2, "deltas": [edited], "rationale": "r2"},
    )
    append_new_event(
        path,
        ev="criteria-change",
        actor="ethan",
        body={"from_version": 2, "to_version": 3, "deltas": [retired], "rationale": "r3"},
    )
    report = verify_repository(repo)
    assert not any(i.code == "E_CRITERION_REUSE" for i in report.issues)


def _add_active_criterion(repo: Repo, *, criterion_id: str, applies_at: list[str]) -> None:
    path = repo.path("events", "criteria", "ethan.ndjson")
    delta = {
        "id": criterion_id,
        "origin": "added",
        "direction": "tightened",
        "kind": "exclusion",
        "label": "x",
        "definition": "x",
        "applies_at": applies_at,
        "since_version": 1,
        "status": "active",
    }
    append_new_event(
        path,
        ev="criteria-change",
        actor="ethan",
        body={"from_version": 0, "to_version": 1, "deltas": [delta], "rationale": "r"},
    )


@pytest.mark.req("E_EXCLUSION_NO_CRITERION")
def test_verify_reports_exclusion_with_no_criterion_when_required(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    path = repo.path("events", "screen", "title-abstract.ethan.ndjson")
    append_new_event(
        path,
        ev="screen",
        actor="ethan",
        body={
            "stage": "title-abstract",
            "record": "rec_0000000000000001",
            "decision": "exclude",
            "criteria": [],
            "criteria_version": 0,
        },
    )
    report = verify_repository(repo)
    assert any(i.code == "E_EXCLUSION_NO_CRITERION" for i in report.issues)


def test_verify_allows_exclusion_with_no_criterion_when_not_required(tmp_path: Path) -> None:
    manifest = _VALID_MANIFEST.replace(
        'role = "lead"\n', 'role = "lead"\n\n[screening]\nrequire_exclusion_reason = false\n'
    )
    repo = _make_repo(tmp_path, manifest)
    path = repo.path("events", "screen", "title-abstract.ethan.ndjson")
    append_new_event(
        path,
        ev="screen",
        actor="ethan",
        body={
            "stage": "title-abstract",
            "record": "rec_0000000000000001",
            "decision": "exclude",
            "criteria": [],
            "criteria_version": 0,
        },
    )
    report = verify_repository(repo)
    assert not any(i.code == "E_EXCLUSION_NO_CRITERION" for i in report.issues)


def test_verify_full_text_exclusion_always_needs_a_criterion(tmp_path: Path) -> None:
    manifest = _VALID_MANIFEST.replace(
        'role = "lead"\n', 'role = "lead"\n\n[screening]\nrequire_exclusion_reason = false\n'
    )
    repo = _make_repo(tmp_path, manifest)
    path = repo.path("events", "screen", "full-text.ethan.ndjson")
    append_new_event(
        path,
        ev="screen",
        actor="ethan",
        body={
            "stage": "full-text",
            "record": "rec_0000000000000001",
            "decision": "exclude",
            "criteria": [],
            "criteria_version": 0,
        },
    )
    report = verify_repository(repo)
    assert any(i.code == "E_EXCLUSION_NO_CRITERION" for i in report.issues)


@pytest.mark.req("E_CRITERION_STAGE")
def test_verify_reports_citation_of_criterion_not_applicable_at_stage(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    _add_active_criterion(repo, criterion_id="EXC-01", applies_at=["full-text"])
    path = repo.path("events", "screen", "title-abstract.ethan.ndjson")
    append_new_event(
        path,
        ev="screen",
        actor="ethan",
        body={
            "stage": "title-abstract",
            "record": "rec_0000000000000001",
            "decision": "exclude",
            "criteria": ["EXC-01"],
            "criteria_version": 1,
        },
    )
    report = verify_repository(repo)
    assert any(i.code == "E_CRITERION_STAGE" for i in report.issues)


def test_verify_reports_citation_of_unknown_or_retired_criterion(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    path = repo.path("events", "screen", "title-abstract.ethan.ndjson")
    append_new_event(
        path,
        ev="screen",
        actor="ethan",
        body={
            "stage": "title-abstract",
            "record": "rec_0000000000000001",
            "decision": "exclude",
            "criteria": ["EXC-99"],
            "criteria_version": 1,
        },
    )
    report = verify_repository(repo)
    assert any(i.code == "E_CRITERION_STAGE" and "EXC-99" in i.message for i in report.issues)


def test_verify_accepts_valid_citation_at_the_right_stage(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    _add_active_criterion(repo, criterion_id="EXC-01", applies_at=["title-abstract"])
    path = repo.path("events", "screen", "title-abstract.ethan.ndjson")
    append_new_event(
        path,
        ev="screen",
        actor="ethan",
        body={
            "stage": "title-abstract",
            "record": "rec_0000000000000001",
            "decision": "exclude",
            "criteria": ["EXC-01"],
            "criteria_version": 1,
        },
    )
    report = verify_repository(repo)
    assert not any(i.code == "E_CRITERION_STAGE" for i in report.issues)


def test_verify_skips_criterion_stage_check_when_no_criteria_cited(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    path = repo.path("events", "screen", "title-abstract.ethan.ndjson")
    append_new_event(
        path,
        ev="screen",
        actor="ethan",
        body={
            "stage": "title-abstract",
            "record": "rec_0000000000000001",
            "decision": "include",
            "criteria": [],
            "criteria_version": 1,
        },
    )
    report = verify_repository(repo)
    assert not any(i.code == "E_CRITERION_STAGE" for i in report.issues)


def test_verify_skips_criterion_stage_check_when_version_missing(tmp_path: Path) -> None:
    """An `imported: true` decision recorded before this milestone's own
    validation existed might lack `criteria_version` entirely -- the check
    must not crash on it, just skip (nothing to reconstruct against)."""
    repo = _make_repo(tmp_path)
    path = repo.path("events", "screen", "title-abstract.ethan.ndjson")
    append_new_event(
        path,
        ev="screen",
        actor="ethan",
        body={
            "stage": "title-abstract",
            "record": "rec_0000000000000001",
            "decision": "exclude",
            "criteria": ["EXC-01"],
        },
    )
    report = verify_repository(repo)
    assert not any(i.code == "E_CRITERION_STAGE" for i in report.issues)


def test_verify_ignores_non_screen_events_in_the_screen_directory(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    path = repo.path("events", "screen", "title-abstract.ethan.ndjson")
    append_new_event(path, ev="note", actor="ethan", body={"subject": "s", "text": "t"})
    report = verify_repository(repo)
    assert not any(
        i.code in ("E_EXCLUSION_NO_CRITERION", "E_CRITERION_STAGE") for i in report.issues
    )


def test_verify_reuses_reconstructed_criteria_across_events_at_the_same_version(
    tmp_path: Path,
) -> None:
    """Two screen events citing criteria at the same `criteria_version` share
    one `reconstruct_at_version` call rather than recomputing it per event."""
    repo = _make_repo(tmp_path)
    _add_active_criterion(repo, criterion_id="EXC-01", applies_at=["title-abstract"])
    path = repo.path("events", "screen", "title-abstract.ethan.ndjson")
    for record_id in ("rec_0000000000000001", "rec_0000000000000002"):
        append_new_event(
            path,
            ev="screen",
            actor="ethan",
            body={
                "stage": "title-abstract",
                "record": record_id,
                "decision": "exclude",
                "criteria": ["EXC-01"],
                "criteria_version": 1,
            },
        )
    report = verify_repository(repo)
    assert not any(i.code == "E_CRITERION_STAGE" for i in report.issues)


def test_verify_fast_mode_skips_alias_and_dangling_checks(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    aliases_path = repo.path("records", "aliases.ndjson")
    aliases_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        json.dumps({"alias": "rec_aaaaaaaaaaaaaaaa", "canonical": "rec_bbbbbbbbbbbbbbbb"}),
        json.dumps({"alias": "rec_bbbbbbbbbbbbbbbb", "canonical": "rec_aaaaaaaaaaaaaaaa"}),
    ]
    aliases_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    report = verify_repository(repo, fast=True)
    assert report.ok
