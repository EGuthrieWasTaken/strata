"""Every guardrail fires, can be acknowledged, and only the blocking one needs `--force`
(openspec:analysis-specification#guardrails)."""

# ruff: noqa: E501
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from strata.analysis import engine, guardrails, rows
from strata.analysis import spec as sp
from tests.unit._m4 import effects_repo, meta_repo, write_spec

_SPEC: dict[str, Any] = {
    "id": "primary",
    "title": "Guardrails",
    "preregistered": True,
    "effect_size": {"measure": "SMD"},
    "model": {"type": "random-effects", "tau2_estimator": "REML", "ci_method": "wald"},
}


def _context(**overrides: Any) -> guardrails.Context:
    spec = sp.parse_spec(overrides.pop("spec", _SPEC))
    fields: dict[str, Any] = {
        "spec": spec, "k": 12, "n_params": 1, "i2": 10.0, "multi_effect_studies": [],
        "handling": "none", "p_value_effects": [], "assumed_correlation_effects": [],
        "fit_warnings": [], "freeman_tukey": None, "double_zero": 0, "hk_truncated": False,
        "bias_requested": False,
    }  # fmt: skip
    fields.update(overrides)
    return guardrails.Context(**fields)


CLUSTERS = "dependence:cluster-robust:few-clusters:clusters=8:satterthwaite-df=6.0"
STRONG = "dependence:cluster-robust:few-clusters-strong:clusters=4:satterthwaite-df=2.1"

TRIGGERS: dict[str, dict[str, Any]] = {
    "k-lt-3": {"k": 2},
    "k-lt-5": {"k": 4},
    "k-lt-10-bias-tests": {"k": 6, "bias_requested": True},
    "meta-regression-overfitting": {"k": 12, "n_params": 3},
    "cluster-robust:few-clusters": {"fit_warnings": [CLUSTERS]},
    "cluster-robust:few-clusters-strong": {"fit_warnings": [STRONG]},
    "dependence-ignored": {"multi_effect_studies": ["std_a"], "handling": "none"},
    "p-value-derived": {"p_value_effects": ["eff_1"]},
    "assumed-correlation": {"assumed_correlation_effects": ["eff_1"]},
    "high-heterogeneity": {"i2": 80.0},
    "exploratory": {"spec": {**_SPEC, "preregistered": False}},
    "freeman-tukey-instability": {"freeman_tukey": "sizes differ 20-fold"},
    "double-zero-excluded": {"double_zero": 2},
    "hk-truncation": {"hk_truncated": True},
}


def test_every_guardrail_has_a_trigger() -> None:
    assert set(TRIGGERS) == set(guardrails.CODES)


@pytest.mark.parametrize("code", guardrails.CODES)
def test_a_guardrail_fires_names_itself_and_can_be_acknowledged(code: str) -> None:
    ctx = _context(**TRIGGERS[code])
    fired = {w["code"]: w for w in guardrails.evaluate(ctx, set())}
    assert code in fired
    assert fired[code]["message"] and not fired[code]["acknowledged"]
    acknowledged = {w["code"]: w for w in guardrails.evaluate(ctx, {code})}
    assert acknowledged[code]["acknowledged"]
    assert all(not w["acknowledged"] for c, w in acknowledged.items() if c != code)


def test_only_the_underpowered_bias_test_is_blocking() -> None:
    blocking = set()
    for trigger in TRIGGERS.values():
        blocking |= {
            w["code"] for w in guardrails.evaluate(_context(**trigger), set()) if w["blocking"]
        }
    assert blocking == {"k-lt-10-bias-tests"}
    assert guardrails.evaluate(
        _context(**TRIGGERS["k-lt-10-bias-tests"], forced=["Egger's test"]), set()
    )[0]["forced"]


def test_a_quiet_analysis_fires_nothing() -> None:
    assert guardrails.evaluate(_context(), set()) == []


# --- the ones that arise from data ---------------------------------------------------------------


def _fired(repo: Any, **overrides: Any) -> engine.EngineResult:
    write_spec(repo, **overrides)
    spec = sp.load_spec(repo, "primary")
    return engine.run_analysis(spec, rows.build_rows(repo, spec))


def _codes(result: engine.EngineResult) -> list[str]:
    return [w["code"] for w in result.warnings]


def test_a_p_value_only_effect_fires_p_value_derived(tmp_path: Path) -> None:
    repo = effects_repo(
        tmp_path,
        [
            {"design": "two-group-means", "inputs": {"n1": 30, "m1": 0.7, "sd1": 0.2, "n2": 30, "m2": 0.5, "sd2": 0.2}},
            {"design": "two-group-means", "inputs": {"n1": 25, "m1": 0.65, "sd1": 0.2, "n2": 25, "m2": 0.5, "sd2": 0.25}},
            {"design": "p-value-only", "inputs": {"p": 0.03, "n1": 20, "n2": 20, "direction": 1}},
            {"design": "two-group-means", "inputs": {"n1": 40, "m1": 0.6, "sd1": 0.3, "n2": 40, "m2": 0.5, "sd2": 0.2}},
            {"design": "two-group-means", "inputs": {"n1": 35, "m1": 0.72, "sd1": 0.22, "n2": 35, "m2": 0.5, "sd2": 0.2}},
        ],
    )  # fmt: skip
    assert "p-value-derived" in _codes(_fired(repo))


def test_freeman_tukey_with_very_different_sizes_fires(tmp_path: Path) -> None:
    sizes = [20, 400, 25, 380, 30, 350]
    repo = effects_repo(
        tmp_path,
        [{"design": "single-group-proportion", "inputs": {"events": n // 4, "n": n, "measure": "PFT"}} for n in sizes],
    )  # fmt: skip
    result = _fired(repo, effect_size={"measure": "PFT"})
    assert "freeman-tukey-instability" in _codes(result)
    assert result.estimates["back_transformed"]["scale"] == "proportion"


def test_double_zero_studies_in_a_ratio_analysis_are_counted(tmp_path: Path) -> None:
    cells = [
        (12, 100, 20, 100),
        (0, 50, 0, 50),
        (8, 80, 15, 80),
        (5, 60, 9, 60),
        (0, 40, 0, 40),
        (10, 90, 14, 90),
    ]
    repo = effects_repo(
        tmp_path,
        [{"design": "two-group-binary", "inputs": {"events1": a, "n1": b, "events2": c, "n2": d, "measure": "logRR"}} for a, b, c, d in cells],
    )  # fmt: skip
    result = _fired(repo, effect_size={"measure": "logRR"})
    assert "double-zero-excluded" in _codes(result)
    assert result.estimates["double_zero_excluded"] == 2
    assert result.estimates["k_studies"] == 4


def test_knapp_hartung_truncation_is_flagged_when_heterogeneity_is_absent(tmp_path: Path) -> None:
    near_equal = [0.30, 0.31, 0.30, 0.29, 0.30, 0.31, 0.30, 0.29]
    repo = effects_repo(
        tmp_path,
        [{"design": "precomputed", "inputs": {"yi": y, "vi": 0.05, "measure": "SMD"}} for y in near_equal],
    )  # fmt: skip
    result = _fired(
        repo,
        model={"type": "random-effects", "tau2_estimator": "REML", "ci_method": "knapp-hartung"},
    )
    assert "hk-truncation" in _codes(result)
    assert result.estimates["pooled"]["conventions"]["hk_truncation"] is True


def test_the_meta_regression_overfitting_warning_arises_from_a_specification(
    tmp_path: Path,
) -> None:
    repo = meta_repo(tmp_path, k=12)
    result = _fired(
        repo,
        moderators=[
            {"name": "dose", "type": "continuous"},
            {"name": "other", "type": "continuous"},
        ],
    )
    assert "meta-regression-overfitting" in _codes(result)
