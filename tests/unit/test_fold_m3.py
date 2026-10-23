"""The retrieval and study folds (openspec:full-text-retrieval, openspec:study-grouping)."""

from __future__ import annotations

import random
from typing import Any

from strata.core.fold import (
    NOT_RETRIEVED,
    RETRIEVAL_ILL_REQUESTED,
    RETRIEVAL_RETRIEVED,
    fold_retrieval,
    fold_studies,
)
from strata.core.ids import singleton_study_id

A, B, C = "rpt_" + "a" * 16, "rpt_" + "b" * 16, "rpt_" + "c" * 16
S1, S2, S3 = "std_" + "1" * 16, "std_" + "2" * 16, "std_" + "3" * 16
UNKNOWN = "rpt_" + "f" * 16


def _event(n: int, ev: str, body: dict[str, Any], actor: str = "ethan") -> dict[str, Any]:
    return {
        "ev": ev,
        "id": f"ev_{n:04d}",
        "ts": f"2026-01-01T00:00:{n:02d}Z",
        "actor": actor,
        "seq": n,
        "body": body,
        "tool": "test",
        "digest": f"sha256:{n}",
    }


def _group(n: int, study: str, reports: list[str]) -> dict[str, Any]:
    return _event(n, "study-group", {"study": study, "reports": reports, "rationale": "same trial"})


def _split(n: int, report: str, studies: list[str]) -> dict[str, Any]:
    return _event(n, "study-split", {"report": report, "studies": studies, "rationale": "x"})


def _fold(events: list[dict[str, Any]], reports: list[str] = [A, B, C]):  # noqa: B006
    return fold_studies(reports, events, singleton_study_id)


# --- retrieval -----------------------------------------------------------------------------


def _retrieval(n: int, report: str, status: str, actor: str = "ethan") -> dict[str, Any]:
    return _event(n, "retrieval", {"report": report, "status": status}, actor)


def test_a_report_with_no_events_is_absent_from_the_retrieval_fold() -> None:
    assert fold_retrieval([]) == {}


def test_latest_retrieval_event_wins_across_actors() -> None:
    events = [
        _retrieval(1, A, RETRIEVAL_ILL_REQUESTED, "ethan"),
        _retrieval(2, A, RETRIEVAL_RETRIEVED, "sam"),
        _retrieval(3, B, NOT_RETRIEVED, "sam"),
    ]
    states = fold_retrieval(events)
    assert states[A].status == RETRIEVAL_RETRIEVED
    assert states[A].event["actor"] == "sam"
    assert states[B].status == NOT_RETRIEVED


def test_reopening_a_report_is_an_appended_correction() -> None:
    events = [_retrieval(1, A, NOT_RETRIEVED), _retrieval(2, A, "sought")]
    assert fold_retrieval(events)[A].status == "sought"


def test_retrieval_fold_is_order_independent_and_idempotent() -> None:
    events = [_retrieval(i, A if i % 2 else B, RETRIEVAL_RETRIEVED) for i in range(1, 9)]
    shuffled = events[:] + events[:3]
    random.Random(7).shuffle(shuffled)
    assert fold_retrieval(shuffled) == fold_retrieval(events)


# --- studies -------------------------------------------------------------------------------


def test_every_report_starts_as_a_study_of_one() -> None:
    result = _fold([])
    assert result.studies_of[A] == (singleton_study_id(A),)
    assert set(result.members) == {singleton_study_id(r) for r in (A, B, C)}
    assert result.defined_by == {}


def test_grouping_merges_reports_into_one_study() -> None:
    result = _fold([_group(1, S1, [A, B])])
    assert result.members[S1] == (A, B)
    assert result.studies_of[A] == (S1,)
    assert singleton_study_id(A) not in result.members
    assert singleton_study_id(C) in result.members  # untouched
    assert result.defined_by[S1]["ev"] == "study-group"


def test_grouping_ignores_reports_that_are_not_included() -> None:
    result = _fold([_group(1, S1, [A, UNKNOWN])])
    assert result.members[S1] == (A,)
    assert UNKNOWN not in result.studies_of


def test_regrouping_without_a_report_returns_it_to_its_own_study() -> None:
    result = _fold([_group(1, S1, [A, B]), _group(2, S1, [A])])
    assert result.members[S1] == (A,)
    assert result.studies_of[B] == (singleton_study_id(B),)


def test_a_report_moves_to_the_study_it_was_most_recently_grouped_into() -> None:
    result = _fold([_group(1, S1, [A, B]), _group(2, S2, [B, C])])
    assert result.members[S1] == (A,)
    assert result.members[S2] == (B, C)


def test_splitting_puts_one_report_in_several_studies() -> None:
    result = _fold([_split(1, A, [S1, S2, S3])])
    assert result.studies_of[A] == (S1, S2, S3)
    assert result.members[S2] == (A,)
    assert singleton_study_id(A) not in result.members
    assert result.defined_by[S3]["ev"] == "study-split"


def test_splitting_an_unknown_report_is_ignored() -> None:
    result = _fold([_split(1, UNKNOWN, [S1, S2])])
    assert S1 not in result.members


def test_another_report_can_join_one_study_of_a_split_without_leaving_its_siblings() -> None:
    result = _fold([_split(1, A, [S1, S2]), _group(2, S1, [A, B])])
    assert result.studies_of[A] == (S1, S2)
    assert result.members[S1] == (A, B)


def test_grouping_a_split_report_into_an_unrelated_study_ends_the_split() -> None:
    result = _fold([_split(1, A, [S1, S2]), _group(2, S3, [A])])
    assert result.studies_of[A] == (S3,)
    assert S1 not in result.members


def test_dropping_a_report_from_a_split_sibling_study_keeps_its_other_studies() -> None:
    result = _fold([_split(1, A, [S1, S2]), _group(2, S1, [B])])
    assert result.studies_of[A] == (S2,)
    assert result.members[S1] == (B,)


def test_dropping_a_reports_only_study_returns_it_to_a_singleton() -> None:
    result = _fold([_group(1, S1, [A]), _group(2, S1, [B])])
    assert result.studies_of[A] == (singleton_study_id(A),)


def test_a_study_with_no_members_left_is_not_reported_as_defined() -> None:
    result = _fold([_group(1, S1, [A]), _group(2, S2, [A])])
    assert S1 not in result.members
    assert S1 not in result.defined_by


def test_study_fold_is_order_independent_and_idempotent() -> None:
    events = [_group(1, S1, [A, B]), _split(2, C, [S2, S3]), _group(3, S2, [C, A])]
    baseline = _fold(events)
    shuffled = events + events[:2]
    random.Random(3).shuffle(shuffled)
    assert _fold(shuffled) == baseline
