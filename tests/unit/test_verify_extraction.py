"""`strata verify` on extraction data (openspec:repository-verification, data-extraction)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from strata.core.canon import dump_yaml_str
from strata.core.events import append_new_event
from strata.core.verify import verify_repository
from strata.extract import records as rec_mod
from strata.protocol.criteria import add_criterion
from strata.protocol.screening import record_screen_decision
from tests.unit._m3 import rpt
from tests.unit.test_extract_records import MEANS, _review, study

S = study(1)


def _issues(repo) -> dict[str, list[Any]]:  # type: ignore[no-untyped-def]
    found: dict[str, list[Any]] = {}
    for issue in verify_repository(repo).issues:
        found.setdefault(issue.code, []).append(issue)
    return found


def _complete(repo, n: int = 1) -> None:  # type: ignore[no-untyped-def]
    for name, raw in (("n_total", "100"), ("design", "rct"), ("retention_interval", "1 week")):
        rec_mod.set_field(repo, study=study(n), handle="ethan", name=name, raw=raw)


def test_no_extraction_checks_before_extraction_has_started(tmp_path: Path) -> None:
    repo = _review(tmp_path)
    repo.path("extraction", "schema.yaml").unlink()
    assert _issues(repo) == {}


def test_an_included_study_without_a_consensus_is_a_warning_not_a_failure(tmp_path: Path) -> None:
    repo = _review(tmp_path, studies=2)
    _complete(repo, 1)
    found = _issues(repo)
    [missing] = found["E_MISSING_EXTRACTION"]
    assert study(2) in missing.message and missing.severity == "warning"
    assert set(found) == {"E_MISSING_EXTRACTION"}
    assert verify_repository(repo).ok  # a warning does not fail verification


def test_a_complete_extraction_verifies_clean(tmp_path: Path) -> None:
    repo = _review(tmp_path, studies=1)
    _complete(repo)
    rec_mod.add_effect(
        repo, study=S, handle="ethan", outcome="recall", design="two-group-means", inputs=MEANS
    )
    assert verify_repository(repo).issues == []


def test_an_extraction_for_a_study_excluded_afterwards_is_an_orphan_and_is_kept(
    tmp_path: Path,
) -> None:
    """openspec scenario: excluded after its extraction was reconciled -> E_ORPHAN_EXTRACTION."""
    repo = _review(tmp_path, studies=2)
    _complete(repo, 1)
    add_criterion(
        repo,
        kind="exclusion",
        label="Wrong population",
        definition="Not adults.",
        applies_at=["full-text"],
        actor="ethan",
        rationale="Adding a full-text exclusion criterion.",
    )
    for actor in ("ethan", "sam"):
        record_screen_decision(
            repo,
            stage="full-text",
            record_id=f"rec_{rpt(1)[4:]}",
            decision="exclude",
            actor=actor,
            cited=["EXC-01"],
        )
    found = _issues(repo)
    [orphan] = found["E_ORPHAN_EXTRACTION"]
    assert S in orphan.message and orphan.severity == "error"
    assert rec_mod.consensus_path(repo, S).exists()  # retained, never deleted
    assert not verify_repository(repo).ok


def test_a_reviewer_draft_for_an_unknown_study_is_also_an_orphan(tmp_path: Path) -> None:
    repo = _review(tmp_path, mode="dual", studies=1)
    stray = rec_mod.reviewer_path(repo, "ethan", "std_" + "9" * 16)
    stray.parent.mkdir(parents=True, exist_ok=True)
    stray.write_text(
        dump_yaml_str(
            {
                "study": "std_" + "9" * 16,
                "reports": [rpt(9)],
                "schema_version": 1,
                "extracted_by": ["ethan"],
                "fields": {},
            }
        ),
        encoding="utf-8",
    )
    assert "E_ORPHAN_EXTRACTION" in _issues(repo)


def test_a_unit_outside_accepts_units_is_e_unit(tmp_path: Path) -> None:
    """openspec scenario: a value in fortnights for a field that does not accept it."""
    repo = _review(tmp_path, studies=1)
    _complete(repo)
    path = rec_mod.consensus_path(repo, S)
    record = rec_mod.read_record(path)
    assert record is not None
    record["fields"]["retention_interval"] = {
        "value": 2,
        "unit": "hours",
        "entered": "2 fortnights",
    }
    path.write_text(dump_yaml_str(record), encoding="utf-8")
    assert "E_UNIT" in _issues(repo)


def test_an_effect_lacking_its_designs_inputs_is_e_effect_inputs(tmp_path: Path) -> None:
    """openspec scenario: a two-group-means effect lacking sd2."""
    repo = _review(tmp_path, studies=1)
    _complete(repo)
    path = rec_mod.consensus_path(repo, S)
    record = rec_mod.read_record(path)
    assert record is not None
    record["effects"] = [
        {
            "outcome": "recall",
            "design": "two-group-means",
            **{k: v for k, v in MEANS.items() if k != "sd2"},
        }
    ]
    path.write_text(dump_yaml_str(record), encoding="utf-8")
    [issue] = _issues(repo)["E_EFFECT_INPUTS"]
    assert "sd2" in issue.message and issue.path == f"extraction/consensus/{S}.yaml"


def test_unreadable_extraction_files_and_forms_are_reported_not_crashed_on(tmp_path: Path) -> None:
    repo = _review(tmp_path, studies=1)
    bad = rec_mod.consensus_path(repo, S)
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_text("study: [unclosed\n", encoding="utf-8")
    other = rec_mod.consensus_path(repo, "std_" + "8" * 16)
    other.write_text("- just\n- a list\n", encoding="utf-8")
    codes = {i.code for i in verify_repository(repo).issues}
    assert "E_SCHEMA" in codes
    repo.path("extraction", "schema.yaml").write_text("version: 0\nfields: []\n", encoding="utf-8")
    assert any(
        i.path == "extraction/schema.yaml"
        for i in verify_repository(repo).issues
        if i.code == "E_SCHEMA"
    )


def test_events_naming_an_unknown_study_are_dangling(tmp_path: Path) -> None:
    repo = _review(tmp_path, studies=1)
    ghost = "std_" + "7" * 16
    append_new_event(
        repo.path("events", "extract", "ethan.ndjson"),
        ev="extract",
        actor="ethan",
        body={"study": ghost, "fields_changed": ["n_total"], "digest": "sha256:" + "0" * 64},
    )
    [issue] = _issues(repo)["E_DANGLING_REF"]
    assert ghost in issue.message


def test_a_study_created_by_grouping_is_a_known_study(tmp_path: Path) -> None:
    from strata.protocol import studies

    repo = _review(tmp_path, studies=2)
    grouped = studies.group_reports(
        repo, reports=[rpt(1), rpt(2)], actor="ethan", rationale="Same trial, two papers"
    )["body"]["study"]
    rec_mod.set_field(repo, study=grouped, handle="ethan", name="n_total", raw="9")
    assert "E_DANGLING_REF" not in _issues(repo)
