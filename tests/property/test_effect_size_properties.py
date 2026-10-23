"""Property tests for the effect-size calculators, per openspec:test-suite#property-invariants.

P12 effect-size monotonicity (increasing `m1` increases `d`; increasing `n` decreases `v`), plus
the symmetries a correct calculator must also obey.
"""

from __future__ import annotations

import math

from hypothesis import assume, given, settings
from hypothesis import strategies as st

from strata.stats import escalc as es

means = st.floats(min_value=-50, max_value=50, allow_nan=False, allow_infinity=False)
sds = st.floats(min_value=0.1, max_value=20, allow_nan=False, allow_infinity=False)
sizes = st.integers(min_value=4, max_value=2000)
steps = st.floats(min_value=0.01, max_value=25, allow_nan=False, allow_infinity=False)


@given(means, sds, sizes, means, sds, sizes, steps)
def test_p12_increasing_the_first_mean_increases_the_effect(
    m1: float, sd1: float, n1: int, m2: float, sd2: float, n2: int, step: float
) -> None:
    low = es.smd(m1, sd1, n1, m2, sd2, n2)
    high = es.smd(m1 + step, sd1, n1, m2, sd2, n2)
    assert high.yi > low.yi
    raw_low, raw_high = es.md(m1, sd1, n1, m2, sd2, n2), es.md(m1 + step, sd1, n1, m2, sd2, n2)
    assert raw_high.yi > raw_low.yi and raw_high.vi == raw_low.vi


@given(
    means,
    sds,
    st.integers(min_value=4, max_value=1000),
    means,
    sds,
    st.integers(4, 1000),
    st.integers(1, 500),
)
def test_p12_increasing_the_sample_size_decreases_the_variance(
    m1: float, sd1: float, n1: int, m2: float, sd2: float, n2: int, extra: int
) -> None:
    # Hold the standardised difference moderate: a huge d dominates the variance, and g's
    # small-sample correction (which grows with n) can then outweigh the 1/n terms.
    pooled = math.sqrt(((n1 - 1) * sd1**2 + (n2 - 1) * sd2**2) / (n1 + n2 - 2))
    assume(abs(m1 - m2) / pooled <= 5)
    small = es.smd(m1, sd1, n1, m2, sd2, n2)
    large = es.smd(m1, sd1, n1 + extra, m2, sd2, n2 + extra)
    assert large.vi < small.vi
    assert es.md(m1, sd1, n1 + extra, m2, sd2, n2 + extra).vi < es.md(m1, sd1, n1, m2, sd2, n2).vi


@given(means, sds, sizes, means, sds, sizes)
def test_swapping_the_groups_negates_the_effect_and_keeps_its_variance(
    m1: float, sd1: float, n1: int, m2: float, sd2: float, n2: int
) -> None:
    forward, backward = es.smd(m1, sd1, n1, m2, sd2, n2), es.smd(m2, sd2, n2, m1, sd1, n1)
    assert math.isclose(forward.yi, -backward.yi, rel_tol=1e-9, abs_tol=1e-12)
    assert math.isclose(forward.vi, backward.vi, rel_tol=1e-9)


@given(means, sds, sizes, means, sds, sizes, means)
def test_shifting_both_means_changes_nothing(
    m1: float, sd1: float, n1: int, m2: float, sd2: float, n2: int, shift: float
) -> None:
    a, b = es.smd(m1, sd1, n1, m2, sd2, n2), es.smd(m1 + shift, sd1, n1, m2 + shift, sd2, n2)
    assert math.isclose(a.yi, b.yi, rel_tol=1e-6, abs_tol=1e-9)


cells = st.integers(min_value=1, max_value=400)


@given(cells, cells, cells, cells)
def test_ratios_are_antisymmetric_in_the_arms(a: int, n1_extra: int, c: int, n2_extra: int) -> None:
    n1, n2 = a + n1_extra, c + n2_extra
    for measure in (es.log_odds_ratio, es.log_risk_ratio, es.risk_difference):
        forward, backward = measure(a, n1, c, n2), measure(c, n2, a, n1)
        assert math.isclose(forward.yi, -backward.yi, rel_tol=1e-9, abs_tol=1e-12)
        assert math.isclose(forward.vi, backward.vi, rel_tol=1e-9)


@given(cells, cells, cells, cells, st.integers(1, 200))
def test_more_events_in_the_first_arm_raise_a_ratio(
    a: int, n1_extra: int, c: int, n2_extra: int, more: int
) -> None:
    n1, n2 = a + n1_extra + more, c + n2_extra
    for measure in (es.log_odds_ratio, es.log_risk_ratio, es.risk_difference):
        assert measure(a + more, n1, c, n2).yi > measure(a, n1, c, n2).yi


@given(
    st.floats(min_value=-0.99, max_value=0.99),
    st.integers(4, 5000),
    st.floats(0.001, 0.4),
    st.integers(1, 5000),
)
def test_correlation_effects_are_monotone(r: float, n: int, step: float, more: int) -> None:
    assume(r + step < 0.999)
    assert es.zcor(r + step, n).yi > es.zcor(r, n).yi
    assert es.zcor(r, n + more).vi < es.zcor(r, n).vi


@given(st.integers(1, 99), st.integers(100, 3000), st.integers(1, 500))
@settings(max_examples=200)
def test_proportions_are_monotone_in_events_and_precise_with_more_data(
    events: int, n: int, more: int
) -> None:
    assume(events + 1 < n)
    for transform in (es.logit_proportion, es.freeman_tukey_proportion):
        assert transform(events + 1, n).yi > transform(events, n).yi
    assert (
        es.freeman_tukey_proportion(events, n + more).vi < es.freeman_tukey_proportion(events, n).vi
    )
