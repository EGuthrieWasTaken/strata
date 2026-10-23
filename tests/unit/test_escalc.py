"""Effect sizes (openspec:effect-sizes). Expected values are published or hand-checkable."""

from __future__ import annotations

import math

import pytest

from strata.stats import escalc as es


def test_hedges_j_uses_the_exact_gamma_form_below_ten_df() -> None:
    j, form = es.hedges_j(6)
    assert form == "exact"
    assert j == pytest.approx(math.gamma(3) / (math.sqrt(3) * math.gamma(2.5)), rel=1e-12)
    assert j == pytest.approx(0.8686, abs=1e-4)


def test_hedges_j_is_exact_for_every_df_and_close_to_the_textbook_approximation() -> None:
    j, form = es.hedges_j(98)
    assert form == "exact"  # strata always uses the gamma form, as metafor does
    assert j == pytest.approx(1 - 3 / (4 * 98 - 1), abs=1e-5)


@pytest.mark.parametrize("df", [1, 0.5, 0, -3, math.nan, math.inf])
def test_hedges_j_rejects_degrees_of_freedom_it_cannot_correct(df: float) -> None:
    with pytest.raises(es.EffectSizeError):
        es.hedges_j(df)


def test_smd_matches_a_worked_example() -> None:
    """Means 103 vs 100, SDs 5.5 vs 4.5, n = 50 per group: pooled SD 5.025, d 0.597, g 0.5924."""
    result = es.smd(103, 5.5, 50, 100, 4.5, 50)
    assert result.measure == "SMD"
    assert result.details["d"] == pytest.approx(0.5970, abs=1e-4)
    assert result.yi == pytest.approx(0.5924, abs=1e-4)
    assert result.vi == pytest.approx(1 / 50 + 1 / 50 + result.yi**2 / 200)
    assert result.details["variance_convention"] == "LS"
    assert result.details["j_form"] == "exact"
    assert result.se == pytest.approx(math.sqrt(result.vi))


def test_small_samples_record_the_exact_correction() -> None:
    """openspec:effect-sizes scenario: n1 = n2 = 4 (df = 6) uses the exact gamma form."""
    assert es.smd(10, 2, 4, 8, 2, 4).details["j_form"] == "exact"


def test_smd_direction_and_precision_behave() -> None:
    base = es.smd(10, 2, 20, 8, 2, 20)
    assert es.smd(11, 2, 20, 8, 2, 20).yi > base.yi  # raising m1 raises d
    assert es.smd(8, 2, 20, 10, 2, 20).yi == pytest.approx(-base.yi)
    assert es.smd(10, 2, 40, 8, 2, 40).vi < base.vi  # more participants, less variance


@pytest.mark.parametrize(
    "args",
    [
        (10, 2, 0, 8, 2, 4),
        (10, 2, 4, 8, 2, -1),
        (10, -1, 4, 8, 2, 4),
        (10, 0, 4, 8, 0, 4),
        (10, 2, 1, 8, 2, 1),
        (math.nan, 2, 4, 8, 2, 4),
    ],
)
def test_smd_rejects_inputs_that_cannot_be_standardised(args: tuple[float, ...]) -> None:
    with pytest.raises(es.EffectSizeError):
        es.smd(*args)


def test_raw_mean_difference() -> None:
    """openspec:effect-sizes scenario: m = 10 vs 8, SD 2, n = 4 -> yi 2, vi 2."""
    result = es.md(10, 2, 4, 8, 2, 4)
    assert (result.yi, result.vi) == (2, 2)
    with pytest.raises(es.EffectSizeError):
        es.md(10, -2, 4, 8, 2, 4)
    with pytest.raises(es.EffectSizeError):
        es.md(10, 2, 0, 8, 2, 4)


# BCG vaccine trial 1 (metafor's dat.bcg): 4 of 123 vaccinated vs 11 of 139 controls had TB.
BCG = (4, 123, 11, 139)


def test_log_risk_ratio_matches_metafor_on_the_bcg_trial() -> None:
    result = es.log_risk_ratio(*BCG)
    assert result.yi == pytest.approx(-0.8893, abs=1e-4)
    assert result.vi == pytest.approx(0.3256, abs=1e-4)
    assert "continuity_correction" not in result.details


def test_log_odds_ratio_matches_metafor_on_the_bcg_trial() -> None:
    result = es.log_odds_ratio(*BCG)
    assert result.yi == pytest.approx(-0.9387, abs=1e-4)
    assert result.vi == pytest.approx(0.3571, abs=1e-4)


def test_risk_difference_is_hand_checkable() -> None:
    result = es.risk_difference(*BCG)
    assert result.yi == pytest.approx(4 / 123 - 11 / 139)
    assert result.vi == pytest.approx(4 * 119 / 123**3 + 11 * 128 / 139**3)


def test_a_zero_cell_adds_half_to_every_cell_and_says_so() -> None:
    result = es.log_odds_ratio(0, 20, 5, 20)
    assert result.details["continuity_correction"] == 0.5
    assert result.yi == pytest.approx(math.log((0.5 * 15.5) / (20.5 * 5.5)))
    assert result.vi == pytest.approx(1 / 0.5 + 1 / 20.5 + 1 / 5.5 + 1 / 15.5)
    assert "double_zero" not in result.details


def test_every_participant_having_the_event_is_also_a_zero_cell() -> None:
    assert es.log_risk_ratio(20, 20, 5, 20).details["continuity_correction"] == 0.5


def test_a_double_zero_study_is_computable_but_flagged() -> None:
    for fn in (es.log_odds_ratio, es.log_risk_ratio):
        result = fn(0, 30, 0, 30)
        assert result.details["double_zero"] is True
        assert math.isfinite(result.yi) and math.isfinite(result.vi)


@pytest.mark.parametrize("args", [(-1, 20, 5, 20), (21, 20, 5, 20), (3, 0, 5, 20), (3, 20, 5, -2)])
def test_two_by_two_rejects_impossible_tables(args: tuple[float, ...]) -> None:
    with pytest.raises(es.EffectSizeError):
        es.log_odds_ratio(*args)


def test_fisher_z() -> None:
    result = es.zcor(0.5, 23)
    assert result.yi == pytest.approx(math.atanh(0.5))
    assert result.vi == pytest.approx(1 / 20)
    assert math.tanh(result.yi) == pytest.approx(0.5)  # back-transforms to r
    assert result.details["transformation"] == "Fisher z"


@pytest.mark.parametrize(("r", "n"), [(1, 50), (-1, 50), (0.5, 3), (0.5, 2), (math.nan, 20)])
def test_fisher_z_failures_are_specific_errors_never_nan(r: float, n: float) -> None:
    with pytest.raises(es.EffectSizeError):
        es.zcor(r, n)


def test_log_hazard_ratio_recovers_the_se_from_the_interval() -> None:
    result = es.log_hazard_ratio(0.8, 0.65, 0.98)
    assert result.yi == pytest.approx(math.log(0.8))
    assert math.sqrt(result.vi) == pytest.approx(
        (math.log(0.98) - math.log(0.65)) / (2 * 1.959964), rel=1e-5
    )
    for bad in [(0, 0.5, 1.0), (0.8, 1.0, 0.5), (0.8, -1, 2)]:
        with pytest.raises(es.EffectSizeError):
            es.log_hazard_ratio(*bad)
    with pytest.raises(es.EffectSizeError):
        es.log_hazard_ratio(0.8, 0.65, 0.98, level=1.5)


def test_standardised_mean_change_needs_and_records_the_correlation() -> None:
    """m_pre 10, m_post 12, SD_pre 4, n 20, r .5: J = .96, yi = .48, vi = .05 + .00576."""
    result = es.smcr(10, 4, 12, 20, 0.5)
    assert result.yi == pytest.approx(0.48, abs=1e-3)
    assert result.vi == pytest.approx(0.05576, abs=1e-4)
    assert result.details["assumed_correlation"] == 0.5
    for r in (1, -1, 2, math.nan):
        with pytest.raises(es.EffectSizeError):
            es.smcr(10, 4, 12, 20, r)
    with pytest.raises(es.EffectSizeError):
        es.smcr(10, 0, 12, 20, 0.5)


def test_effect_from_a_t_statistic() -> None:
    """openspec:effect-sizes scenario: t = 2.5, n1 = n2 = 30 records derived_from 't'."""
    result = es.d_from_t(2.5, 30, 30)
    d = 2.5 * math.sqrt(2 / 30)
    assert result.details["derived_from"] == "t"
    assert result.details["d"] == pytest.approx(d)
    assert result.yi == pytest.approx(d * (1 - 3 / (4 * 58 - 1)), abs=1e-5)


def test_effect_from_an_f_statistic_takes_its_sign_from_the_direction() -> None:
    up = es.d_from_f(6.25, 30, 30, "positive")
    down = es.d_from_f(6.25, 30, 30, -1)
    assert up.yi == pytest.approx(es.d_from_t(2.5, 30, 30).yi)
    assert down.yi == pytest.approx(-up.yi)
    assert up.details["derived_from"] == "F"
    with pytest.raises(es.EffectSizeError):
        es.d_from_f(-1, 30, 30, 1)
    with pytest.raises(es.EffectSizeError):
        es.d_from_f(6.25, 30, 30, "sideways")


def test_effect_from_a_correlation_assumes_equal_groups() -> None:
    result = es.d_from_r(0.5, 60)
    assert result.details["d"] == pytest.approx(2 * 0.5 / math.sqrt(0.75))
    assert result.details["assumed_equal_groups"] is True
    assert result.details["derived_from"] == "r"
    with pytest.raises(es.EffectSizeError):
        es.d_from_r(1, 60)


def test_effect_from_a_chi_square() -> None:
    result = es.d_from_chi2(9.0, 100, "favours-2")
    assert result.details["derived_from"] == "chi2"
    assert result.yi < 0
    assert result.details["d"] == pytest.approx(-2 * 0.3 / math.sqrt(1 - 0.09))
    with pytest.raises(es.EffectSizeError):
        es.d_from_chi2(150, 100, 1)  # phi would exceed 1
    with pytest.raises(es.EffectSizeError):
        es.d_from_chi2(-1, 100, 1)


def test_effect_from_a_p_value_alone_is_flagged() -> None:
    """p = .05 (two-tailed), n = 30 + 30: t = 2.0017 on 58 df."""
    result = es.d_from_p(0.05, 30, 30, "positive")
    assert result.details["derived_from_pvalue"] is True
    assert result.details["derived_from"] == "p"
    assert result.details["d"] == pytest.approx(2.00172 * math.sqrt(2 / 30), abs=1e-4)
    assert es.d_from_p(0.05, 30, 30, "negative").yi == pytest.approx(-result.yi)
    for p in (0, 1, -0.1, 1.5):
        with pytest.raises(es.EffectSizeError):
            es.d_from_p(p, 30, 30, 1)


def test_sd_recovery() -> None:
    assert es.sd_from_se(0.5, 100) == pytest.approx(5.0)
    assert es.sd_from_ci(8.0, 12.0, 100) == pytest.approx(
        10 * 4.0 / (2 * 1.98422),
        rel=1e-4,  # t(.975, 99) = 1.984217
    )
    for call in (
        lambda: es.sd_from_se(-1, 10),
        lambda: es.sd_from_se(1, 0),
        lambda: es.sd_from_ci(5, 4, 10),
        lambda: es.sd_from_ci(4, 5, 1),
        lambda: es.sd_from_ci(4, 5, 10, level=0),
    ):
        with pytest.raises(es.EffectSizeError):
            call()


# --- proportions -----------------------------------------------------------------------------


def test_logit_proportion_and_its_continuity_correction() -> None:
    plain = es.logit_proportion(5, 20)
    assert plain.measure == "PLO"
    assert plain.yi == pytest.approx(math.log(0.25 / 0.75))
    assert plain.vi == pytest.approx(1 / (20 * 0.25) + 1 / (20 * 0.75))
    assert "continuity_correction" not in plain.details
    for events in (0, 20):
        corrected = es.logit_proportion(events, 20)
        assert corrected.details["continuity_correction"] == 0.5
        assert math.isfinite(corrected.yi) and corrected.vi > 0


def test_freeman_tukey_proportion() -> None:
    result = es.freeman_tukey_proportion(5, 20)
    assert result.measure == "PFT"
    assert result.yi == pytest.approx(math.asin(math.sqrt(5 / 21)) + math.asin(math.sqrt(6 / 21)))
    assert result.vi == pytest.approx(1 / 20.5)


def test_proportion_inputs_are_validated() -> None:
    for call in (
        lambda: es.logit_proportion(-1, 10),
        lambda: es.logit_proportion(11, 10),
        lambda: es.freeman_tukey_proportion(1, 0),
        lambda: es.freeman_tukey_proportion(float("nan"), 10),
    ):
        with pytest.raises(es.EffectSizeError):
            call()


def test_freeman_tukey_warns_when_study_sizes_differ_tenfold() -> None:
    """openspec scenario: study sizes 20 and 400 -> a back-transformation instability warning."""
    warning = es.freeman_tukey_warning([20, 400])
    assert warning is not None and "instab" in warning and "logit" in warning
    assert es.freeman_tukey_warning([20, 150]) is None
    assert es.freeman_tukey_warning([20]) is None
    assert es.freeman_tukey_warning([]) is None


def test_the_freeman_tukey_back_transformation_edges() -> None:
    assert es.inverse_freeman_tukey(0.0, 20) == 0.0  # at or below the value for no events
    assert es.inverse_freeman_tukey(math.pi, 20) == 1.0  # at or above the value for all events
    assert es.inverse_freeman_tukey(math.pi / 2, 20) == pytest.approx(0.5, abs=0.05)
    roundtrip = es.inverse_freeman_tukey(es.freeman_tukey_proportion(30, 100).yi, 100)
    assert roundtrip == pytest.approx(0.3, abs=0.01)
    with pytest.raises(es.EffectSizeError):
        es.inverse_freeman_tukey(float("inf"), 20)
    with pytest.raises(es.EffectSizeError):
        es.inverse_freeman_tukey(1.0, 0)


def test_back_transformations_name_the_scale_they_return_to() -> None:
    assert es.back_transform("ZCOR", math.atanh(0.4)) == pytest.approx(0.4)
    assert es.back_transform("logOR", math.log(2.5)) == pytest.approx(2.5)
    assert es.back_transform("logRR", 0.0) == 1.0 and es.back_transform("logHR", 0.0) == 1.0
    assert es.back_transform("PLO", 0.0) == 0.5
    assert es.back_transform("SMD", 0.3) == 0.3  # unchanged
    with pytest.raises(es.EffectSizeError):
        es.back_transform("SMD", float("nan"))


def test_d_and_log_odds_ratio_convert_as_opt_in_flagged_effects() -> None:
    d = es.d_from_log_or(math.log(2), 0.1)
    assert d.yi == pytest.approx(math.log(2) * math.sqrt(3) / math.pi)
    assert d.vi == pytest.approx(0.1 * 3 / math.pi**2)
    assert d.details["converted_from"] == "logOR" and d.details["opt_in"] is True
    back = es.log_or_from_d(d.yi, d.vi)
    assert back.yi == pytest.approx(math.log(2)) and back.vi == pytest.approx(0.1)
    assert back.details["converted_from"] == "SMD"
    with pytest.raises(es.EffectSizeError):
        es.d_from_log_or(0.5, 0.0)
    with pytest.raises(es.EffectSizeError):
        es.log_or_from_d(float("inf"), 0.1)
