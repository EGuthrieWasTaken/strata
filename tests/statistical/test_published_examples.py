"""Published worked examples, reproduced end to end from the raw study data.

Each dataset is a published meta-analysis whose pooled results are quoted in the literature or in
the `metafor` documentation; the assertions use the precision at which they were published. They
complement the fixture comparison against `metafor` (which checks agreement to 1e-8 on the same
datasets): these check that strata also agrees with what readers will have seen in print.

Sources
-------
* Borenstein, Hedges, Higgins & Rothstein (2009), Introduction to Meta-Analysis, the six-study
  standardised-mean-difference example of chapters 12-16 (Carroll, Grant, Peck, Donat, Stewart,
  Young), as tabulated with raw means in the `statsmodels` meta-analysis documentation, whose
  results that documentation verifies against R `meta` and `metafor`.
* BCG vaccine trials of Colditz et al. (1994), analysed by Viechtbauer (2010), "Conducting
  meta-analyses in R with the metafor package", Journal of Statistical Software 36(3): the
  random-effects model of the log risk ratio and the meta-regression on absolute latitude.
* Raudenbush (1985) teacher-expectancy studies (Raudenbush & Bryk 1985; Raudenbush 2009).
* Niel-Weise et al. (2007) anti-infective-treated central venous catheters, a review with zero
  cells in many arms (the dataset `dat.nielweise2007` of `metafor`).

Not included: Hedges & Olkin (1985). The worked tables of that book could not be obtained, so no
number from it is asserted here; the same formulae (Hedges' g with the exact small-sample
correction, the Q statistic) are exercised by the Borenstein example above.
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from scipy import stats

from strata.stats import escalc as es
from strata.stats import models

# --- Borenstein et al. (2009) -----------------------------------------------------------------

BORENSTEIN = [  # study, mean_t, sd_t, n_t, mean_c, sd_c, n_c
    ("Carroll", 94, 22, 60, 92, 20, 60),
    ("Grant", 98, 21, 65, 92, 22, 65),
    ("Peck", 98, 28, 40, 88, 26, 40),
    ("Donat", 94, 19, 200, 82, 17, 200),
    ("Stewart", 98, 21, 50, 88, 22, 45),
    ("Young", 96, 21, 85, 92, 22, 85),
]


def _borenstein() -> tuple[list[float], list[float]]:
    effects = [es.smd(m1, s1, n1, m2, s2, n2) for _, m1, s1, n1, m2, s2, n2 in BORENSTEIN]
    return [e.yi for e in effects], [e.vi for e in effects]


def test_borenstein_standardised_mean_differences() -> None:
    yi, vi = _borenstein()
    assert [round(y, 2) for y in yi] == [0.09, 0.28, 0.37, 0.66, 0.46, 0.19]
    assert [round(v, 3) for v in vi] == [0.033, 0.031, 0.051, 0.011, 0.043, 0.024]


def test_borenstein_fixed_effect_and_heterogeneity() -> None:
    yi, vi = _borenstein()
    fit = models.common_effect(yi, vi)
    assert fit.beta[0] == pytest.approx(0.4150, abs=5e-4)
    assert fit.se[0] == pytest.approx(0.0643, abs=5e-4)
    assert (fit.ci_lb[0], fit.ci_ub[0]) == pytest.approx((0.2890, 0.5410), abs=5e-4)
    het = fit.heterogeneity
    assert het is not None
    assert het.q == pytest.approx(11.914, abs=5e-4) and het.df == 5
    assert het.p == pytest.approx(0.0360, abs=5e-4)
    assert het.i2 == pytest.approx(58.03, abs=5e-3)


def test_borenstein_dersimonian_laird_random_effects() -> None:
    yi, vi = _borenstein()
    fit = models.random_effects(yi, vi, method="DL", ci_method="wald")
    assert fit.tau2 == pytest.approx(0.0372, abs=5e-5)
    assert fit.beta[0] == pytest.approx(0.3585, abs=5e-4)
    assert fit.se[0] == pytest.approx(0.1055, abs=5e-4)
    assert (fit.ci_lb[0], fit.ci_ub[0]) == pytest.approx((0.1518, 0.5652), abs=5e-4)


def test_borenstein_knapp_hartung_is_truncated_to_the_wald_error_here() -> None:
    """Q/(k-1) = 2.4 > 1 for the fixed-effect weights but the random-effects Q is below k-1, so
    the ad hoc rule keeps the Wald standard error (`metafor` `test="adhoc"`), with a t interval
    on k-1 = 5 degrees of freedom. Without the truncation the standard error would be 0.0903."""
    yi, vi = _borenstein()
    fit = models.random_effects(yi, vi, method="DL", ci_method="knapp-hartung")
    assert fit.hk_truncation is True
    assert fit.beta[0] == pytest.approx(0.3585, abs=5e-4)
    assert fit.se[0] == pytest.approx(0.1055, abs=5e-4)
    assert (fit.ci_lb[0], fit.ci_ub[0]) == pytest.approx((0.0874, 0.6296), abs=5e-4)


# --- BCG (Colditz et al. 1994; Viechtbauer 2010) ----------------------------------------------

BCG = [  # trial, tpos, tneg, cpos, cneg, absolute latitude
    (1, 4, 119, 11, 128, 44), (2, 6, 300, 29, 274, 55), (3, 3, 228, 11, 209, 42),
    (4, 62, 13536, 248, 12619, 52), (5, 33, 5036, 47, 5761, 13), (6, 180, 1361, 372, 1079, 44),
    (7, 8, 2537, 10, 619, 19), (8, 505, 87886, 499, 87892, 13), (9, 29, 7470, 45, 7232, 27),
    (10, 17, 1699, 65, 1600, 42), (11, 186, 50448, 141, 27197, 18), (12, 5, 2493, 3, 2338, 33),
    (13, 27, 16886, 29, 17825, 33),
]  # fmt: skip


def _bcg() -> tuple[list[float], list[float], list[float]]:
    effects = [es.log_risk_ratio(a, a + b, c, c + d) for _, a, b, c, d, _ in BCG]
    return [e.yi for e in effects], [e.vi for e in effects], [float(row[5]) for row in BCG]


def test_bcg_random_effects_model_as_published() -> None:
    yi, vi, _ = _bcg()
    fit = models.random_effects(yi, vi, method="REML", ci_method="wald")
    assert fit.beta[0] == pytest.approx(-0.7145, abs=5e-5)
    assert fit.se[0] == pytest.approx(0.1798, abs=5e-5)
    assert (fit.ci_lb[0], fit.ci_ub[0]) == pytest.approx((-1.0669, -0.3622), abs=5e-5)
    assert fit.tau2 == pytest.approx(0.3132, abs=5e-5)
    het = fit.heterogeneity
    assert het is not None
    assert het.q == pytest.approx(152.23, abs=5e-3) and het.df == 12
    # `metafor` prints I^2 = 92.22% for this fit (tau^2 relative to the typical variance); strata's
    # I^2 is always the Q-based (Q - df) / Q, the same for every tau^2 estimator.
    assert het.i2 == pytest.approx(100 * (152.233 - 12) / 152.233, abs=5e-3)
    assert math.exp(fit.beta[0]) == pytest.approx(0.489, abs=5e-4)  # pooled risk ratio


def test_bcg_dersimonian_laird_and_the_other_published_intervals() -> None:
    yi, vi, _ = _bcg()
    dl = models.random_effects(yi, vi, method="DL", ci_method="wald")
    assert dl.beta[0] == pytest.approx(-0.7141, abs=5e-5) and dl.tau2 == pytest.approx(
        0.3088, abs=5e-5
    )
    kh = models.random_effects(yi, vi, method="REML", ci_method="knapp-hartung")
    assert (kh.ci_lb[0], kh.ci_ub[0]) == pytest.approx((-1.1084, -0.3206), abs=5e-4)
    reml = models.random_effects(yi, vi, method="REML", ci_method="wald")
    assert reml.prediction is not None
    # `metafor` predict() uses the normal quantile, giving (-1.8667, 0.4376); strata uses a t
    # distribution on k - 2 = 11 degrees of freedom (Riley et al. 2011), which is wider.
    expected = -0.7145 + np.array([-1, 1]) * stats.t.ppf(0.975, 11) * math.sqrt(0.3132 + 0.1798**2)
    assert (reml.prediction.lb, reml.prediction.ub) == pytest.approx(tuple(expected), abs=5e-4)


def test_bcg_latitude_explains_most_of_the_heterogeneity() -> None:
    yi, vi, latitude = _bcg()
    fit = models.random_effects(
        yi, vi, method="REML", ci_method="wald", x=[[1.0, lat] for lat in latitude],
        columns=("intrcpt", "ablat"),
    )  # fmt: skip
    assert fit.beta[0] == pytest.approx(0.2515, abs=5e-4)
    assert fit.beta[1] == pytest.approx(-0.0291, abs=5e-5)
    assert fit.tau2 == pytest.approx(0.0764, abs=5e-4)
    assert fit.r2 == pytest.approx(75.62, abs=5e-2)


# --- Raudenbush (1985) ---------------------------------------------------------------------------

RAUDENBUSH = [  # standardised mean differences and variances as published
    (0.03, 0.0156), (0.12, 0.0216), (-0.14, 0.0279), (1.18, 0.1391), (0.26, 0.1362),
    (-0.06, 0.0106), (-0.02, 0.0106), (-0.32, 0.0484), (0.27, 0.0269), (0.80, 0.0630),
    (0.54, 0.0912), (0.18, 0.0497), (-0.02, 0.0835), (0.23, 0.0841), (-0.18, 0.0253),
    (-0.06, 0.0279), (0.30, 0.0193), (0.07, 0.0088), (-0.07, 0.0303),
]  # fmt: skip


def test_raudenbush_teacher_expectancy() -> None:
    fit = models.random_effects(
        [y for y, _ in RAUDENBUSH], [v for _, v in RAUDENBUSH], method="REML", ci_method="wald"
    )
    assert fit.beta[0] == pytest.approx(0.0837, abs=5e-5)
    assert fit.se[0] == pytest.approx(0.0516, abs=5e-5)
    assert fit.tau2 == pytest.approx(0.0188, abs=5e-5)
    het = fit.heterogeneity
    assert het is not None and het.q == pytest.approx(35.83, abs=5e-3) and het.df == 18
    # `metafor` prints I^2 = 41.86% (tau^2 based); strata's is Q-based: (Q - df) / Q.
    assert het.i2 == pytest.approx(100 * (35.8295 - 18) / 35.8295, abs=5e-3)


# --- Niel-Weise et al. (2007): zero cells ------------------------------------------------------

NIEL_WEISE = [  # events and size, treated then control
    (0, 116, 3, 117), (1, 44, 3, 35), (2, 208, 9, 195), (0, 130, 7, 136), (5, 151, 6, 157),
    (1, 98, 4, 139), (1, 174, 3, 177), (1, 74, 2, 39), (1, 97, 19, 103), (1, 113, 2, 122),
    (0, 66, 7, 64), (0, 70, 1, 58), (3, 188, 5, 175), (6, 187, 11, 180), (0, 118, 0, 105),
    (0, 252, 1, 262), (1, 345, 3, 362), (4, 64, 1, 69),
]  # fmt: skip


def test_zero_cell_trials_are_corrected_and_the_double_zero_trial_is_flagged() -> None:
    effects = [es.log_odds_ratio(*row) for row in NIEL_WEISE]
    corrected = [i for i, e in enumerate(effects) if e.details.get("continuity_correction")]
    assert corrected == [0, 3, 10, 11, 14, 15]  # every trial with a zero cell, none other
    assert [i for i, e in enumerate(effects) if e.details.get("double_zero")] == [14]
    usable = [e for e in effects if not e.details.get("double_zero")]
    fit = models.random_effects(
        [e.yi for e in usable], [e.vi for e in usable], method="REML", ci_method="wald"
    )
    assert all(math.isfinite(x) for x in (*fit.beta, *fit.se, fit.tau2))
    assert fit.ci_ub[0] < 0  # fewer infections with the treated catheters
    assert 0.2 < math.exp(fit.beta[0]) < 0.6
