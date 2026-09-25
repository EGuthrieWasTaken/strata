"""Unit tests for docs/spec/06-workflow-screening.md §4-§5's staleness rules.

Exercises every row of §5's reason table by name, plus the §4.3 residual-risk
scenario (a carelessly miscited exclusion). The property test in
tests/property/test_staleness_properties.py (P10) covers the general
combinatorics against an independent brute-force reference; this file pins
the specific, named scenarios the spec calls out.
"""

from __future__ import annotations

from strata.protocol.staleness import CriterionChange, evaluate_staleness


def _change(
    criterion_id: str,
    *,
    origin: str,
    direction: str,
    to_version: int,
    applies_at: frozenset[str] = frozenset({"title-abstract"}),
) -> CriterionChange:
    return CriterionChange(
        criterion_id=criterion_id,
        origin=origin,  # type: ignore[arg-type]
        direction=direction,  # type: ignore[arg-type]
        to_version=to_version,
        applies_at=applies_at,
    )


def test_include_with_no_relevant_change_is_not_stale() -> None:
    result = evaluate_staleness(
        decision="include",
        cited=frozenset(),
        decision_version=3,
        current_version=3,
        stage="title-abstract",
        changes=[],
    )
    assert result.stale is False
    assert result.reason is None
    assert result.causes == frozenset()


def test_criterion_added_stales_an_include() -> None:
    """§5 `criterion-added`: a new criterion applies at this stage and the
    record was included."""
    change = _change("EXC-07", origin="added", direction="tightened", to_version=4)
    result = evaluate_staleness(
        decision="include",
        cited=frozenset(),
        decision_version=3,
        current_version=4,
        stage="title-abstract",
        changes=[change],
    )
    assert result.stale is True
    assert result.reason == "criterion-added"
    assert result.causes == frozenset({"EXC-07"})


def test_criterion_tightened_stales_an_include() -> None:
    """§5 `criterion-tightened`: a cited-or-not criterion was tightened and
    the record was included."""
    change = _change("EXC-03", origin="edited", direction="tightened", to_version=4)
    result = evaluate_staleness(
        decision="include",
        cited=frozenset(),  # an inclusion cites no exclusion criteria at all
        decision_version=3,
        current_version=4,
        stage="title-abstract",
        changes=[change],
    )
    assert result.stale is True
    assert result.reason == "criterion-tightened"


def test_loosening_does_not_stale_an_include() -> None:
    """§4.3: inclusions are robust to loosening."""
    change = _change("EXC-03", origin="edited", direction="loosened", to_version=4)
    result = evaluate_staleness(
        decision="include",
        cited=frozenset(),
        decision_version=3,
        current_version=4,
        stage="title-abstract",
        changes=[change],
    )
    assert result.stale is False


def test_criterion_loosened_stales_the_exclusion_that_cited_it() -> None:
    """§5: `criterion-loosened` -- a criterion this exclusion cited was loosened."""
    change = _change("EXC-03", origin="edited", direction="loosened", to_version=4)
    result = evaluate_staleness(
        decision="exclude",
        cited=frozenset({"EXC-03"}),
        decision_version=3,
        current_version=4,
        stage="title-abstract",
        changes=[change],
    )
    assert result.stale is True
    assert result.reason == "criterion-loosened"
    assert result.causes == frozenset({"EXC-03"})


def test_criterion_retired_stales_the_exclusion_that_cited_it() -> None:
    """§5: `criterion-retired` -- a criterion this exclusion cited was retired."""
    change = _change("EXC-02", origin="retired", direction="loosened", to_version=4)
    result = evaluate_staleness(
        decision="exclude",
        cited=frozenset({"EXC-02"}),
        decision_version=3,
        current_version=4,
        stage="title-abstract",
        changes=[change],
    )
    assert result.stale is True
    assert result.reason == "criterion-retired"


def test_tightening_does_not_stale_an_exclusion() -> None:
    """§4.3: exclusions are robust to tightening -- adding grounds cannot rescue a paper."""
    added = _change("EXC-07", origin="added", direction="tightened", to_version=4)
    tightened = _change("EXC-02", origin="edited", direction="tightened", to_version=4)
    result = evaluate_staleness(
        decision="exclude",
        cited=frozenset({"EXC-02"}),
        decision_version=3,
        current_version=4,
        stage="title-abstract",
        changes=[added, tightened],
    )
    assert result.stale is False


def test_exclusion_unaffected_by_a_change_to_an_uncited_criterion() -> None:
    """An exclusion citing EXC-02 is unaffected by a change to EXC-03 (§4.3)."""
    change = _change("EXC-03", origin="edited", direction="loosened", to_version=4)
    result = evaluate_staleness(
        decision="exclude",
        cited=frozenset({"EXC-02"}),
        decision_version=3,
        current_version=4,
        stage="title-abstract",
        changes=[change],
    )
    assert result.stale is False


def test_criterion_both_stales_include_and_cited_exclude() -> None:
    """§5: `criterion-both` -- a bidirectional change stales both directions."""
    change = _change("EXC-03", origin="edited", direction="both", to_version=4)
    include_result = evaluate_staleness(
        decision="include",
        cited=frozenset(),
        decision_version=3,
        current_version=4,
        stage="title-abstract",
        changes=[change],
    )
    exclude_result = evaluate_staleness(
        decision="exclude",
        cited=frozenset({"EXC-03"}),
        decision_version=3,
        current_version=4,
        stage="title-abstract",
        changes=[change],
    )
    assert include_result.stale is True
    assert include_result.reason == "criterion-both"
    assert exclude_result.stale is True
    assert exclude_result.reason == "criterion-both"


def test_both_takes_priority_over_added_when_causes_overlap() -> None:
    both = _change("EXC-01", origin="edited", direction="both", to_version=4)
    added = _change("EXC-07", origin="added", direction="tightened", to_version=4)
    result = evaluate_staleness(
        decision="include",
        cited=frozenset(),
        decision_version=3,
        current_version=4,
        stage="title-abstract",
        changes=[both, added],
    )
    assert result.reason == "criterion-both"
    assert result.causes == frozenset({"EXC-01", "EXC-07"})


def test_maybe_stales_on_any_non_editorial_change() -> None:
    """§5: `maybe-any-change` -- the decision was `maybe` and anything (non-editorial) changed."""
    change = _change("EXC-05", origin="edited", direction="tightened", to_version=4)
    result = evaluate_staleness(
        decision="maybe",
        cited=frozenset(),
        decision_version=3,
        current_version=4,
        stage="title-abstract",
        changes=[change],
    )
    assert result.stale is True
    assert result.reason == "maybe-any-change"


def test_maybe_is_not_stale_from_editorial_change_alone() -> None:
    change = _change("EXC-05", origin="edited", direction="editorial", to_version=4)
    result = evaluate_staleness(
        decision="maybe",
        cited=frozenset(),
        decision_version=3,
        current_version=4,
        stage="title-abstract",
        changes=[change],
    )
    assert result.stale is False


def test_maybe_stales_even_for_an_uncited_criterion() -> None:
    """§4.2: for `maybe`, Δ != ∅ is sufficient -- no citation restriction, unlike `exclude`."""
    change = _change("EXC-05", origin="edited", direction="tightened", to_version=4)
    result = evaluate_staleness(
        decision="maybe",
        cited=frozenset({"EXC-09"}),
        decision_version=3,
        current_version=4,
        stage="title-abstract",
        changes=[change],
    )
    assert result.stale is True


def test_editorial_change_alone_stales_nothing() -> None:
    change = _change("EXC-03", origin="edited", direction="editorial", to_version=4)
    for decision, cited in (("include", frozenset()), ("exclude", frozenset({"EXC-03"}))):
        result = evaluate_staleness(
            decision=decision,  # type: ignore[arg-type]
            cited=cited,
            decision_version=3,
            current_version=4,
            stage="title-abstract",
            changes=[change],
        )
        assert result.stale is False


def test_change_before_decision_version_is_irrelevant() -> None:
    """A change the decision was already made *under* (to_version <= decision_version)
    is not part of Δ."""
    change = _change("EXC-03", origin="added", direction="tightened", to_version=3)
    result = evaluate_staleness(
        decision="include",
        cited=frozenset(),
        decision_version=3,
        current_version=5,
        stage="title-abstract",
        changes=[change],
    )
    assert result.stale is False


def test_change_at_a_different_stage_is_irrelevant() -> None:
    change = _change(
        "EXC-07",
        origin="added",
        direction="tightened",
        to_version=4,
        applies_at=frozenset({"full-text"}),
    )
    result = evaluate_staleness(
        decision="include",
        cited=frozenset(),
        decision_version=3,
        current_version=4,
        stage="title-abstract",
        changes=[change],
    )
    assert result.stale is False


def test_miscited_criterion_residual_risk_from_spec_4_3() -> None:
    """§4.3's worked residual-risk scenario: a reviewer excludes a rodent study
    but cites EXC-05 (wrong outcome) instead of EXC-02 (animal model).

    Retiring EXC-05 correctly flags the record stale (no harm, since it
    should be re-examined regardless). Retiring EXC-02 does *not* flag it,
    because the exclusion never cited EXC-02 -- exactly the residual risk
    the spec says the tool cannot fully protect against.
    """
    retire_cited_criterion = _change("EXC-05", origin="retired", direction="loosened", to_version=4)
    result_cited = evaluate_staleness(
        decision="exclude",
        cited=frozenset({"EXC-05"}),
        decision_version=3,
        current_version=4,
        stage="title-abstract",
        changes=[retire_cited_criterion],
    )
    assert result_cited.stale is True
    assert result_cited.reason == "criterion-retired"

    retire_uncited_criterion = _change(
        "EXC-02", origin="retired", direction="loosened", to_version=4
    )
    result_uncited = evaluate_staleness(
        decision="exclude",
        cited=frozenset({"EXC-05"}),  # the actual (miscited) citation on file
        decision_version=3,
        current_version=4,
        stage="title-abstract",
        changes=[retire_uncited_criterion],
    )
    assert result_uncited.stale is False


def test_relevant_changes_boundaries() -> None:
    from strata.protocol.staleness import relevant_changes

    at_decision_version = _change("EXC-01", origin="added", direction="tightened", to_version=3)
    within_range = _change("EXC-02", origin="added", direction="tightened", to_version=4)
    beyond_current = _change("EXC-03", origin="added", direction="tightened", to_version=6)
    wrong_stage = _change(
        "EXC-04",
        origin="added",
        direction="tightened",
        to_version=4,
        applies_at=frozenset({"full-text"}),
    )
    result = relevant_changes(
        [at_decision_version, within_range, beyond_current, wrong_stage],
        decision_version=3,
        current_version=5,
        stage="title-abstract",
    )
    assert result == [within_range]


def test_criterion_change_effective_direction() -> None:
    added = _change("EXC-01", origin="added", direction="tightened", to_version=1)
    edited_both = _change("EXC-01", origin="edited", direction="both", to_version=2)
    retired = _change("EXC-01", origin="retired", direction="loosened", to_version=3)
    assert added.effective_direction == "tightened"
    assert edited_both.effective_direction == "both"
    assert retired.effective_direction == "loosened"
