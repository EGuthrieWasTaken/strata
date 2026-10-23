"""Aggregation, the multilevel (CHE) model and CR2 cluster-robust inference against `metafor` and
`clubSandwich` output
(openspec:pooling-models#dependent-effect-sizes-are-never-ignored-silently)."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from strata.stats import models, robust

DEP: dict[str, Any] = json.loads(
    (Path(__file__).parent / "fixtures" / "dependence.json").read_text(encoding="utf-8")
)


def close(actual: float, expected: float, rel: float) -> bool:
    return math.isclose(actual, expected, rel_tol=rel, abs_tol=1e-9)


@pytest.mark.parametrize("rho", ["0.2", "0.5", "0.8"])
def test_aggregation_matches_aggregate_escalc(rho: str) -> None:
    data = DEP["assink_aggregate"]
    got = robust.aggregate_effects(data["study"], data["yi"], data["vi"], float(rho))
    expected = data["results"][rho]
    assert [g.study for g in got] == expected["study"]
    for g, y, v in zip(got, expected["yi"], expected["vi"], strict=True):
        assert close(g.yi, y, 1e-10) and close(g.vi, v, 1e-10)


def test_aggregation_edge_cases() -> None:
    one = robust.aggregate_effects(["a", "a", "b"], [0.2, 0.4, 0.1], [0.04, 0.04, 0.09], rho=0.5)
    assert one[1].yi == 0.1 and one[1].vi == 0.09 and one[1].n_effects == 1  # a lone effect is kept
    assert one[0].vi == pytest.approx((0.04 + 0.04 + 2 * 0.5 * 0.04) / 4)
    with pytest.raises(robust.DependenceError, match="rho"):
        robust.aggregate_effects(["a"], [0.1], [0.04], rho=1.5)
    with pytest.raises(robust.DependenceError, match="positive"):
        robust.aggregate_effects(["a"], [0.1], [0.0], rho=0.5)
    with pytest.raises(robust.DependenceError, match="same"):
        robust.aggregate_effects(["a"], [0.1, 0.2], [0.04], rho=0.5)


def _check_robust(fit: robust.RobustFit, expected: dict[str, Any], rel: float) -> None:
    # The coefficient depends on the fitted variance components, which agree to ~1e-5 (iterative).
    assert close(fit.beta[0], expected["beta"][0], min(rel, 1e-6))
    assert close(fit.se[0], expected["se"][0], rel)
    assert close(fit.df[0], expected["df"][0], rel)
    assert close(fit.tval[0], expected["tval"][0], rel)
    assert close(fit.pval[0], expected["pval"][0], rel)
    assert close(fit.ci_lb[0], expected["ci_lb"][0], rel) and close(
        fit.ci_ub[0], expected["ci_ub"][0], rel
    )


def test_cr2_around_the_random_effects_model_matches_clubsandwich() -> None:
    data = DEP["assink_re_cr2"]
    re = models.random_effects(data["yi"], data["vi"], method="REML", ci_method="wald")
    assert close(re.tau2, data["tau2"], 1e-6)
    fit = robust.cluster_robust_random_effects(data["yi"], data["vi"], data["study"], data["tau2"])
    _check_robust(fit, data["fit"], 1e-6)
    assert fit.n_clusters == 17 and fit.adjustment == "CR2" and fit.df_method == "Satterthwaite"


@pytest.mark.parametrize("rho", ["0.2", "0.5", "0.8"])
def test_che_model_and_its_cr2_match_metafor_and_clubsandwich(rho: str) -> None:
    data = DEP["assink_che"]
    expected = data["results"][rho]
    fit = robust.fit_multilevel(
        data["yi"], data["vi"], data["study"], list(range(len(data["yi"]))), rho=float(rho)
    )
    for got, want in zip(fit.sigma2, expected["sigma2"], strict=True):
        assert close(got, want, 1e-5), (rho, fit.sigma2, expected["sigma2"])
    assert close(fit.beta[0], expected["beta"][0], 1e-6) and close(
        fit.se[0], expected["se"][0], 1e-6
    )
    assert close(fit.loglik, expected["ll"], 1e-8)
    cr2 = robust.cluster_robust_multilevel(data["yi"], fit, data["study"])
    _check_robust(cr2, expected["cr2"], 1e-5)


def test_three_level_model_matches_metafor() -> None:
    data = DEP["konstantopoulos_three_level"]
    fit = robust.fit_multilevel(data["yi"], data["vi"], data["district"], data["study"], rho=0.0)
    for got, want in zip(fit.sigma2, data["sigma2"], strict=True):
        assert close(got, want, 1e-5)
    assert close(fit.beta[0], data["beta"][0], 1e-6) and close(fit.se[0], data["se"][0], 1e-6)
    assert close(fit.loglik, data["ll"], 1e-8)
    _check_robust(
        robust.cluster_robust_multilevel(data["yi"], fit, data["district"]), data["cr2"], 1e-5
    )


def test_independent_effects_reduce_to_the_ordinary_model() -> None:
    """With one effect per cluster and no nested variance the multilevel model is the usual
    random-effects model, so its REML tau^2 and estimate must agree with `models`."""
    rng = np.random.default_rng(3)
    v = rng.uniform(0.02, 0.08, 12)
    y = rng.normal(0.3, 0.25, 12)
    fit = robust.fit_multilevel(y, v, list(range(12)), list(range(12)))
    re = models.random_effects(y, v, method="REML", ci_method="wald")
    assert fit.sigma2[0] + fit.sigma2[1] == pytest.approx(re.tau2, rel=1e-4, abs=1e-8)
    assert fit.beta[0] == pytest.approx(re.beta[0], rel=1e-6)


def test_few_clusters_are_warned_about_with_the_degrees_of_freedom() -> None:
    assert robust.cluster_warnings(25, 18.0) == []
    mild = robust.cluster_warnings(15, 9.5)
    assert len(mild) == 1 and "few-clusters:" in mild[0] and "9.5" in mild[0]
    strong = robust.cluster_warnings(8, 4.2)
    assert len(strong) == 1 and "strong" in strong[0] and "4.2" in strong[0]


def test_degenerate_inputs_give_specific_errors() -> None:
    with pytest.raises(robust.DependenceError, match="at least 2 clusters"):
        robust.fit_multilevel([0.1, 0.2], [0.04, 0.05], [1, 1], [1, 2])
    with pytest.raises(robust.DependenceError, match="same non-zero length"):
        robust.fit_multilevel([0.1, 0.2], [0.04], [1, 2], [1, 2])
    with pytest.raises(robust.DependenceError, match="at least 2 clusters"):
        robust.cluster_robust([0.1, 0.2], [1, 1], [np.eye(2)])
    with pytest.raises(robust.DependenceError, match="one working covariance"):
        robust.cluster_robust([0.1, 0.2], [1, 2], [np.eye(1)])
