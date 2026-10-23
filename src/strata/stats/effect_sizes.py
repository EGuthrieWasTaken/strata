"""Effect sizes and their variances from extracted inputs (openspec:effect-sizes).

Pure: plain numbers in, numbers out, no repository
(openspec:architecture#statistics-know-nothing-of-the-repository). Group 1 is the
treatment/experimental group, group 2 the control; every log is natural. Each result names the
convention and any conversion that produced it, so the number can be reproduced elsewhere
(`metafor::escalc` with `vtype="LS"` for the standardised mean difference).

M3 uses these to show an effect size while it is being entered; M4 builds the pooling models on
top of them.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from scipy import special, stats


class EffectSizeError(ValueError):
    """The inputs cannot produce an effect size (never `NaN` or `inf`: a specific message)."""


@dataclass(frozen=True)
class EffectSize:
    """One effect estimate `yi` with sampling variance `vi`, on the scale named by `measure`."""

    measure: str
    yi: float
    vi: float
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def se(self) -> float:
        return math.sqrt(self.vi)


def _positive(name: str, value: float) -> None:
    if not (math.isfinite(value) and value > 0):
        raise EffectSizeError(f"{name} must be a positive number, got {value!r}")


def _finite(name: str, value: float) -> None:
    if not math.isfinite(value):
        raise EffectSizeError(f"{name} must be a finite number, got {value!r}")


def hedges_j(df: float) -> tuple[float, str]:
    """Small-sample correction `J` and which form was used.

    The exact gamma form `Γ(df/2) / (sqrt(df/2) * Γ((df-1)/2))` is used when `df < 10`, the
    approximation `1 - 3/(4*df - 1)` otherwise (openspec:effect-sizes#standardised-mean-difference).
    """
    if not (math.isfinite(df) and df > 1):
        raise EffectSizeError(f"degrees of freedom must exceed 1 for a bias correction, got {df!r}")
    if df < 10:
        j = math.exp(special.gammaln(df / 2) - special.gammaln((df - 1) / 2)) / math.sqrt(df / 2)
        return j, "exact"
    return 1 - 3 / (4 * df - 1), "approximate"


def smd_from_d(
    d: float, n1: float, n2: float, *, details: dict[str, Any] | None = None
) -> EffectSize:
    """Hedges' g (and its variance) from an uncorrected standardised difference `d`."""
    _finite("d", d)
    _positive("n1", n1)
    _positive("n2", n2)
    j, form = hedges_j(n1 + n2 - 2)
    g = j * d
    vi = 1 / n1 + 1 / n2 + g**2 / (2 * (n1 + n2))
    return EffectSize(
        "SMD",
        g,
        vi,
        {"variance_convention": "LS", "j_form": form, "d": d, "j": j, **(details or {})},
    )


def smd(m1: float, sd1: float, n1: float, m2: float, sd2: float, n2: float) -> EffectSize:
    """Standardised mean difference (Hedges' g) from two groups' means and SDs."""
    for name, value in (("n1", n1), ("n2", n2)):
        _positive(name, value)
    if n1 + n2 <= 2:
        raise EffectSizeError("n1 + n2 must exceed 2 to estimate a pooled SD")
    for name, value in (("sd1", sd1), ("sd2", sd2)):
        if not (math.isfinite(value) and value >= 0):
            raise EffectSizeError(f"{name} must be zero or positive, got {value!r}")
    _finite("m1", m1)
    _finite("m2", m2)
    pooled = math.sqrt(((n1 - 1) * sd1**2 + (n2 - 1) * sd2**2) / (n1 + n2 - 2))
    if pooled == 0:
        raise EffectSizeError("both SDs are zero, so the standardised difference is undefined")
    return smd_from_d((m1 - m2) / pooled, n1, n2)


def md(m1: float, sd1: float, n1: float, m2: float, sd2: float, n2: float) -> EffectSize:
    """Raw mean difference: `yi = m1 - m2`, `vi = sd1^2/n1 + sd2^2/n2`."""
    _positive("n1", n1)
    _positive("n2", n2)
    for name, value in (("sd1", sd1), ("sd2", sd2)):
        if not (math.isfinite(value) and value >= 0):
            raise EffectSizeError(f"{name} must be zero or positive, got {value!r}")
    return EffectSize("MD", m1 - m2, sd1**2 / n1 + sd2**2 / n2)


def _two_by_two(events1: float, n1: float, events2: float, n2: float) -> tuple[float, ...]:
    for name, value in (("events1", events1), ("events2", events2)):
        if not (math.isfinite(value) and value >= 0):
            raise EffectSizeError(f"{name} must be zero or positive, got {value!r}")
    _positive("n1", n1)
    _positive("n2", n2)
    if events1 > n1 or events2 > n2:
        raise EffectSizeError("an event count cannot exceed its group size")
    return events1, n1 - events1, events2, n2 - events2


def _corrected(cells: tuple[float, ...]) -> tuple[tuple[float, ...], dict[str, Any]]:
    """Add 0.5 to every cell when any cell is zero
    (openspec:effect-sizes#ratios-from-a-2x2-table)."""
    details: dict[str, Any] = {}
    if 0 in cells:
        cells = tuple(c + 0.5 for c in cells)
        details["continuity_correction"] = 0.5
    return cells, details


def log_odds_ratio(events1: float, n1: float, events2: float, n2: float) -> EffectSize:
    cells = _two_by_two(events1, n1, events2, n2)
    double_zero = events1 == 0 and events2 == 0
    (a, b, c, d), details = _corrected(cells)
    if double_zero:
        details["double_zero"] = True
    return EffectSize("logOR", math.log(a * d / (b * c)), 1 / a + 1 / b + 1 / c + 1 / d, details)


def log_risk_ratio(events1: float, n1: float, events2: float, n2: float) -> EffectSize:
    cells = _two_by_two(events1, n1, events2, n2)
    double_zero = events1 == 0 and events2 == 0
    (a, b, c, d), details = _corrected(cells)
    if double_zero:
        details["double_zero"] = True
    size1, size2 = a + b, c + d
    return EffectSize(
        "logRR", math.log((a / size1) / (c / size2)), 1 / a - 1 / size1 + 1 / c - 1 / size2, details
    )


def risk_difference(events1: float, n1: float, events2: float, n2: float) -> EffectSize:
    a, b, c, d = _two_by_two(events1, n1, events2, n2)
    return EffectSize("RD", a / n1 - c / n2, a * b / n1**3 + c * d / n2**3)


def zcor(r: float, n: float) -> EffectSize:
    """Fisher's z of a correlation: `yi = atanh(r)`, `vi = 1/(n-3)` (back-transform with tanh)."""
    _finite("r", r)
    if abs(r) >= 1:
        raise EffectSizeError("Fisher's z is undefined for a correlation of exactly -1 or 1")
    if not (math.isfinite(n) and n > 3):
        raise EffectSizeError(
            f"n must exceed 3 for Fisher's z (the variance is 1/(n-3)), got {n!r}"
        )
    return EffectSize("ZCOR", math.atanh(r), 1 / (n - 3), {"transformation": "Fisher z"})


def log_hazard_ratio(hr: float, ci_lo: float, ci_hi: float, level: float = 0.95) -> EffectSize:
    """Log hazard ratio with its SE recovered from the reported confidence interval."""
    for name, value in (("hr", hr), ("ci_lo", ci_lo), ("ci_hi", ci_hi)):
        _positive(name, value)
    if not ci_lo < ci_hi:
        raise EffectSizeError("the confidence interval's lower bound must be below its upper bound")
    if not 0 < level < 1:
        raise EffectSizeError("the confidence level must be between 0 and 1")
    z = stats.norm.ppf((1 + level) / 2)
    se = (math.log(ci_hi) - math.log(ci_lo)) / (2 * z)
    return EffectSize("logHR", math.log(hr), se**2, {"ci_level": level})


def smcr(m_pre: float, sd_pre: float, m_post: float, n: float, r: float) -> EffectSize:
    """Standardised mean change using the pre-test SD: needs the pre-post correlation `r`.

    `yi = J * (m_post - m_pre) / sd_pre`, `vi = 2*(1 - r)/n + yi^2/(2*n)`. `r` is never defaulted:
    it is recorded on the result as `assumed_correlation`, which is what triggers the
    sensitivity analysis over r in {0.3, 0.5, 0.7} in M4.
    """
    _positive("n", n)
    _positive("sd_pre", sd_pre)
    _finite("m_pre", m_pre)
    _finite("m_post", m_post)
    if not (math.isfinite(r) and -1 < r < 1):
        raise EffectSizeError(f"the pre-post correlation must be between -1 and 1, got {r!r}")
    j, form = hedges_j(n - 1)
    yi = j * (m_post - m_pre) / sd_pre
    vi = 2 * (1 - r) / n + yi**2 / (2 * n)
    return EffectSize(
        "SMCR", yi, vi, {"assumed_correlation": r, "j_form": form, "variance_convention": "LS"}
    )


# --- conversions between reported statistics. Each records where the number came from
# (openspec:effect-sizes#conversions-between-reported-statistics). ------------------------------


def _signed(direction: float | str) -> int:
    if direction in (1, "positive", "favours-1"):
        return 1
    if direction in (-1, "negative", "favours-2"):
        return -1
    raise EffectSizeError(
        f"direction must be 1/-1 (or positive/negative, favours-1/favours-2), got {direction!r}"
    )


def d_from_t(t: float, n1: float, n2: float) -> EffectSize:
    """`d = t * sqrt(1/n1 + 1/n2)` for an independent-groups t statistic."""
    _finite("t", t)
    _positive("n1", n1)
    _positive("n2", n2)
    return smd_from_d(t * math.sqrt(1 / n1 + 1 / n2), n1, n2, details={"derived_from": "t"})


def d_from_f(f: float, n1: float, n2: float, direction: float | str) -> EffectSize:
    """`d` from a one-degree-of-freedom F test: `t = sqrt(F)`, signed by `direction`."""
    if not (math.isfinite(f) and f >= 0):
        raise EffectSizeError(f"F must be zero or positive, got {f!r}")
    sign = _signed(direction)
    result = d_from_t(sign * math.sqrt(f), n1, n2)
    return EffectSize(result.measure, result.yi, result.vi, {**result.details, "derived_from": "F"})


def d_from_r(r: float, n: float) -> EffectSize:
    """`d = 2r / sqrt(1 - r^2)` for a correlation; the groups are assumed equal in size."""
    _finite("r", r)
    if abs(r) >= 1:
        raise EffectSizeError(
            "a correlation of exactly -1 or 1 has no finite standardised difference"
        )
    _positive("n", n)
    half = n / 2
    return smd_from_d(
        2 * r / math.sqrt(1 - r**2),
        half,
        half,
        details={"derived_from": "r", "assumed_equal_groups": True},
    )


def d_from_chi2(chi2: float, n: float, direction: float | str) -> EffectSize:
    """`d` from a 2x2 chi-square (1 df): phi = `sqrt(chi2/n)`, then `d_from_r`."""
    if not (math.isfinite(chi2) and chi2 >= 0):
        raise EffectSizeError(f"chi-square must be zero or positive, got {chi2!r}")
    _positive("n", n)
    sign = _signed(direction)
    r = math.sqrt(chi2 / n)
    if r >= 1:
        raise EffectSizeError("chi-square is larger than n allows (phi would exceed 1)")
    result = d_from_r(sign * r, n)
    return EffectSize(
        result.measure, result.yi, result.vi, {**result.details, "derived_from": "chi2"}
    )


def d_from_p(p: float, n1: float, n2: float, direction: float | str) -> EffectSize:
    """`d` from a two-tailed p-value alone: `t = quantile_t(1 - p/2, n1 + n2 - 2)`, signed.

    Approximate by construction, so the result is flagged `derived_from_pvalue` and the
    p-value guardrail fires (openspec:data-extraction#data-quality-guards).
    """
    if not 0 < p < 1:
        raise EffectSizeError(f"p must be strictly between 0 and 1 to recover an effect, got {p!r}")
    _positive("n1", n1)
    _positive("n2", n2)
    sign = _signed(direction)
    t = sign * stats.t.ppf(1 - p / 2, n1 + n2 - 2)
    result = d_from_t(float(t), n1, n2)
    return EffectSize(
        result.measure,
        result.yi,
        result.vi,
        {**result.details, "derived_from": "p", "derived_from_pvalue": True},
    )


def sd_from_se(se: float, n: float) -> float:
    """`sd = se * sqrt(n)`."""
    _positive("n", n)
    if not (math.isfinite(se) and se >= 0):
        raise EffectSizeError(f"SE must be zero or positive, got {se!r}")
    return se * math.sqrt(n)


def sd_from_ci(ci_lo: float, ci_hi: float, n: float, level: float = 0.95) -> float:
    """SD from a mean's confidence interval, using the t distribution with `n - 1` df."""
    _positive("n", n)
    if n < 2:
        raise EffectSizeError("n must be at least 2 to recover an SD from a confidence interval")
    if not ci_lo < ci_hi:
        raise EffectSizeError("the confidence interval's lower bound must be below its upper bound")
    if not 0 < level < 1:
        raise EffectSizeError("the confidence level must be between 0 and 1")
    t = stats.t.ppf((1 + level) / 2, n - 1)
    return float(math.sqrt(n) * (ci_hi - ci_lo) / (2 * t))
