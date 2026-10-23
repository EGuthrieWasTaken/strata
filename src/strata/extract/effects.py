"""Effect designs: the shapes in which a paper reports an effect, and how each becomes `yi`/`vi`.

Implements openspec:data-extraction#effect-data-entry-in-any-reported-form. A *design* names the
inputs an effect needs (`requires`) and how to compute it. A project declares the designs it uses
in `extraction/schema.yaml`; the built-in ones below cover group means (with SD, SE or a
confidence interval), 2x2 tables, correlations, test statistics, a p-value alone, pre-post
change, hazard ratios, and pre-computed effects.

Nothing here touches a repository: it is inputs in, an effect (and warnings) out, which is what
lets the CLI and the web form both show the effect size as it is typed.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from strata.extract import quality
from strata.stats import effect_sizes as es

Inputs = Mapping[str, Any]


class EffectInputError(ValueError):
    """`E_EFFECT_INPUTS`: an effect lacks the inputs its declared design requires."""


@dataclass(frozen=True)
class Design:
    id: str
    requires: tuple[str, ...]
    compute: Callable[[dict[str, Any]], es.EffectSize]
    label: str


def _num(inputs: Inputs, name: str) -> float:
    value = inputs.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise EffectInputError(f"{name!r} must be a number, got {value!r}")
    return float(value)


def _present(inputs: Inputs, name: str) -> bool:
    return inputs.get(name) is not None


def _arm_sd(inputs: Inputs, arm: str) -> float:
    """SD of arm 1 or 2 from whichever form was reported: SD, SE, or a confidence interval."""
    n = _num(inputs, f"n{arm}")
    if _present(inputs, f"sd{arm}"):
        return _num(inputs, f"sd{arm}")
    if _present(inputs, f"se{arm}"):
        return es.sd_from_se(_num(inputs, f"se{arm}"), n)
    return es.sd_from_ci(
        _num(inputs, f"ci_lo{arm}"),
        _num(inputs, f"ci_hi{arm}"),
        n,
        _num(inputs, "ci_level") if _present(inputs, "ci_level") else 0.95,
    )


def _two_group_means(inputs: dict[str, Any]) -> es.EffectSize:
    args = (
        _num(inputs, "m1"),
        _arm_sd(inputs, "1"),
        _num(inputs, "n1"),
        _num(inputs, "m2"),
        _arm_sd(inputs, "2"),
        _num(inputs, "n2"),
    )
    measure = inputs.get("measure", "SMD")
    if measure == "MD":
        return es.md(*args)
    if measure != "SMD":
        raise EffectInputError(f"a two-group-means effect is SMD or MD, not {measure!r}")
    return es.smd(*args)


def _two_group_binary(inputs: dict[str, Any]) -> es.EffectSize:
    args = (
        _num(inputs, "events1"),
        _num(inputs, "n1"),
        _num(inputs, "events2"),
        _num(inputs, "n2"),
    )
    measure = inputs.get("measure", "logOR")
    functions = {"logOR": es.log_odds_ratio, "logRR": es.log_risk_ratio, "RD": es.risk_difference}
    if measure not in functions:
        raise EffectInputError(
            f"a two-group-binary effect is one of {sorted(functions)}, not {measure!r}"
        )
    return functions[measure](*args)


def _precomputed(inputs: dict[str, Any]) -> es.EffectSize:
    measure = inputs.get("measure")
    if not isinstance(measure, str) or not measure:
        raise EffectInputError("a precomputed effect needs its 'measure' (e.g. SMD, logOR)")
    vi = _num(inputs, "vi")
    if vi <= 0:
        raise es.EffectSizeError(f"vi must be positive, got {vi!r}")
    return es.EffectSize(measure, _num(inputs, "yi"), vi, {"derived_from": "precomputed"})


def _f_test(inputs: dict[str, Any]) -> es.EffectSize:
    if _present(inputs, "df1") and _num(inputs, "df1") != 1:
        raise es.EffectSizeError("only an F test with 1 numerator degree of freedom converts to d")
    return es.d_from_f(
        _num(inputs, "F"), _num(inputs, "n1"), _num(inputs, "n2"), inputs.get("direction", 1)
    )


DESIGNS: dict[str, Design] = {
    d.id: d
    for d in (
        Design(
            "two-group-means",
            ("n1", "m1", "sd1", "n2", "m2", "sd2"),
            _two_group_means,
            "Group means (SD, SE or CI)",
        ),
        Design(
            "two-group-binary",
            ("events1", "n1", "events2", "n2"),
            _two_group_binary,
            "2x2 table",
        ),
        Design(
            "correlation",
            ("r", "n"),
            lambda i: es.zcor(_num(i, "r"), _num(i, "n")),
            "Correlation",
        ),
        Design("precomputed", ("yi", "vi", "measure"), _precomputed, "Pre-computed effect"),
        Design(
            "pre-post",
            ("n", "m_pre", "sd_pre", "m_post", "sd_post", "r"),
            lambda i: es.smcr(
                _num(i, "m_pre"), _num(i, "sd_pre"), _num(i, "m_post"), _num(i, "n"), _num(i, "r")
            ),
            "Pre-post change",
        ),
        Design(
            "t-test",
            ("t", "n1", "n2"),
            lambda i: es.d_from_t(_num(i, "t"), _num(i, "n1"), _num(i, "n2")),
            "Independent-groups t",
        ),
        Design("f-test", ("F", "n1", "n2", "direction"), _f_test, "F test (1 df)"),
        Design(
            "chi-square",
            ("chi2", "n", "direction"),
            lambda i: es.d_from_chi2(_num(i, "chi2"), _num(i, "n"), i.get("direction", 1)),
            "Chi-square (2x2)",
        ),
        Design(
            "p-value-only",
            ("p", "n1", "n2", "direction"),
            lambda i: es.d_from_p(
                _num(i, "p"), _num(i, "n1"), _num(i, "n2"), i.get("direction", 1)
            ),
            "p-value only",
        ),
        Design(
            "hazard-ratio",
            ("hr", "ci_lo", "ci_hi"),
            lambda i: es.log_hazard_ratio(
                _num(i, "hr"),
                _num(i, "ci_lo"),
                _num(i, "ci_hi"),
                _num(i, "ci_level") if _present(i, "ci_level") else 0.95,
            ),
            "Hazard ratio with CI",
        ),
    )
}

_ARM_SD = re.compile(r"^sd([12])$")


def missing_inputs(requires: tuple[str, ...] | list[str], inputs: Inputs) -> list[str]:
    """Required inputs that are absent. An `sdK` is met by `sdK`, `seK`, or `ci_loK` + `ci_hiK`."""
    missing = []
    for name in requires:
        arm = _ARM_SD.match(name)
        if arm:
            k = arm.group(1)
            met = (
                _present(inputs, name)
                or _present(inputs, f"se{k}")
                or (_present(inputs, f"ci_lo{k}") and _present(inputs, f"ci_hi{k}"))
            )
        else:
            met = _present(inputs, name)
        if not met:
            missing.append(name)
    return missing


def compute(design: str, inputs: Inputs) -> es.EffectSize:
    """Compute the effect for a built-in design. `E_EFFECT_INPUTS` if inputs are missing;
    `EffectSizeError` if they are present but cannot produce an effect (e.g. both SDs zero)."""
    spec = DESIGNS.get(design)
    if spec is None:
        raise EffectInputError(f"no built-in way to compute a {design!r} effect")
    missing = missing_inputs(spec.requires, inputs)
    if missing:
        raise EffectInputError(f"a {design} effect still needs: {', '.join(missing)}")
    return spec.compute(dict(inputs))


def guard_warnings(
    design: str,
    inputs: Inputs,
    effect: es.EffectSize | None,
    *,
    n_total: float | None = None,
    peer_sds: list[float] | None = None,
) -> list[quality.QualityWarning]:
    """Every data-quality guard that applies to one effect. They warn; none blocks."""
    found: list[quality.QualityWarning | None] = [quality.check_p_derived(design)]
    if effect is not None and effect.measure == "SMD":
        found.append(quality.check_large_effect(effect.yi))
    if design == "two-group-binary":
        found.append(
            quality.check_zero_cell(
                int(_num(inputs, "events1")),
                int(_num(inputs, "n1")),
                int(_num(inputs, "events2")),
                int(_num(inputs, "n2")),
            )
        )
    arm_ns = [_num(inputs, k) for k in ("n1", "n2") if _present(inputs, k)]
    if design != "correlation" and len(arm_ns) == 2:
        found.append(quality.check_n_consistency(_whole(n_total), [int(n) for n in arm_ns]))
    if design == "two-group-means" and peer_sds:
        for arm in ("1", "2"):
            try:
                found.append(quality.check_sd_outlier(_arm_sd(inputs, arm), peer_sds))
            except (EffectInputError, es.EffectSizeError):
                continue
    if design == "t-test" and _present(inputs, "reported_p"):
        df = (
            _num(inputs, "df")
            if _present(inputs, "df")
            else _num(inputs, "n1") + _num(inputs, "n2") - 2
        )
        found.append(quality.check_t_p(_num(inputs, "t"), df, _num(inputs, "reported_p")))
    if design == "f-test" and _present(inputs, "reported_p") and _present(inputs, "df2"):
        found.append(
            quality.check_f_p(
                _num(inputs, "F"),
                _num(inputs, "df1") if _present(inputs, "df1") else 1,
                _num(inputs, "df2"),
                _num(inputs, "reported_p"),
            )
        )
    return [w for w in found if w is not None]


def _whole(value: float | None) -> int | None:
    return None if value is None else int(value)
