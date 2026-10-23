"""The native pooling models against committed `metafor` fixtures
(openspec:test-suite#statistical-validation).

`tests/statistical/generate.R` produced `fixtures/pooling.json` and `fixtures/meta_regression.json`;
this suite needs no R. Tolerance is 1e-8 relative, 1e-6 for the iteratively fitted estimators
(`ML`, `REML`, `EB`, `PM`) and for root-found intervals. A convention mismatch is fixed in the
model or pinned in the generator, never hidden by loosening a tolerance.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import pytest

from strata.stats import models

FIXTURES = Path(__file__).parent / "fixtures"
ITERATIVE = {"ML", "REML", "EB", "PM"}


def _load(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))  # type: ignore[no-any-return]


POOLING = _load("pooling.json")
REGRESSION = _load("meta_regression.json")


def close(actual: float, expected: float, rel: float) -> bool:
    return math.isclose(actual, expected, rel_tol=rel, abs_tol=1e-12)


def _fit_options(test: str) -> dict[str, Any]:
    # metafor test="z" is a Wald interval; "knha" the untruncated Knapp-Hartung; "adhoc" is
    # Knapp-Hartung with the standard error never below the Wald one (strata's default).
    return {
        "z": {"ci_method": "wald"},
        "knha": {"ci_method": "knapp-hartung", "hk_truncation": False},
        "adhoc": {"ci_method": "knapp-hartung", "hk_truncation": True},
    }[test]


def _cases() -> list[tuple[str, str]]:
    return [(case, key) for case, data in POOLING.items() for key in data["fits"]]


def _compare(fit: models.Fit, expected: dict[str, Any], rel: float, label: str) -> None:
    assert fit.k == expected["k"]
    for name, got in (
        ("beta", fit.beta), ("se", fit.se), ("zval", fit.stat), ("pval", fit.pval),
        ("ci_lb", fit.ci_lb), ("ci_ub", fit.ci_ub),
    ):  # fmt: skip
        for g, e in zip(got, expected[name], strict=True):
            assert close(g, e, rel), f"{label}: {name} {g!r} != {e!r}"
    assert close(fit.tau2, expected["tau2"], rel), (
        f"{label}: tau2 {fit.tau2!r} != {expected['tau2']!r}"
    )
    het = fit.heterogeneity
    if het is not None and fit.k > len(fit.beta):
        assert close(het.q, expected["QE"], 1e-8), label
        assert close(het.p or 0.0, expected["QEp"], 1e-6), label
        assert close(het.i2, expected["I2"], 1e-8), label
        assert close(het.h2, expected["H2"], 1e-8), label


@pytest.mark.parametrize(("case", "key"), _cases())
def test_intercept_only_fits_match_metafor(case: str, key: str) -> None:
    data = POOLING[case]
    expected = data["fits"][key]
    if key == "FE":
        fit = models.common_effect(data["yi"], data["vi"])
        _compare(fit, expected, 1e-8, f"{case} {key}")
        return
    method, test = key.split("|")
    rel = 1e-6 if method in ITERATIVE else 1e-8
    fit = models.random_effects(data["yi"], data["vi"], method=method, **_fit_options(test))
    _compare(fit, expected, rel, f"{case} {key}")
    if "pi_lb" in expected:
        assert fit.prediction is not None and fit.prediction.lb is not None
        assert close(fit.prediction.lb, expected["pi_lb"], max(rel, 1e-8))
        assert close(fit.prediction.ub or 0.0, expected["pi_ub"], max(rel, 1e-8))
    elif fit.k < 3:
        assert fit.prediction is not None and fit.prediction.lb is None  # k = 2: stated, not faked
    if test == "adhoc":
        # Truncated <=> the Wald standard error was used; never below it either way.
        wald = models.random_effects(data["yi"], data["vi"], method=method, ci_method="wald")
        assert fit.se[0] >= wald.se[0] * (1 - 1e-12)
        if fit.hk_truncation:
            assert close(fit.se[0], wald.se[0], 1e-12)


@pytest.mark.parametrize("case", sorted(POOLING))
def test_the_q_profile_interval_for_tau2_matches_metafor(case: str) -> None:
    data = POOLING[case]
    expected = data["fits"]["DL|z"]
    lo, hi = models.q_profile_interval(data["yi"], data["vi"])
    assert close(lo, expected["tau2_ci_lb"], 1e-6)
    assert close(hi, expected["tau2_ci_ub"], 1e-6)
    het = models.random_effects(data["yi"], data["vi"], method="DL").heterogeneity
    assert het is not None and het.tau2_ci is not None
    assert close(het.tau_ci[1] if het.tau_ci else 0.0, expected["tau_ci_ub"], 1e-6)


def _design(case: dict[str, Any]) -> models.Design:
    matrix = tuple(tuple(row) for row in case["X"])
    return models.Design(tuple(case["columns"]), matrix, {}, {})


def _regression_cases() -> list[tuple[str, str]]:
    return [(case, key) for case, data in REGRESSION.items() for key in data["fits"]]


@pytest.mark.parametrize(("case", "key"), _regression_cases())
def test_meta_regression_matches_metafor(case: str, key: str) -> None:
    data = REGRESSION[case]
    expected = data["fits"][key]
    method, test = key.split("|")
    rel = 1e-6 if method in ITERATIVE else 1e-8
    fit = models.meta_regression(
        data["yi"], data["vi"], _design(data), method=method, **_fit_options(test)
    )
    _compare(fit, expected, rel, f"{case} {key}")
    assert fit.qm is not None and fit.qm_p is not None
    assert close(fit.qm, expected["QM"], rel), key
    assert close(fit.qm_p, expected["QMp"], 1e-6), key
    if expected.get("R2") is not None:
        assert fit.r2 is not None and close(fit.r2, expected["R2"], 1e-6), key
    assert fit.heterogeneity is not None
    assert fit.heterogeneity.df == expected["QE_df"]
