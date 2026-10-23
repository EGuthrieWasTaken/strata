"""Every numerical edge case produces a correct value or a specific error, never NaN or inf
(openspec:test-suite, M4)."""

# ruff: noqa: E501
from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import pytest

from strata.analysis import engine, rows
from strata.analysis import spec as sp
from strata.stats import bias, diagnostics, models
from strata.stats import escalc as es
from tests.unit._m4 import effects_repo, write_spec

METHODS = ["DL", "HE", "HS", "SJ", "ML", "REML", "EB", "PM"]


def _finite(fit: models.Fit) -> None:
    numbers = [*fit.beta, *fit.se, *fit.ci_lb, *fit.ci_ub, fit.tau2]
    if fit.heterogeneity:
        numbers += [fit.heterogeneity.q, fit.heterogeneity.i2, fit.heterogeneity.h2]
    assert all(math.isfinite(n) for n in numbers)


# --- one and two studies -----------------------------------------------------------------------


@pytest.mark.parametrize("method", METHODS)
def test_one_study_is_that_study(method: str) -> None:
    fit = models.random_effects([0.3], [0.04], method=method, ci_method="wald")
    assert fit.beta[0] == pytest.approx(0.3) and fit.se[0] == pytest.approx(0.2)
    assert fit.tau2 == 0.0 and fit.heterogeneity is not None and fit.heterogeneity.i2 == 0.0
    assert fit.prediction is not None and fit.prediction.lb is None
    assert "at least 3" in (fit.prediction.reason or "")


def test_one_study_cannot_have_a_knapp_hartung_interval() -> None:
    with pytest.raises(models.ModelError, match="Knapp-Hartung"):
        models.random_effects([0.3], [0.04])
    fit = models.common_effect([0.3], [0.04])
    assert fit.heterogeneity is None and fit.beta[0] == 0.3


@pytest.mark.parametrize("method", METHODS)
def test_two_studies_pool_with_a_t_interval_on_one_degree_of_freedom(method: str) -> None:
    fit = models.random_effects([0.3, 0.6], [0.04, 0.05], method=method)
    _finite(fit)
    assert fit.df == 1
    wald = models.random_effects([0.3, 0.6], [0.04, 0.05], method=method, ci_method="wald")
    assert fit.ci_ub[0] - fit.ci_lb[0] > 4 * (wald.ci_ub[0] - wald.ci_lb[0])
    assert fit.prediction is not None and fit.prediction.lb is None


# --- degenerate heterogeneity ------------------------------------------------------------------


def test_identical_variances_have_a_closed_form_dersimonian_laird_tau2() -> None:
    y, v = [0.1, 0.5, 0.3, 0.9], 0.05
    fit = models.random_effects(y, [v] * 4, method="DL", ci_method="wald")
    mean = sum(y) / 4
    expected = sum((a - mean) ** 2 for a in y) / 3 - v
    assert fit.tau2 == pytest.approx(expected, rel=1e-12)
    assert fit.beta[0] == pytest.approx(mean)


@pytest.mark.parametrize("method", METHODS)
def test_identical_effects_have_no_heterogeneity(method: str) -> None:
    fit = models.random_effects([0.3] * 6, [0.04, 0.05, 0.06, 0.04, 0.05, 0.03], method=method)
    _finite(fit)
    assert fit.tau2 == 0.0 and fit.beta[0] == pytest.approx(0.3)
    assert fit.heterogeneity is not None and fit.heterogeneity.q == pytest.approx(0, abs=1e-12)
    assert fit.heterogeneity.i2 == 0.0 and fit.hk_truncation is True


def test_a_dominant_weight_gives_that_study_and_stays_finite() -> None:
    fit = models.random_effects(
        [0.5, 0.1, 0.2, 0.3], [1e-8, 1, 1, 1], method="REML", ci_method="wald"
    )
    _finite(fit)
    assert fit.beta[0] == pytest.approx(0.5, abs=1e-6)


@pytest.mark.parametrize("method", ["DL", "REML"])
def test_a_weight_that_swamps_double_precision_is_a_specific_error(method: str) -> None:
    with pytest.raises(models.ModelError, match="essentially all the weight"):
        models.random_effects(
            [0.5, 0.1, 0.2, 0.3], [1e-12, 1e12, 1e12, 1e12], method=method, ci_method="wald"
        )
    for other in ("ML", "PM", "HE"):
        _finite(
            models.random_effects(
                [0.5, 0.1, 0.2, 0.3], [1e-12, 1e12, 1e12, 1e12], method=other, ci_method="wald"
            )
        )


def test_very_large_effects_stay_finite() -> None:
    fit = models.random_effects(
        [1e9, 1e9 + 1, 1e9 - 1, 1e9 + 2], [1, 1, 1, 1], method="REML", ci_method="wald"
    )
    _finite(fit)
    assert fit.beta[0] == pytest.approx(1e9 + 0.5)


@pytest.mark.parametrize(
    ("yi", "vi", "match"),
    [
        ([1, 2], [-1, 1], "positive"),
        ([1, 2], [0, 1], "positive"),
        ([1, float("nan")], [1, 1], "finite"),
        ([1, 2], [1, float("inf")], "finite"),
        ([], [], "no effects"),
        ([1, 2], [1], "same length"),
    ],
)
def test_unusable_inputs_are_named(yi: list[float], vi: list[float], match: str) -> None:
    with pytest.raises(models.ModelError, match=match):
        models.random_effects(yi, vi)


# --- effect sizes -------------------------------------------------------------------------------


def test_a_perfect_correlation_and_a_tiny_sample_are_specific_errors() -> None:
    for r in (1.0, -1.0):
        with pytest.raises(es.EffectSizeError, match="undefined"):
            es.zcor(r, 20)
    with pytest.raises(es.EffectSizeError, match="exceed 3"):
        es.zcor(0.5, 3)
    assert es.zcor(0.5, 4).vi == 1.0


def test_very_large_samples_stay_finite() -> None:
    big = es.smd(1, 1, 10**9, 0, 1, 10**9)
    assert big.yi == pytest.approx(1.0, abs=1e-5) and 0 < big.vi < 1e-8
    assert es.zcor(0.5, 1e12).vi == pytest.approx(1e-12, rel=1e-6)


def test_groups_too_small_for_a_pooled_sd_are_specific_errors() -> None:
    with pytest.raises(es.EffectSizeError, match="exceed 2"):
        es.smd(1, 1, 1, 0, 1, 1)
    with pytest.raises(es.EffectSizeError, match="degrees of freedom"):
        es.smd(1, 1, 1, 0, 1, 2)


def test_zero_cells_in_every_arm_are_corrected_and_flagged() -> None:
    both = es.log_odds_ratio(0, 10, 0, 10)
    assert (
        both.yi == 0.0
        and both.details["double_zero"]
        and both.details["continuity_correction"] == 0.5
    )
    full = es.log_odds_ratio(10, 10, 10, 10)
    assert (
        math.isfinite(full.yi)
        and math.isfinite(full.vi)
        and full.details["continuity_correction"] == 0.5
    )
    one = es.log_risk_ratio(0, 10, 5, 10)
    assert math.isfinite(one.yi) and "double_zero" not in one.details
    assert es.risk_difference(0, 10, 0, 10).vi == 0.0  # no correction: the analysis excludes it


def test_proportions_at_the_boundaries_are_corrected_and_round_trip() -> None:
    assert es.logit_proportion(0, 10).details["continuity_correction"] == 0.5
    assert es.logit_proportion(10, 10).details["continuity_correction"] == 0.5
    assert es.logit_proportion(0, 10).yi == pytest.approx(-es.logit_proportion(10, 10).yi)
    for events in (0, 3, 10):
        assert es.inverse_freeman_tukey(
            es.freeman_tukey_proportion(events, 10).yi, 10
        ) == pytest.approx(events / 10, abs=1e-9)


# --- bias tests and diagnostics ---------------------------------------------------------------


def test_bias_tests_name_what_is_missing() -> None:
    with pytest.raises(bias.BiasMethodError, match="at least 3"):
        bias.egger([0.1, 0.2], [0.04, 0.05])
    same = [0.04] * 5
    for test in (bias.egger, bias.pet_peese):
        with pytest.raises(bias.BiasMethodError, match="no variation"):
            test([0.1, 0.2, 0.4, 0.3, 0.5], same)
    with pytest.raises(bias.BiasMethodError, match="tied"):
        bias.begg([0.3] * 6, [0.04, 0.05, 0.06, 0.04, 0.05, 0.03])
    with pytest.raises(bias.BiasMethodError, match="side"):
        bias.trim_and_fill([0.3] * 6, [0.04] * 6)
    explicit = bias.trim_and_fill([0.3] * 6, [0.04] * 6, side="left")
    assert explicit.k0 == 0 and explicit.estimate == pytest.approx(0.3)


def test_trim_and_fill_of_a_symmetric_funnel_adds_nothing() -> None:
    result = bias.trim_and_fill([0.1, 0.2, 0.4], [0.04, 0.05, 0.06])
    assert result.k0 == 0 and result.filled_yi == ()
    assert "not a bias-corrected" in result.label


def test_diagnostics_need_enough_studies_and_a_real_order() -> None:
    with pytest.raises(diagnostics.DiagnosticsError, match="at least 2"):
        diagnostics.leave_one_out([0.1], [0.04])
    with pytest.raises(diagnostics.DiagnosticsError, match="more than"):
        diagnostics.influence_diagnostics([0.1, 0.2], [0.04, 0.05])
    with pytest.raises(diagnostics.DiagnosticsError, match="permutation"):
        diagnostics.cumulative([0.1, 0.3], [0.04, 0.05], [0, 0])
    assert len(diagnostics.leave_one_out([0.1, 0.3], [0.04, 0.05])) == 2


# --- through the analysis ---------------------------------------------------------------------


def _analyse(repo: Any, **spec: Any) -> engine.EngineResult:
    write_spec(repo, **spec)
    parsed = sp.load_spec(repo, "primary")
    return engine.run_analysis(parsed, rows.build_rows(repo, parsed))


def test_a_risk_difference_study_without_variance_is_excluded_with_its_reason(
    tmp_path: Path,
) -> None:
    cells = [(12, 100, 20, 100), (0, 50, 0, 50), (8, 80, 15, 80), (5, 60, 9, 60), (10, 90, 14, 90)]
    repo = effects_repo(
        tmp_path,
        [
            {
                "design": "two-group-binary",
                "inputs": {"events1": a, "n1": b, "events2": c, "n2": d, "measure": "RD"},
            }
            for a, b, c, d in cells
        ],
    )
    write_spec(repo, effect_size={"measure": "RD"})
    selection = rows.build_rows(repo, sp.load_spec(repo, "primary"))
    assert len(selection.rows) == 4
    assert any("zero sampling variance" in reason for reason in selection.excluded)
    result = _analyse(repo, effect_size={"measure": "RD"})
    assert result.estimates["k_studies"] == 4


def test_no_effect_left_after_exclusions_is_a_specific_error(tmp_path: Path) -> None:
    repo = effects_repo(
        tmp_path,
        [
            {
                "design": "two-group-binary",
                "inputs": {"events1": 0, "n1": 20, "events2": 0, "n2": 20, "measure": "logRR"},
            }
        ]
        * 3,
    )
    with pytest.raises(engine.AnalysisError, match="no effect"):
        _analyse(repo, effect_size={"measure": "logRR"})
