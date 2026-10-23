"""Data-quality guards for extraction.

Implements the guards of openspec:data-extraction#data-quality-guards. Pure: no I/O.
Every guard warns; none blocks.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass

from scipy import stats


@dataclass(frozen=True)
class QualityWarning:
    code: str
    message: str


CODES = (
    "sd-outlier",
    "large-effect",
    "zero-cell",
    "n-inconsistent",
    "p-derived",
    "stat-p-inconsistent",
)


def check_sd_outlier(sd: float, peer_sds: list[float]) -> QualityWarning | None:
    if len(peer_sds) < 2:
        return None
    median = statistics.median(peer_sds)
    if median <= 0:
        return None
    if sd > 3 * median or sd < median / 3:
        return QualityWarning(
            code=CODES[0],
            message=f"SD {sd:g} is an outlier (median {median:g})",
        )
    return None


def check_large_effect(g: float) -> QualityWarning | None:
    if abs(g) > 3:
        return QualityWarning(
            code=CODES[1],
            message=f"Large effect size: {g:g}",
        )
    return None


def check_zero_cell(events1: int, n1: int, events2: int, n2: int) -> QualityWarning | None:
    if events1 < 0 or events1 > n1 or events2 < 0 or events2 > n2:
        raise ValueError("Event count is negative or exceeds its n.")

    cells = [events1, n1 - events1, events2, n2 - events2]
    if 0 in cells:
        return QualityWarning(
            code=CODES[2],
            message=(
                "One or more cells are zero; 0.5 will be added to every cell of the "
                "table (continuity correction) when the odds ratio is computed."
            ),
        )
    return None


def check_n_consistency(n_total: int | None, arm_ns: list[int]) -> QualityWarning | None:
    if n_total is None or not arm_ns:
        return None
    actual_sum = sum(arm_ns)
    if actual_sum != n_total:
        return QualityWarning(
            code=CODES[3],
            message=f"Sum of arm sizes ({actual_sum:g}) does not match n_total ({n_total:g}).",
        )
    return None


def check_p_derived(design: str) -> QualityWarning | None:
    if design == "p-value-only":
        return QualityWarning(
            code=CODES[4],
            message="Effect size was derived from a p-value (approximate).",
        )
    return None


def check_t_p(
    t: float, df: float, p: float, *, t_decimals: int = 2, p_decimals: int = 3
) -> QualityWarning | None:
    if df <= 0 or not (0 <= p <= 1):
        raise ValueError("Invalid df or p-value.")

    h = 0.5 * 10**-t_decimals
    p_lo = 2 * stats.t.sf(abs(t) + h, df)
    p_hi = min(1, 2 * stats.t.sf(max(abs(t) - h, 0), df))
    tol = 0.5 * 10**-p_decimals

    if not (p_lo - tol - 1e-12 <= p <= p_hi + tol + 1e-12):
        return QualityWarning(
            code=CODES[5],
            message=(
                f"Statistic {t:g}, df {df:g}, p {p:g} is inconsistent with "
                f"p range [{p_lo:g}, {p_hi:g}]."
            ),
        )
    return None


def check_f_p(
    f: float, df1: float, df2: float, p: float, *, f_decimals: int = 2, p_decimals: int = 3
) -> QualityWarning | None:
    if df1 <= 0 or df2 <= 0 or not (0 <= p <= 1):
        raise ValueError("Invalid df or p-value.")

    h = 0.5 * 10**-f_decimals
    p_lo = stats.f.sf(f + h, df1, df2)
    p_hi = min(1, stats.f.sf(max(f - h, 0), df1, df2))
    tol = 0.5 * 10**-p_decimals

    if not (p_lo - tol - 1e-12 <= p <= p_hi + tol + 1e-12):
        return QualityWarning(
            code=CODES[5],
            message=(
                f"Statistic {f:g}, df1 {df1:g}, df2 {df2:g}, p {p:g} is "
                f"inconsistent with p range [{p_lo:g}, {p_hi:g}]."
            ),
        )
    return None
