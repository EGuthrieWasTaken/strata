"""Effect-size computation against `metafor::escalc()` (openspec:effect-sizes)."""

from __future__ import annotations

import json
import math
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from strata.stats import escalc as es

FIX: dict[str, Any] = json.loads(
    (Path(__file__).parent / "fixtures" / "escalc.json").read_text(encoding="utf-8")
)


def close(actual: float, expected: float, rel: float = 1e-8) -> bool:
    return math.isclose(actual, expected, rel_tol=rel, abs_tol=1e-12)


def _rows(case: dict[str, Any]) -> list[tuple[float, ...]]:
    return list(zip(*case["inputs"], strict=True))


MEASURES: dict[str, Callable[..., es.EffectSize]] = {
    # inputs are in the fixture's column order
    "smd": lambda m1, sd1, n1, m2, sd2, n2: es.smd(m1, sd1, n1, m2, sd2, n2),
    "md": lambda m1, sd1, n1, m2, sd2, n2: es.md(m1, sd1, n1, m2, sd2, n2),
    "or": es.log_odds_ratio,
    "rr": es.log_risk_ratio,
    "rd": es.risk_difference,
    "zcor": es.zcor,
    "plo": es.logit_proportion,
    "pft": es.freeman_tukey_proportion,
    "smcr": lambda m_post, m_pre, sd_pre, n, r: es.smcr(m_pre, sd_pre, m_post, n, r),
}


@pytest.mark.parametrize("name", sorted(MEASURES))
def test_every_row_matches_metafor(name: str) -> None:
    case = FIX[name]
    rows = _rows(case)
    assert rows and len(rows) == len(case["yi"])
    for row, yi, vi in zip(rows, case["yi"], case["vi"], strict=True):
        got = MEASURES[name](*row)
        assert close(got.yi, yi) and close(got.vi, vi), (name, row, got, yi, vi)


def test_a_zero_cell_adds_a_half_to_every_cell_and_a_double_zero_is_flagged() -> None:
    zero = es.log_odds_ratio(0, 116, 3, 117)  # Bach 1996 in the Niel-Weise data
    assert zero.details["continuity_correction"] == 0.5 and "double_zero" not in zero.details
    double = es.log_risk_ratio(0, 118, 0, 105)
    assert double.details["double_zero"] is True and math.isfinite(double.yi)
    assert es.log_odds_ratio(3, 30, 4, 30).details == {}


def test_back_transformed_freeman_tukey_matches_metafor() -> None:
    case = FIX["ipft"]
    for y, n, p in zip(case["y"], case["n"], case["p"], strict=True):
        assert close(es.inverse_freeman_tukey(y, n), p, 1e-10)


def test_conversions_match_the_specified_formulas() -> None:
    c = FIX["conversions"]
    cases = {
        "t": es.d_from_t(c["t"]["t"], c["t"]["n1"], c["t"]["n2"]),
        "F": es.d_from_f(c["F"]["F"], c["F"]["n1"], c["F"]["n2"], c["F"]["direction"]),
        "r": es.d_from_r(c["r"]["r"], c["r"]["n"]),
        "p": es.d_from_p(c["p"]["p"], c["p"]["n1"], c["p"]["n2"], c["p"]["direction"]),
    }
    for name, got in cases.items():
        assert close(got.yi, c[name]["yi"]) and close(got.vi, c[name]["vi"]), name
        assert got.details["derived_from"] == name
    assert cases["p"].details["derived_from_pvalue"] is True
    assert "derived_from_pvalue" not in cases["t"].details


def test_hazard_ratio_from_its_confidence_interval() -> None:
    case = FIX["hazard_ratio"]
    got = es.log_hazard_ratio(case["hr"], case["ci_lo"], case["ci_hi"], case["level"])
    assert close(got.yi, case["yi"]) and close(got.se, case["se"])
