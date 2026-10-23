"""Influence diagnostics, leave-one-out and cumulative meta-analysis against `metafor`
(openspec:bias-and-sensitivity#sensitivity-analyses-and-diagnostics)."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import pytest

from strata.stats import diagnostics

DIAG: dict[str, Any] = json.loads(
    (Path(__file__).parent / "fixtures" / "diagnostics.json").read_text(encoding="utf-8")
)
CASES = [(case, test) for case in sorted(DIAG) for test in DIAG[case]["fits"]]
# metafor test="z" is a Wald interval; "adhoc" is Knapp-Hartung with truncation (strata's default).
CI = {"z": "wald", "adhoc": "knapp-hartung"}


def close(actual: float, expected: float, rel: float = 1e-6) -> bool:
    return math.isclose(actual, expected, rel_tol=rel, abs_tol=1e-9)


@pytest.mark.parametrize(("case", "test"), CASES)
def test_influence_matches_metafor(case: str, test: str) -> None:
    data = DIAG[case]
    expected = data["fits"][test]["influence"]
    got = diagnostics.influence_diagnostics(data["yi"], data["vi"], ci_method=CI[test])
    for name, attr in (
        ("rstudent", "rstudent"), ("dffits", "dffits"), ("cook_d", "cook_d"),
        ("cov_r", "cov_r"), ("tau2_del", "tau2_del"), ("QE_del", "qe_del"),
        ("hat", "hat"), ("weight", "weight"),
    ):  # fmt: skip
        for i, (g, e) in enumerate(zip(got, expected[name], strict=True)):
            assert close(getattr(g, attr), e), (
                f"{case} {test} {name}[{i}]: {getattr(g, attr)} != {e}"
            )
    for g, e in zip(got, expected["dfbs"], strict=True):
        assert close(g.dfbs[0], e)


@pytest.mark.parametrize(("case", "test"), CASES)
def test_leave_one_out_matches_metafor(case: str, test: str) -> None:
    data = DIAG[case]
    expected = data["fits"][test]["leave_one_out"]
    got = diagnostics.leave_one_out(data["yi"], data["vi"], ci_method=CI[test])
    assert len(got) == len(data["yi"])
    for name, attr in (
        ("estimate", "estimate"), ("se", "se"), ("ci_lb", "ci_lb"), ("ci_ub", "ci_ub"),
        ("tau2", "tau2"), ("Q", "q"), ("I2", "i2"),
    ):  # fmt: skip
        for g, e in zip(got, expected[name], strict=True):
            assert close(getattr(g, attr), e), f"{case} {test} {name}"


@pytest.mark.parametrize(("case", "test"), CASES)
def test_cumulative_matches_metafor(case: str, test: str) -> None:
    data = DIAG[case]
    expected = data["fits"][test]["cumulative"]
    order = [int(i) - 1 for i in expected["order"]]
    got = diagnostics.cumulative(data["yi"], data["vi"], order, ci_method=CI[test])
    assert [g.study for g in got] == order
    for name, attr in (
        ("estimate", "estimate"), ("se", "se"), ("tau2", "tau2"), ("Q", "q"),
        ("ci_lb", "ci_lb"), ("ci_ub", "ci_ub"),
    ):  # fmt: skip
        for i, (g, e) in enumerate(zip(got, expected[name], strict=True)):
            assert close(getattr(g, attr), e), f"{case} {test} {name}[{i}]"


def test_flags_follow_the_documented_cutoffs_and_nothing_is_removed() -> None:
    data = DIAG["k5"]  # the fourth study (1.4) is far from the rest
    result = diagnostics.influence_diagnostics(data["yi"], data["vi"], ci_method="wald")
    assert len(result) == 5
    flagged = {i for i, r in enumerate(result) if r.flags}
    assert 3 in flagged
    for r in result:
        assert ("rstudent" in r.flags) == (abs(r.rstudent) > 1.96)
        assert ("cook" in r.flags) == (r.cook_d > 0.45)
        assert ("hat" in r.flags) == (r.hat > 3 / 5)
    assert sum(r.weight for r in result) == pytest.approx(100.0)


def test_degenerate_inputs_give_specific_errors() -> None:
    with pytest.raises(diagnostics.DiagnosticsError, match="at least 2"):
        diagnostics.leave_one_out([0.1], [0.04])
    with pytest.raises(diagnostics.DiagnosticsError, match="more than"):
        diagnostics.influence_diagnostics([0.1, 0.2], [0.04, 0.05])
    with pytest.raises(diagnostics.DiagnosticsError, match="permutation"):
        diagnostics.cumulative([0.1, 0.2, 0.3], [0.04, 0.05, 0.06], [0, 0, 1])
