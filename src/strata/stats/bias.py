"""Small-study-effect and publication-bias methods (openspec:bias-and-sensitivity).

Egger's regression, Peters' and Harbord's tests for log odds ratios, Begg's rank correlation,
Duval & Tweedie trim-and-fill, and PET-PEESE. Pure numerics
(openspec:architecture#statistics-know-nothing-of-the-repository).

None of these methods *corrects* for publication bias: each result says what it measured
("consistent with small-study effects"), and trim-and-fill is a sensitivity analysis only. The
underpowering guardrail (`k < 10`) lives in `require_adequate_studies`, so the analysis layer can
refuse by default and record `--force`.

Egger, PET and PEESE follow `metafor::regtest()`'s weighted-regression form (weights `1/v`,
multiplicative residual variance, `t` on `k - 2` df); trim-and-fill follows `metafor::trimfill()`.
`tests/statistical` checks them against committed `metafor` output, and Peters and Harbord against
the same regressions written out in R (`metafor` does not provide those two).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
from scipy import stats

from strata.stats import models

MIN_STUDIES = 10  # Cochrane guidance: no asymmetry tests below ten studies
ESTIMATORS = ("L0", "R0", "Q0")


class BiasMethodError(ValueError):
    """The data cannot support the requested method (specific and actionable)."""


class UnderpoweredError(BiasMethodError):
    """Fewer than ten studies and no `--force` (the CLI maps this to exit code 8)."""


def require_adequate_studies(k: int, method: str, *, force: bool = False) -> bool:
    """Refuse `method` below ten studies unless forced; returns `True` when the result must be
    labelled underpowered (forced with `k < 10`)."""
    if k >= MIN_STUDIES:
        return False
    if force:
        return True
    raise UnderpoweredError(
        f"{method} is underpowered with {k} studies (fewer than {MIN_STUDIES}): the test cannot "
        "tell small-study effects from chance, so it is refused; use --force to compute it anyway "
        "(the result is then labelled underpowered)"
    )


@dataclass(frozen=True)
class Line:
    """A weighted straight-line fit `y = intercept + slope * x` (residual variance estimated)."""

    intercept: float
    intercept_se: float
    intercept_t: float
    intercept_p: float
    slope: float
    slope_se: float
    slope_t: float
    slope_p: float
    df: int


def _line(y: np.ndarray, x: np.ndarray, w: np.ndarray) -> Line:
    k = y.size
    if k < 3:
        raise BiasMethodError("a regression test needs at least 3 studies")
    design = np.column_stack([np.ones(k), x])
    xtw = design.T * w
    try:
        cov_unscaled = np.linalg.inv(xtw @ design)
    except np.linalg.LinAlgError as exc:
        raise BiasMethodError(
            "the predictor has no variation, so the line cannot be fitted"
        ) from exc
    beta = cov_unscaled @ (xtw @ y)
    resid = y - design @ beta
    df = k - 2
    sigma2 = float(np.sum(w * resid**2)) / df
    se = np.sqrt(sigma2 * np.diag(cov_unscaled))
    t = beta / se
    p = 2 * stats.t.sf(np.abs(t), df)
    return Line(
        float(beta[0]), float(se[0]), float(t[0]), float(p[0]),
        float(beta[1]), float(se[1]), float(t[1]), float(p[1]), df,
    )  # fmt: skip


def _clean(yi: Sequence[float], vi: Sequence[float]) -> tuple[np.ndarray, np.ndarray]:
    y = np.asarray(yi, dtype=float)
    v = np.asarray(vi, dtype=float)
    if y.shape != v.shape or y.ndim != 1:
        raise BiasMethodError("yi and vi must be one-dimensional and the same length")
    if not (np.all(np.isfinite(y)) and np.all(np.isfinite(v)) and np.all(v > 0)):
        raise BiasMethodError("every effect size must be finite and every variance positive")
    return y, v


@dataclass(frozen=True)
class SmallStudyTest:
    """A test for small-study effects. `bias` is the asymmetry coefficient; `p` is two-sided."""

    method: str
    k: int
    bias: float | None
    bias_se: float | None
    statistic: float
    df: int | None
    p: float
    interpretation: str
    detail: dict[str, float]


def _interpret(p: float, name: str) -> str:
    if p < 0.05:
        return f"{name}: the funnel plot is asymmetric, consistent with small-study effects"
    return (
        f"{name}: no evidence of funnel plot asymmetry "
        "(which does not rule out small-study effects)"
    )


def egger(yi: Sequence[float], vi: Sequence[float]) -> SmallStudyTest:
    """Egger's regression test: the slope of the effect on its standard error, weighted by `1/v`
    (equivalently Egger's intercept in the standard-normal-deviate form)."""
    y, v = _clean(yi, vi)
    line = _line(y, np.sqrt(v), 1.0 / v)
    return SmallStudyTest(
        "egger", y.size, line.slope, line.slope_se, line.slope_t, line.df, line.slope_p,
        _interpret(line.slope_p, "Egger's regression"),
        {"effect_at_zero_se": line.intercept, "effect_se": line.intercept_se},
    )  # fmt: skip


def _counts(
    events1: Sequence[float], n1: Sequence[float], events2: Sequence[float], n2: Sequence[float]
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    a, m, c, o = (np.asarray(x, dtype=float) for x in (events1, n1, events2, n2))
    if not (a.shape == m.shape == c.shape == o.shape) or a.ndim != 1:
        raise BiasMethodError("the four count vectors must be one-dimensional and the same length")
    if np.any(a < 0) or np.any(c < 0) or np.any(a > m) or np.any(c > o):
        raise BiasMethodError("events must lie between 0 and the arm size")
    return a, m, c, o


def peters(
    yi: Sequence[float],
    events1: Sequence[float],
    n1: Sequence[float],
    events2: Sequence[float],
    n2: Sequence[float],
) -> SmallStudyTest:
    """Peters et al. (2006): `ln(OR)` on `1/n`, weights `m1*m0/n`; the slope tests bias."""
    a, m, c, o = _counts(events1, n1, events2, n2)
    y = np.asarray(yi, dtype=float)
    if y.shape != a.shape:
        raise BiasMethodError("yi and the counts must be the same length")
    n = m + o
    m1 = a + c
    m0 = n - m1
    line = _line(y, 1.0 / n, m1 * m0 / n)
    return SmallStudyTest(
        "peters", y.size, line.slope, line.slope_se, line.slope_t, line.df, line.slope_p,
        _interpret(line.slope_p, "Peters' regression"),
        {"effect_at_infinite_n": line.intercept},
    )  # fmt: skip


def harbord(
    events1: Sequence[float], n1: Sequence[float], events2: Sequence[float], n2: Sequence[float]
) -> SmallStudyTest:
    """Harbord et al. (2006): regress `Z/sqrt(V)` on `sqrt(V)` (score statistic and its variance)
    and test the intercept. Studies whose variance is zero (all events, or none) are left out."""
    a, m, c, o = _counts(events1, n1, events2, n2)
    n = m + o
    m1 = a + c
    m0 = n - m1
    ok = (m * o * m1 * m0) > 0
    if int(ok.sum()) < 3:
        raise BiasMethodError("Harbord's test needs at least 3 studies with events and non-events")
    a, m, o, n, m1, m0 = (arr[ok] for arr in (a, m, o, n, m1, m0))
    z = a - m * m1 / n
    v = m * o * m1 * m0 / (n**2 * (n - 1))
    line = _line(z / np.sqrt(v), np.sqrt(v), np.ones(z.size))
    return SmallStudyTest(
        "harbord", int(ok.sum()), line.intercept, line.intercept_se, line.intercept_t, line.df,
        line.intercept_p, _interpret(line.intercept_p, "Harbord's regression"),
        {"excluded": float(ok.size - ok.sum())},
    )  # fmt: skip


def begg(yi: Sequence[float], vi: Sequence[float]) -> SmallStudyTest:
    """Begg & Mazumdar's rank correlation between standardised effects and variances
    (Kendall's tau-b; an exact p-value when there are no ties, as `metafor::ranktest()` does)."""
    y, v = _clean(yi, vi)
    k = y.size
    if k < 3:
        raise BiasMethodError("Begg's test needs at least 3 studies")
    w = 1.0 / v
    theta = float(np.sum(w * y) / np.sum(w))
    v_star = v - 1.0 / float(np.sum(w))
    if np.any(v_star <= 0):
        raise BiasMethodError(
            "a study's variance is not larger than the pooled variance; cannot standardise"
        )
    y_star = (y - theta) / np.sqrt(v_star)
    if len(set(v.tolist())) < 2 or len(set(y_star.tolist())) < 2:
        raise BiasMethodError(
            "Begg's rank correlation is undefined: the variances (or the standardised effects) "
            "are all tied"
        )
    ties = len(set(v.tolist())) < k or len(set(y_star.tolist())) < k
    method = "exact" if (not ties and k <= 200) else "asymptotic"
    result = stats.kendalltau(y_star, v, method=method)
    tau = float(result.statistic)
    return SmallStudyTest(
        "begg", k, None, None, tau, None, float(result.pvalue),
        _interpret(float(result.pvalue), "Begg's rank correlation"), {"kendall_tau": tau},
    )  # fmt: skip


# --- trim and fill --------------------------------------------------------------------------


@dataclass(frozen=True)
class TrimFill:
    """Duval & Tweedie trim-and-fill. A sensitivity analysis, never a bias-corrected estimate."""

    estimator: str
    side: str
    k0: int
    k: int
    estimate_original: float
    estimate: float
    se: float
    tau2: float
    filled_yi: tuple[float, ...]
    filled_vi: tuple[float, ...]
    label: str = "sensitivity analysis (not a bias-corrected estimate)"


def _rank_first(values: np.ndarray) -> np.ndarray:
    order = np.argsort(values, kind="stable")
    ranks = np.empty(values.size, dtype=int)
    ranks[order] = np.arange(1, values.size + 1)
    return ranks


def trim_and_fill(
    yi: Sequence[float],
    vi: Sequence[float],
    *,
    method: str = "REML",
    estimator: str = "L0",
    side: str | None = None,
    max_iterations: int = 100,
) -> TrimFill:
    """Impute the studies missing from one side of the funnel and re-pool (`metafor::trimfill`).

    `side` is the side on which studies are missing; by default it is chosen as `metafor` does,
    from the sign of the slope on the standard error.
    """
    if estimator not in ESTIMATORS:
        raise BiasMethodError(
            f"estimator must be one of {', '.join(ESTIMATORS)}, got {estimator!r}"
        )
    y, v = _clean(yi, vi)
    k = y.size
    if k < 2:
        raise BiasMethodError("trim-and-fill needs at least 2 studies")
    original = models.random_effects(y, v, method=method, ci_method="wald")
    if side is None:
        if float(np.ptp(v)) == 0.0:
            raise BiasMethodError(
                "the side with missing studies cannot be chosen when every sampling variance is "
                "equal (a funnel with no spread in precision); pass side='left' or 'right'"
            )
        design = np.column_stack([np.ones(k), np.sqrt(v)])
        slope = models.random_effects(
            y, v, method=method, ci_method="wald", x=design.tolist(), columns=("intrcpt", "sei")
        ).beta[1]
        side = "right" if slope < 0 else "left"
    elif side not in ("left", "right"):
        raise BiasMethodError("side must be 'left' or 'right'")
    sign = -1.0 if side == "right" else 1.0
    y_flip = sign * y
    order = np.argsort(y_flip, kind="stable")
    ys, vs = y_flip[order], v[order]

    k0 = 0
    previous = -1
    iterations = 0
    beta = 0.0
    centred = ys
    while k0 != previous:
        previous = k0
        iterations += 1
        if iterations > max_iterations:
            raise BiasMethodError("the trim-and-fill algorithm did not converge")
        trimmed = models.random_effects(ys[: k - k0], vs[: k - k0], method=method, ci_method="wald")
        beta = trimmed.beta[0]
        centred = ys - beta
        ranks = _rank_first(np.abs(centred))
        signed = np.sign(centred) * ranks
        if estimator == "R0":
            negative = signed[signed < 0]
            if negative.size == 0:
                raise BiasMethodError(
                    "trim-and-fill (R0) found no study below the centre; cannot estimate k0"
                )
            raw = (k - float(np.max(-negative))) - 1
        else:
            sr = float(np.sum(signed[signed > 0]))
            if estimator == "L0":
                raw = (4 * sr - k * (k + 1)) / (2 * k - 1)
            else:
                inside = 2 * k**2 - 4 * sr + 0.25
                if inside < 0:
                    raise BiasMethodError(
                        "trim-and-fill (Q0) is undefined for these data "
                        "(negative discriminant); try L0 or R0"
                    )
                raw = k - 0.5 - math.sqrt(inside)
        k0 = int(max(0, round(raw)))  # Python rounds half to even, as R does
        if k0 >= k:
            raise BiasMethodError("trim-and-fill would trim every study; the data cannot be filled")
    if k0 == 0:
        return TrimFill(
            estimator,
            side,
            0,
            k,
            original.beta[0],
            original.beta[0],
            original.se[0],
            original.tau2,
            (),
            (),
        )
    extreme = slice(k - k0, k)
    # Mirror the k0 most extreme studies about the trimmed estimate (flipped scale, then back).
    filled_y = sign * (2 * beta - ys[extreme])
    filled_v = vs[extreme]
    pooled = models.random_effects(
        np.concatenate([y, filled_y]),
        np.concatenate([v, filled_v]),
        method=method,
        ci_method="wald",
    )
    return TrimFill(
        estimator, side, k0, k, original.beta[0], pooled.beta[0], pooled.se[0], pooled.tau2,
        tuple(float(x) for x in filled_y), tuple(float(x) for x in filled_v),
    )  # fmt: skip


# --- PET-PEESE ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class PetPeese:
    """Precision-effect test and PEESE (Stanley & Doucouliagos). PEESE is used when the one-tailed
    PET intercept test has p < .10, otherwise PET. Both are sensitivity analyses."""

    k: int
    pet: Line
    peese: Line
    pet_p_one_tailed: float
    selected: str
    estimate: float
    se: float
    label: str = "sensitivity analysis (not a bias-corrected estimate)"


def pet_peese(yi: Sequence[float], vi: Sequence[float]) -> PetPeese:
    y, v = _clean(yi, vi)
    w = 1.0 / v
    pet = _line(y, np.sqrt(v), w)
    peese = _line(y, v, w)
    # One-tailed in the direction of the PET estimate: half the two-sided p when the sign agrees
    # with the estimate (always, here), so the test asks whether the effect is real at all.
    one_tailed = pet.intercept_p / 2.0
    use_peese = one_tailed < 0.10
    chosen = peese if use_peese else pet
    return PetPeese(
        y.size,
        pet,
        peese,
        one_tailed,
        "PEESE" if use_peese else "PET",
        chosen.intercept,
        chosen.intercept_se,
    )


def describe(result: Any) -> str:
    """One sentence in the project's non-"correcting" language."""
    if isinstance(result, SmallStudyTest):
        return result.interpretation
    if isinstance(result, TrimFill):
        return (
            f"trim-and-fill ({result.estimator}) imputed {result.k0} study(ies) on the "
            f"{result.side}; "
            f"the estimate moves from {result.estimate_original:.3f} to {result.estimate:.3f} "
            "(a sensitivity analysis, not a bias-corrected estimate)"
        )
    if isinstance(result, PetPeese):
        return (
            f"{result.selected} estimate {result.estimate:.3f} "
            "(a sensitivity analysis, not a bias-corrected estimate)"
        )
    raise TypeError(type(result).__name__)  # pragma: no cover
