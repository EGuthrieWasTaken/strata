"""Study grouping and splitting (openspec:study-grouping)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from strata.core.ids import singleton_study_id
from strata.core.verify import verify_repository
from strata.protocol import studies
from tests.unit._m3 import add_records, decide, init_review, record, rpt


def _review(tmp_path: Path, records: list[dict[str, Any]] | int):  # type: ignore[no-untyped-def]
    repo = init_review(tmp_path)
    ids = add_records(repo, records)
    decide(repo, "full-text", ids)
    return repo


def _codes(repo) -> set[str]:  # type: ignore[no-untyped-def]
    return {i.code for i in verify_repository(repo).issues}


def test_every_included_report_is_a_study_of_one_until_grouped(tmp_path: Path) -> None:
    repo = _review(tmp_path, 3)
    assert studies.included_reports(repo) == [rpt(1), rpt(2), rpt(3)]
    current = studies.study_map(repo)
    assert len(current.members) == 3
    assert current.studies_of[rpt(2)] == (singleton_study_id(rpt(2)),)


def test_only_reports_included_at_the_last_stage_are_studied(tmp_path: Path) -> None:
    repo = init_review(tmp_path)
    ids = add_records(repo, 3)
    decide(repo, "full-text", ids[:2])
    assert studies.included_reports(repo) == [rpt(1), rpt(2)]


def test_grouping_records_one_study_with_both_reports_and_the_rationale(tmp_path: Path) -> None:
    """41 included reports -> 38 studies, in miniature: 4 reports -> 2 studies."""
    repo = _review(tmp_path, 4)
    event = studies.group_reports(
        repo, reports=[rpt(2), rpt(1)], actor="ethan", rationale="Follow-up of the same trial"
    )
    assert event["ev"] == "study-group"
    assert event["body"]["reports"] == [rpt(1), rpt(2)]
    assert event["body"]["rationale"] == "Follow-up of the same trial"
    assert event["body"]["study"].startswith("std_")
    current = studies.study_map(repo)
    assert len(current.members) == 3
    assert current.members[event["body"]["study"]] == (rpt(1), rpt(2))
    assert _codes(repo) == set()


def test_a_rationale_is_required_to_group_or_split(tmp_path: Path) -> None:
    repo = _review(tmp_path, 2)
    with pytest.raises(studies.StudyError, match="rationale"):
        studies.group_reports(repo, reports=[rpt(1), rpt(2)], actor="ethan", rationale="  ")
    with pytest.raises(studies.StudyError, match="rationale"):
        studies.split_report(repo, report=rpt(1), parts=2, actor="ethan", rationale="")
    assert studies.all_study_events(repo) == []


def test_grouping_refuses_reports_that_are_not_included_or_a_missing_study(tmp_path: Path) -> None:
    repo = _review(tmp_path, 2)
    with pytest.raises(studies.StudyError, match="not included"):
        studies.group_reports(repo, reports=[rpt(1), rpt(9)], actor="ethan", rationale="same")
    with pytest.raises(studies.StudyError, match="at least one"):
        studies.group_reports(repo, reports=[], actor="ethan", rationale="same")
    with pytest.raises(studies.StudyError, match="no study"):
        studies.group_reports(
            repo, reports=[rpt(1)], actor="ethan", rationale="same", study="std_" + "9" * 16
        )


def test_an_existing_study_can_be_redefined_keeping_its_id(tmp_path: Path) -> None:
    repo = _review(tmp_path, 3)
    first = studies.group_reports(repo, reports=[rpt(1), rpt(2)], actor="ethan", rationale="same")
    study = first["body"]["study"]
    studies.group_reports(
        repo, reports=[rpt(1), rpt(2), rpt(3)], actor="sam", rationale="third paper", study=study
    )
    current = studies.study_map(repo)
    assert current.members[study] == (rpt(1), rpt(2), rpt(3))
    assert len(current.members) == 1


def test_splitting_a_multi_experiment_report_makes_linked_studies(tmp_path: Path) -> None:
    repo = _review(tmp_path, 2)
    event = studies.split_report(
        repo, report=rpt(1), parts=3, actor="ethan", rationale="Three independent experiments"
    )
    assert event["ev"] == "study-split"
    assert len(set(event["body"]["studies"])) == 3
    current = studies.study_map(repo)
    assert set(current.studies_of[rpt(1)]) == set(event["body"]["studies"])
    assert len(current.members) == 4  # three experiments + the other report
    assert _codes(repo) == set()


def test_splitting_needs_two_parts_and_an_included_report(tmp_path: Path) -> None:
    repo = _review(tmp_path, 1)
    with pytest.raises(studies.StudyError, match="at least 2"):
        studies.split_report(repo, report=rpt(1), parts=1, actor="ethan", rationale="x")
    with pytest.raises(studies.StudyError, match="not an included"):
        studies.split_report(repo, report=rpt(5), parts=2, actor="ethan", rationale="x")


# --- suggestions ---------------------------------------------------------------------------


def _pair(**second: Any) -> list[dict[str, Any]]:
    first = record(
        1,
        author=[{"family": "Larsen"}, {"family": "Butler"}],
        title="Test-enhanced learning in medical education",
        abstract="We enrolled n = 120 residents in a randomised trial.",
    )
    other = record(
        2,
        author=[{"family": "Larsen"}, {"family": "Butler"}, {"family": "Roediger"}],
        title="Repeated testing: long-term outcomes",
    )
    other.update(second)
    return [first, other]


def test_a_shared_registration_number_is_suggested_with_its_evidence(tmp_path: Path) -> None:
    repo = _review(
        tmp_path,
        [
            record(1, abstract="Registered as NCT00713310."),
            record(2, author=[{"family": "Someone Else"}], note="Trial registration NCT00713310"),
            record(3, abstract="An unrelated study."),
        ],
    )
    found = studies.suggestions(repo)
    assert [g.reports for g in found.groupings] == [(rpt(1), rpt(2))]
    assert "NCT00713310" in found.groupings[0].evidence[0]


def test_suggesting_changes_nothing(tmp_path: Path) -> None:
    repo = _review(tmp_path, [record(1, abstract="NCT00713310"), record(2, abstract="NCT00713310")])
    assert studies.suggestions(repo).groupings
    assert studies.all_study_events(repo) == []
    assert len(studies.study_map(repo).members) == 2


def test_a_shared_author_set_alone_is_not_enough(tmp_path: Path) -> None:
    repo = _review(tmp_path, _pair())
    assert studies.suggestions(repo).groupings == []


def test_author_set_plus_overlapping_sample_is_suggested(tmp_path: Path) -> None:
    repo = _review(tmp_path, _pair(abstract="The same 120 participants were retested."))
    [group] = studies.suggestions(repo).groupings
    assert any("shared author set" in e for e in group.evidence)
    assert any("n = 120" in e for e in group.evidence)


def test_author_set_plus_follow_up_language_is_suggested(tmp_path: Path) -> None:
    repo = _review(tmp_path, _pair(title="A long-term follow-up study of test-enhanced learning"))
    [group] = studies.suggestions(repo).groupings
    assert any("follow-up language" in e for e in group.evidence)


def test_mutual_citation_counts_as_a_signal(tmp_path: Path) -> None:
    records = _pair()
    records[0]["DOI"] = "10.1000/first"
    records[1]["DOI"] = "10.1000/second"
    records[1]["references"] = ["10.1000/FIRST"]
    repo = _review(tmp_path, records)
    [group] = studies.suggestions(repo).groupings
    assert "the reports cite each other" in group.evidence


def test_unrelated_reports_are_not_suggested(tmp_path: Path) -> None:
    repo = _review(tmp_path, 4)
    found = studies.suggestions(repo)
    assert found.groupings == [] and found.splits == []


def test_three_reports_of_one_trial_are_one_suggestion(tmp_path: Path) -> None:
    repo = _review(tmp_path, [record(i, abstract="NCT01234567") for i in (1, 2, 3)])
    [group] = studies.suggestions(repo).groupings
    assert group.reports == (rpt(1), rpt(2), rpt(3))


def test_an_already_grouped_pair_is_not_suggested_again(tmp_path: Path) -> None:
    repo = _review(tmp_path, [record(1, abstract="NCT00713310"), record(2, abstract="NCT00713310")])
    studies.group_reports(repo, reports=[rpt(1), rpt(2)], actor="ethan", rationale="same trial")
    assert studies.suggestions(repo).groupings == []


def test_keep_separate_is_remembered(tmp_path: Path) -> None:
    repo = _review(tmp_path, [record(1, abstract="NCT00713310"), record(2, abstract="NCT00713310")])
    studies.dismiss_suggestion(repo, reports=[rpt(2), rpt(1)], actor="ethan", kind="keep-separate")
    assert studies.suggestions(repo).groupings == []


def test_multi_experiment_reports_are_suggested_for_splitting(tmp_path: Path) -> None:
    repo = _review(
        tmp_path,
        [
            record(1, abstract="Across three independent experiments we show spacing helps."),
            record(2, abstract="We tested 2 groups of learners."),
            record(3, title="Two studies of retrieval practice"),
        ],
    )
    found = studies.suggestions(repo)
    assert [(s.report, s.parts) for s in found.splits] == [(rpt(1), 3), (rpt(3), 2)]
    assert found.splits[0].evidence == "three independent experiments"


def test_split_suggestion_disappears_once_split_or_kept_as_one(tmp_path: Path) -> None:
    repo = _review(
        tmp_path,
        [record(1, abstract="Three experiments."), record(2, abstract="Four experiments.")],
    )
    studies.split_report(repo, report=rpt(1), parts=3, actor="ethan", rationale="3 experiments")
    studies.dismiss_suggestion(repo, reports=[rpt(2)], actor="ethan", kind="keep-as-one")
    assert studies.suggestions(repo).splits == []
