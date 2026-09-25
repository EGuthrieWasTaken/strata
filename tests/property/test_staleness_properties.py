"""Property test for docs/spec/06-workflow-screening.md §4.2's staleness rules.

P10: staleness soundness. For a random criteria change and decision set,
`strata.protocol.staleness.evaluate_staleness`'s verdict MUST agree with an
independently-written brute-force reference implementation of the same
rules. The reference lives here, not in shipped code, and is written in a
deliberately different shape (explicit loops, no shared helpers, no early
generalisation) so a bug shared between the two is unlikely to slip through
unnoticed.
"""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from strata.protocol.staleness import CriterionChange, Decision, evaluate_staleness

_CRITERION_IDS = ["EXC-01", "EXC-02", "EXC-03", "EXC-04"]
_STAGES = ["title-abstract", "full-text"]
_ORIGINS = ["added", "edited", "retired"]
_DIRECTIONS = ["tightened", "loosened", "both", "editorial"]


def _brute_force_stale(
    *,
    decision: str,
    cited: frozenset[str],
    decision_version: int,
    current_version: int,
    stage: str,
    changes: list[CriterionChange],
) -> bool:
    """Deliberately naive: no shared helper with `relevant_changes`/`effective_direction`."""
    applicable = []
    for change in changes:
        if change.to_version <= decision_version:
            continue
        if change.to_version > current_version:
            continue
        stage_matches = False
        for applies in change.applies_at:
            if applies == stage:
                stage_matches = True
        if not stage_matches:
            continue
        applicable.append(change)

    def effective(change: CriterionChange) -> str:
        if change.origin == "added":
            return "tightened"
        elif change.origin == "retired":
            return "loosened"
        else:
            return change.direction

    if decision == "include":
        for change in applicable:
            direction = effective(change)
            if direction == "tightened" or direction == "both":
                return True
        return False

    if decision == "exclude":
        for change in applicable:
            is_cited = False
            for c in cited:
                if c == change.criterion_id:
                    is_cited = True
            if not is_cited:
                continue
            direction = effective(change)
            if direction == "loosened" or direction == "both":
                return True
        return False

    if decision == "maybe":
        return any(effective(change) != "editorial" for change in applicable)

    raise AssertionError(f"unhandled decision {decision!r}")


_changes_strategy = st.lists(
    st.builds(
        CriterionChange,
        criterion_id=st.sampled_from(_CRITERION_IDS),
        origin=st.sampled_from(_ORIGINS),
        direction=st.sampled_from(_DIRECTIONS),
        to_version=st.integers(min_value=1, max_value=8),
        applies_at=st.sets(st.sampled_from(_STAGES), min_size=1, max_size=2).map(frozenset),
    ),
    max_size=6,
)


@pytest.mark.req("P10")
@given(
    decision=st.sampled_from(["include", "exclude", "maybe"]),
    cited=st.sets(st.sampled_from(_CRITERION_IDS), max_size=3).map(frozenset),
    decision_version=st.integers(min_value=0, max_value=8),
    current_version=st.integers(min_value=0, max_value=8),
    stage=st.sampled_from(_STAGES),
    changes=_changes_strategy,
)
def test_p10_staleness_matches_brute_force_reference(
    decision: Decision,
    cited: frozenset[str],
    decision_version: int,
    current_version: int,
    stage: str,
    changes: list[CriterionChange],
) -> None:
    result = evaluate_staleness(
        decision=decision,
        cited=cited,
        decision_version=decision_version,
        current_version=current_version,
        stage=stage,
        changes=changes,
    )
    expected = _brute_force_stale(
        decision=decision,
        cited=cited,
        decision_version=decision_version,
        current_version=current_version,
        stage=stage,
        changes=changes,
    )
    assert result.stale == expected


@pytest.mark.req("P10")
@given(
    decision=st.sampled_from(["include", "exclude", "maybe"]),
    cited=st.sets(st.sampled_from(_CRITERION_IDS), max_size=3).map(frozenset),
    decision_version=st.integers(min_value=0, max_value=8),
    current_version=st.integers(min_value=0, max_value=8),
    stage=st.sampled_from(_STAGES),
    changes=_changes_strategy,
)
def test_p10_stale_implies_a_nonempty_cause_set(
    decision: Decision,
    cited: frozenset[str],
    decision_version: int,
    current_version: int,
    stage: str,
    changes: list[CriterionChange],
) -> None:
    """Whenever a decision is flagged stale, at least one specific criterion
    is named as the cause -- staleness is never reported without a reason."""
    result = evaluate_staleness(
        decision=decision,
        cited=cited,
        decision_version=decision_version,
        current_version=current_version,
        stage=stage,
        changes=changes,
    )
    if result.stale:
        assert result.reason is not None
        assert result.causes
        assert result.causes.issubset({c.criterion_id for c in changes})
    else:
        assert result.reason is None
        assert result.causes == frozenset()
