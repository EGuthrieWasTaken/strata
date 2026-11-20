"""Reading Rayyan, Covidence and EPPI-Reviewer exports
(openspec:literature-import#migration-imports-from-incumbent-tools). The fixtures are hand-written
to each tool's documented export format (`tests/fixtures/migration/README.md`)."""

from __future__ import annotations

from pathlib import Path

import pytest

from strata.ingest.parsers import migration

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "migration"


def _text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_a_rayyan_export_gives_its_records_and_each_reviewers_decision() -> None:
    parsed = migration.parse_rayyan(_text("rayyan-articles.csv"))

    titles = [r["title"] for r in parsed.records.records]
    assert titles[0].startswith("Spacing effects") and len(titles) == 3
    assert [r.line for r in parsed.records.rejected] == [5]  # the row with no title
    cepeda = parsed.records.records[0]
    assert cepeda["author"][0] == {"family": "Cepeda", "given": "Nicholas J."}
    assert cepeda["issued"] == {"date-parts": [[2008, 11]]}
    assert cepeda["DOI"] == "10.1111/j.1467-9280.2008.02209.x"
    assert parsed.records.records[1]["issued"] == {"date-parts": [[2006, 3]]}  # "Mar"
    roediger = {d.reviewer: d for d in parsed.decisions[1]}
    assert roediger["Ada"].decision == "exclude" and roediger["Ada"].reasons == (
        "wrong population",
    )
    assert roediger["Sam"].decision == "maybe" and roediger["Sam"].reasons == ()


def test_a_covidence_list_gives_its_records_and_reasons() -> None:
    parsed = migration.parse_covidence(_text("covidence-excluded.csv"))

    assert len(parsed.records.records) == 2
    assert parsed.records.records[0]["author"][1] == {"family": "Vul", "given": "Edward"}
    assert parsed.decisions[1][0].reasons == ("Wrong study design",)


@pytest.mark.parametrize(
    ("listed", "stage", "decision"),
    [
        ("irrelevant", "title-abstract", "exclude"),
        ("irrelevant", "full-text", None),
        ("excluded", "title-abstract", "include"),
        ("excluded", "full-text", "exclude"),
        ("included", "full-text", "include"),
    ],
)
def test_a_covidence_list_is_a_decision_at_each_stage(
    listed: str, stage: str, decision: str | None
) -> None:
    assert migration.covidence_decision(listed, stage) == decision


def test_an_eppi_export_reads_its_codes_as_decisions() -> None:
    parsed = migration.parse_eppi_json(_text("eppi-reviewer.json"))

    assert [d[0].decision if d else None for d in parsed.decisions] == ["include", "exclude", None]
    assert parsed.decisions[1][0].reasons == ("Exclude: not empirical",)
    assert parsed.records.records[1]["author"][0] == {"family": "Roediger", "given": "H L"}


def test_a_file_from_another_tool_is_refused_with_the_reason() -> None:
    with pytest.raises(migration.MigrationFormatError, match="not a Rayyan CSV export"):
        migration.parse_rayyan(_text("covidence-excluded.csv"))
    with pytest.raises(migration.MigrationFormatError, match="not a Covidence CSV export"):
        migration.parse_covidence(_text("rayyan-articles.csv"))
    with pytest.raises(migration.MigrationFormatError, match="not an EPPI-Reviewer JSON export"):
        migration.parse_eppi_json("[]")


def test_an_eppi_reference_coded_both_ways_is_left_as_maybe() -> None:
    text = (
        '{"References": [{"Title": "T", "Codes": [{"AttributeName": "Include"},'
        ' {"AttributeName": "Exclude: wrong"}]}]}'
    )
    assert migration.parse_eppi_json(text).decisions == [[migration.ToolDecision("maybe")]]


@pytest.mark.parametrize(
    "document",
    [
        '{"CodeSets": 5, "References": [{"Title": "T", "Codes": {"a": 1}}]}',
        '{"CodeSets": [{"Attributes": {"AttributesList": [{"AttributeId": [1]}]}}],'
        ' "References": [{"Title": 7, "Codes": [{"AttributeId": {"x": 1}}], "Authors": 3}]}',
        '{"References": [5, null, {"Title": ""}]}',
    ],
)
def test_an_eppi_export_of_an_odd_shape_is_read_or_rejected_row_by_row(document: str) -> None:
    parsed = migration.parse_eppi_json(document)
    assert len(parsed.decisions) == len(parsed.records.records)
