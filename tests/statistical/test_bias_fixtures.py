"""Small-study-effect methods against `metafor` output (openspec:bias-and-sensitivity).

Egger, Begg, trim-and-fill, PET and PEESE are compared with `metafor`'s own functions; Peters and
Harbord, which `metafor` does not provide, with the same regressions written out in R
(`tests/statistical/generate.R`).
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import pytest

from strata.stats import bias

BIAS: dict[str, Any] = json.loads(
    (Path(__file__).parent / "fixtures" / "bias.json").read_text(encoding="utf-8")
)


def close(actual: float, expected: float, rel: float = 1e-8) -> bool:
    return math.isclose(actual, expected, rel_tol=rel, abs_tol=1e-12)


@pytest.mark.parametrize("case", sorted(BIAS))
def test_egger_matches_metafor_regtest(case: str) -> None:
    data, expected = BIAS[case], BIAS[case]["egger"]
    result = bias.egger(data["yi"], data["vi"])
    assert result.bias is not None and result.bias_se is not None
    assert close(result.bias, expected["slope"]) and close(result.bias_se, expected["slope_se"])
    assert close(result.statistic, expected["slope_t"]) and close(result.p, expected["slope_p"])
    assert result.df == expected["df"] and result.k == len(data["yi"])
    assert close(result.detail["effect_at_zero_se"], expected["intercept"])


@pytest.mark.parametrize("case", sorted(BIAS))
def test_begg_matches_metafor_ranktest(case: str) -> None:
    data, expected = BIAS[case], BIAS[case]["begg"]
    result = bias.begg(data["yi"], data["vi"])
    assert close(result.statistic, expected["tau"]) and close(result.p, expected["pval"], 1e-6)


def _trimfill_cases() -> list[tuple[str, str]]:
    return [(case, est) for case in sorted(BIAS) for est in BIAS[case]["trimfill"]]


@pytest.mark.parametrize(("case", "estimator"), _trimfill_cases())
def test_trim_and_fill_matches_metafor(case: str, estimator: str) -> None:
    data, expected = BIAS[case], BIAS[case]["trimfill"][estimator]
    result = bias.trim_and_fill(data["yi"], data["vi"], estimator=estimator)
    assert result.k0 == expected["k0"] and result.side == expected["side"]
    assert close(result.estimate, expected["beta"][0], 1e-6)
    assert close(result.se, expected["se"][0], 1e-6) and close(result.tau2, expected["tau2"], 1e-6)
    assert len(result.filled_yi) == len(expected["yi_filled"])
    for got, want in zip(result.filled_yi, expected["yi_filled"], strict=True):
        assert close(got, want, 1e-6)
    for got, want in zip(result.filled_vi, expected["vi_filled"], strict=True):
        assert close(got, want, 1e-10)


def test_trim_and_fill_is_labelled_a_sensitivity_analysis() -> None:
    data = BIAS["bcg_logrr"]
    result = bias.trim_and_fill(data["yi"], data["vi"])
    assert "sensitivity analysis" in result.label and "not a bias-corrected" in result.label
    assert "correct" not in bias.describe(result).replace("not a bias-corrected estimate", "")


def test_a_failed_trim_and_fill_is_a_specific_error_not_nan() -> None:
    data = BIAS["egger2001_logor"]  # metafor itself fails on the Q0 estimator here
    with pytest.raises(bias.BiasMethodError, match="Q0"):
        bias.trim_and_fill(data["yi"], data["vi"], estimator="Q0")


@pytest.mark.parametrize("case", sorted(BIAS))
def test_pet_and_peese_match_weighted_regressions(case: str) -> None:
    data = BIAS[case]
    result = bias.pet_peese(data["yi"], data["vi"])
    for line, expected in ((result.pet, data["pet"]), (result.peese, data["peese"])):
        assert close(line.intercept, expected["intercept"]) and close(
            line.intercept_se, expected["intercept_se"]
        )
        assert close(line.intercept_p, expected["intercept_p"]) and close(
            line.slope_t, expected["slope_t"]
        )
        assert line.df == expected["df"]
    expected_choice = "PEESE" if data["pet"]["intercept_p"] / 2 < 0.10 else "PET"
    assert result.selected == expected_choice
    chosen = result.peese if result.selected == "PEESE" else result.pet
    assert close(result.estimate, chosen.intercept)


def test_peters_and_harbord_match_their_reference_regressions() -> None:
    data = BIAS["egger2001_logor"]
    a, n1, c, n2 = data["ai"], data["n1i"], data["ci"], data["n2i"]
    peters = bias.peters(data["yi"], a, n1, c, n2)
    assert peters.bias is not None and peters.bias_se is not None
    assert close(peters.bias, data["peters"]["slope"]) and close(
        peters.bias_se, data["peters"]["slope_se"]
    )
    assert close(peters.p, data["peters"]["slope_p"]) and peters.df == data["peters"]["df"]
    harbord = bias.harbord(a, n1, c, n2)
    assert harbord.bias is not None
    assert close(harbord.bias, data["harbord"]["intercept"]) and close(
        harbord.p, data["harbord"]["intercept_p"]
    )
    assert harbord.k == len(a)


def test_the_underpowering_guardrail_refuses_below_ten_unless_forced() -> None:
    assert bias.require_adequate_studies(10, "Egger") is False
    with pytest.raises(bias.UnderpoweredError, match="underpowered"):
        bias.require_adequate_studies(7, "Egger's test")
    assert bias.require_adequate_studies(7, "Egger's test", force=True) is True


def test_edge_cases_give_specific_errors() -> None:
    with pytest.raises(bias.BiasMethodError, match="at least 3"):
        bias.egger([0.1, 0.2], [0.04, 0.05])
    with pytest.raises(bias.BiasMethodError, match="no variation"):
        bias.egger([0.1, 0.2, 0.3], [0.04, 0.04, 0.04])
    with pytest.raises(bias.BiasMethodError, match="finite"):
        bias.egger([0.1, float("nan"), 0.3], [0.04, 0.05, 0.06])
    with pytest.raises(bias.BiasMethodError, match="estimator"):
        bias.trim_and_fill([0.1, 0.2, 0.3], [0.04, 0.05, 0.06], estimator="X0")
    with pytest.raises(bias.BiasMethodError, match="side"):
        bias.trim_and_fill([0.1, 0.2, 0.3], [0.04, 0.05, 0.06], side="up")
    with pytest.raises(bias.BiasMethodError, match="at least 2"):
        bias.trim_and_fill([0.1], [0.04])
