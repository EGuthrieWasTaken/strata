"""Pooling models: common-effect and random-effects, `tau^2` estimators, intervals, heterogeneity,
and meta-regression (openspec:pooling-models).

Pure numerics with no knowledge of the repository
(openspec:architecture#statistics-know-nothing-of-the-repository).
Every estimator follows `metafor::rma.uni` (checked against committed fixtures to 1e-8, 1e-6 for the
iterative `tau^2` estimators: `tests/statistical`). Conventions that differ from the most common
defaults are named in the result so a reader can reproduce them elsewhere:

- `I^2` and `H^2` are the Q-based quantities, `max(0, (Q - df)/Q)` and `Q/df`;
- the prediction interval uses a t distribution on `k - 2` degrees of freedom (Riley et al.);
- `knapp-hartung` intervals never use a standard error smaller than the Wald one (`metafor`'s
  `test="adhoc"`), and say so (`hk_truncation`).

The matrix algebra never forms a `k x k` matrix: the traces and quadratic forms `metafor` writes
with the projection matrix `P` are computed from `p x p` cross-products, so a few thousand effects
fit in milliseconds.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from typing import Any

import numpy as np
from scipy import optimize, stats

TAU2_METHODS = ("DL", "HE", "HS", "SJ", "ML", "REML", "EB", "PM")
CI_METHODS = ("wald", "knapp-hartung")
MAX_ITERATIONS = 200
TOLERANCE = 1e-10
# metafor's guard against a likelihood stuck at a local maximum: eps^0.25.
_LL_TOLERANCE = float(np.finfo(float).eps ** 0.25)


class ModelError(ValueError):
    """The data or options cannot be pooled as asked (always specific and actionable)."""


class ConvergenceError(ModelError):
    """An iterative estimator did not converge; no estimate is returned."""


@dataclass(frozen=True)
class Heterogeneity:
    """Q, `I^2`, `H^2` and `tau^2` with its Q-profile interval, all on the effect-size scale."""

    q: float
    df: int
    p: float | None
    i2: float
    h2: float
    tau2: float
    tau: float
    tau2_ci: tuple[float, float] | None
    tau_ci: tuple[float, float] | None


@dataclass(frozen=True)
class Prediction:
    lb: float | None
    ub: float | None
    df: int | None
    reason: str | None = None


@dataclass(frozen=True)
class Fit:
    """One fitted model. Coefficient fields are tuples in the order of `columns`."""

    model: str  # "common-effect" | "random-effects"
    k: int
    columns: tuple[str, ...]
    beta: tuple[float, ...]
    se: tuple[float, ...]
    stat: tuple[float, ...]  # z, or t when `df` is set
    pval: tuple[float, ...]
    ci_lb: tuple[float, ...]
    ci_ub: tuple[float, ...]
    df: int | None
    level: float
    tau2: float
    tau2_method: str | None
    ci_method: str
    hk_truncation: bool | None
    heterogeneity: Heterogeneity | None
    vb: tuple[tuple[float, ...], ...]
    prediction: Prediction | None = None
    qm: float | None = None
    qm_df: tuple[int, ...] | None = None
    qm_p: float | None = None
    r2: float | None = None
    iterations: int | None = None
    conventions: dict[str, Any] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()

    @property
    def estimate(self) -> float:
        return self.beta[0]


# --- inputs ---------------------------------------------------------------------------------


def _prepare(
    yi: Sequence[float], vi: Sequence[float], x: Sequence[Sequence[float]] | None
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    y = np.asarray(yi, dtype=float)
    v = np.asarray(vi, dtype=float)
    if y.ndim != 1 or v.shape != y.shape:
        raise ModelError("yi and vi must be one-dimensional and the same length")
    if y.size == 0:
        raise ModelError("there are no effects to pool")
    if not (np.all(np.isfinite(y)) and np.all(np.isfinite(v))):
        raise ModelError("every effect size and variance must be a finite number")
    if np.any(v <= 0):
        raise ModelError("every sampling variance must be positive")
    if x is None:
        design = np.ones((y.size, 1))
    else:
        design = np.asarray(x, dtype=float)
        if design.ndim != 2 or design.shape[0] != y.size:
            raise ModelError("the design matrix needs one row per effect")
        if not np.all(np.isfinite(design)):
            raise ModelError("the design matrix must be finite")
    return y, v, design


def _check_rank(design: np.ndarray) -> None:
    if np.linalg.matrix_rank(design) < design.shape[1]:
        raise ModelError("the moderators are collinear: the model matrix is not of full rank")


# --- weighted least squares -------------------------------------------------------------------


@dataclass(frozen=True)
class _Wls:
    w: np.ndarray
    beta: np.ndarray
    vb: np.ndarray  # (X'WX)^-1
    resid: np.ndarray
    rss: float


def _wls(y: np.ndarray, x: np.ndarray, w: np.ndarray) -> _Wls:
    xtw = x.T * w
    a = xtw @ x
    try:
        inverse = np.linalg.inv(a)
    except np.linalg.LinAlgError as exc:  # pragma: no cover - guarded by the rank check
        raise ModelError("the weighted model matrix is singular") from exc
    beta = inverse @ (xtw @ y)
    resid = y - x @ beta
    return _Wls(w, beta, inverse, resid, float(np.sum(w * resid**2)))


def _trace_p(x: np.ndarray, fit: _Wls) -> float:
    b = (x.T * fit.w**2) @ x
    return float(np.sum(fit.w) - np.trace(fit.vb @ b))


def _trace_pp(x: np.ndarray, fit: _Wls) -> float:
    b = (x.T * fit.w**2) @ x
    d = (x.T * fit.w**3) @ x
    ainv_b = fit.vb @ b
    return float(np.sum(fit.w**2) - 2 * np.trace(fit.vb @ d) + np.trace(ainv_b @ ainv_b))


def _q_at(tau2: float, y: np.ndarray, v: np.ndarray, x: np.ndarray) -> float:
    return _wls(y, x, 1.0 / (v + tau2)).rss


# --- tau^2 --------------------------------------------------------------------------------------


def _mad(values: np.ndarray) -> float:
    return float(1.4826 * np.median(np.abs(values - np.median(values))))


def _tau2_iterative(
    method: str, y: np.ndarray, v: np.ndarray, x: np.ndarray, start: float
) -> tuple[float, int]:
    """Fisher scoring for ML, REML and EB with step-halving, as `metafor` does."""
    k, p = x.shape
    tau2 = max(0.0, start)
    for iteration in range(1, MAX_ITERATIONS + 1):
        fit = _wls(y, x, 1.0 / (v + tau2))
        w = fit.w
        wr = w * fit.resid
        if method == "ML":
            adj = (float(np.sum(wr**2)) - float(np.sum(w))) / float(np.sum(w**2))
        elif method == "REML":
            adj = (float(np.sum(wr**2)) - _trace_p(x, fit)) / _trace_pp(x, fit)
        else:  # EB
            adj = (fit.rss * k / (k - p) - k) / float(np.sum(w))
        if not math.isfinite(adj):
            adj = 0.0
        while tau2 + adj < 0.0:
            adj /= 2.0
        new = tau2 + adj
        change = abs(new - tau2)
        tau2 = new
        if change <= TOLERANCE:
            return tau2, iteration
    raise ConvergenceError(
        f"the {method} estimator of tau^2 did not converge within {MAX_ITERATIONS} iterations "
        "(Fisher scoring); try another estimator such as DL or PM"
    )


def _log_likelihood(method: str, tau2: float, y: np.ndarray, v: np.ndarray, x: np.ndarray) -> float:
    k, p = x.shape
    fit = _wls(y, x, 1.0 / (v + tau2))
    ll = -0.5 * float(np.sum(np.log(v + tau2))) - 0.5 * fit.rss
    if method == "ML":
        return float(ll - 0.5 * k * math.log(2 * math.pi))
    _sign, logdet = np.linalg.slogdet((x.T * fit.w) @ x)
    return float(ll - 0.5 * (k - p) * math.log(2 * math.pi) - 0.5 * logdet)


def estimate_tau2(
    yi: Sequence[float],
    vi: Sequence[float],
    *,
    method: str = "REML",
    x: Sequence[Sequence[float]] | None = None,
) -> tuple[float, int | None]:
    """The between-study variance and, for iterative estimators, the iterations used.

    Negative estimates are truncated to zero. Non-convergence raises `ConvergenceError`; it never
    returns the last iterate.
    """
    if method not in TAU2_METHODS:
        raise ModelError(
            f"tau^2 estimator must be one of {', '.join(TAU2_METHODS)}, got {method!r}"
        )
    y, v, design = _prepare(yi, vi, x)
    _check_rank(design)
    return _estimate_tau2(y, v, design, method)


def _estimate_tau2(
    y: np.ndarray, v: np.ndarray, x: np.ndarray, method: str
) -> tuple[float, int | None]:
    k, p = x.shape
    if k <= p:
        # Nothing is left over to estimate heterogeneity from.
        return 0.0, None
    iterations: int | None = None
    # The ordinary-least-squares quantities shared by HE and the starting value of ML/REML/EB.
    hat = np.einsum("ij,jk,ik->i", x, np.linalg.inv(x.T @ x), x)
    ols_resid = y - x @ np.linalg.solve(x.T @ x, x.T @ y)
    he = (float(np.sum(ols_resid**2)) - float(np.sum(v * (1.0 - hat)))) / (k - p)
    if method == "HE":
        tau2 = he
    elif method in ("DL", "HS"):
        fit = _wls(y, x, 1.0 / v)
        if method == "DL":
            tau2 = (fit.rss - (k - p)) / _trace_p(x, fit)
        else:
            tau2 = (fit.rss - k) / float(np.sum(fit.w))
    elif method == "SJ":
        start = float(np.var(y, ddof=1) * (k - 1) / k)
        if start <= 0.0:
            tau2 = 0.0
        else:
            fit = _wls(y, x, 1.0 / (v + start))
            tau2 = start * fit.rss / (k - p)
    elif method == "PM":
        tau2 = _tau2_paule_mandel(y, v, x)
    else:
        tau2, iterations = _tau2_iterative(method, y, v, x, he)
        if method in ("ML", "REML"):
            # metafor's guard: a likelihood at zero above the iterate's means a local maximum.
            ll_zero = _log_likelihood(method, 0.0, y, v, x)
            ll = _log_likelihood(method, tau2, y, v, x)
            if ll_zero - ll > _LL_TOLERANCE and tau2 > TOLERANCE:
                tau2 = 0.0
        # Fisher scoring approaches a boundary optimum only geometrically, so a true zero arrives as
        # a speck (1e-11); a value a billionth of the sampling variance is zero for every purpose.
        if tau2 < 1e-9 * float(np.mean(v)):
            tau2 = 0.0
    return max(0.0, tau2), iterations


def _tau2_paule_mandel(y: np.ndarray, v: np.ndarray, x: np.ndarray) -> float:
    k, p = x.shape
    target = float(k - p)
    if _q_at(0.0, y, v, x) < target:
        return 0.0
    upper = max(100.0, 10.0 * _mad(y) ** 2)
    if _q_at(upper, y, v, x) > target:
        raise ConvergenceError(
            "the PM estimator of tau^2 is larger than the search limit "
            f"({upper:g}); try another estimator"
        )
    return float(
        optimize.brentq(
            lambda t: _q_at(t, y, v, x) - target,
            0.0,
            upper,
            xtol=1e-14,
            rtol=4 * np.finfo(float).eps,
        )
    )


def q_profile_interval(
    yi: Sequence[float],
    vi: Sequence[float],
    *,
    x: Sequence[Sequence[float]] | None = None,
    level: float = 0.95,
) -> tuple[float, float]:
    """The Q-profile (Viechtbauer 2007) confidence interval for `tau^2`.

        Solves `Q(tau^2) = chi-square quantile` on `k - p` degrees of freedom for each bound, with 0
    as the floor. It depends only on the data, not on which estimator gave the point estimate.
    """
    y, v, design = _prepare(yi, vi, x)
    _check_rank(design)
    return _q_profile(y, v, design, level)


def _q_profile(y: np.ndarray, v: np.ndarray, x: np.ndarray, level: float) -> tuple[float, float]:
    k, p = x.shape
    if k <= p:
        raise ModelError("a confidence interval for tau^2 needs more effects than parameters")
    alpha = 1.0 - level
    crit_lower = float(stats.chi2.ppf(alpha / 2, k - p))  # Q below this -> upper bound at the floor
    crit_upper = float(stats.chi2.isf(alpha / 2, k - p))

    def q_minus(target: float) -> Any:
        return lambda t: _q_at(t, y, v, x) - target

    def root(target: float) -> float:
        high = max(1.0, float(np.var(y)))
        while _q_at(high, y, v, x) > target:
            high *= 2.0
            if high > 1e12:  # pragma: no cover - Q decays like 1/tau^2, so this cannot be reached
                raise ModelError("the Q-profile search diverged")
        return float(
            optimize.brentq(q_minus(target), 0.0, high, xtol=1e-14, rtol=4 * np.finfo(float).eps)
        )

    q_zero = _q_at(0.0, y, v, x)
    if q_zero < crit_lower:
        return 0.0, 0.0
    upper = root(crit_lower)
    lower = 0.0 if q_zero < crit_upper else root(crit_upper)
    return lower, upper


# --- fitting ----------------------------------------------------------------------------------


def _tail(level: float) -> float:
    return (1.0 + level) / 2.0


def _heterogeneity(
    y: np.ndarray, v: np.ndarray, x: np.ndarray, tau2: float, level: float, with_ci: bool
) -> Heterogeneity:
    k, p = x.shape
    df = k - p
    if df <= 0:
        return Heterogeneity(0.0, 0, None, 0.0, 1.0, tau2, math.sqrt(tau2), None, None)
    q = max(0.0, _q_at(0.0, y, v, x))
    qp = float(stats.chi2.sf(q, df))
    i2 = max(0.0, 100.0 * (q - df) / q) if q > 0 else 0.0
    h2 = q / df
    ci = tau_ci = None
    if with_ci:
        lo, hi = _q_profile(y, v, x, level)
        ci = (lo, hi)
        tau_ci = (math.sqrt(lo), math.sqrt(hi))
    return Heterogeneity(q, df, qp, i2, h2, tau2, math.sqrt(tau2), ci, tau_ci)


def prediction_interval(
    estimate: float, se: float, tau2: float, k: int, level: float = 0.95
) -> Prediction:
    """`mu +/- t_{k-2} * sqrt(tau^2 + se^2)`; needs `k >= 3` (the `k-2` convention is named in the
    model's conventions)."""
    if k < 3:
        return Prediction(
            None, None, None, "a prediction interval needs at least 3 effects (k - 2 > 0 df)"
        )
    df = k - 2
    half = float(stats.t.ppf(_tail(level), df)) * math.sqrt(tau2 + se**2)
    return Prediction(estimate - half, estimate + half, df)


def _coefficient_table(
    beta: np.ndarray, vb: np.ndarray, df: int | None, level: float
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    se = np.sqrt(np.diag(vb))
    stat = beta / se
    if df is None:
        pval = 2 * stats.norm.sf(np.abs(stat))
        crit = float(stats.norm.ppf(_tail(level)))
    else:
        pval = 2 * stats.t.sf(np.abs(stat), df)
        crit = float(stats.t.ppf(_tail(level), df))
    return se, stat, pval, beta - crit * se, beta + crit * se


def _omnibus(
    beta: np.ndarray, vb: np.ndarray, df: int | None, columns: tuple[str, ...]
) -> tuple[float | None, tuple[int, ...] | None, float | None]:
    """`Q_M` for all coefficients except the intercept (a Wald chi-square, or an F with `k - p`)."""
    if beta.size < 2:
        return None, None, None
    idx = list(range(1, beta.size))
    m = len(idx)
    sub = vb[np.ix_(idx, idx)]
    qm = float(beta[idx] @ np.linalg.solve(sub, beta[idx]))
    if df is None:
        return qm, (m,), float(stats.chi2.sf(qm, m))
    f = qm / m
    return f, (m, df), float(stats.f.sf(f, m, df))


def common_effect(
    yi: Sequence[float],
    vi: Sequence[float],
    *,
    x: Sequence[Sequence[float]] | None = None,
    columns: Sequence[str] | None = None,
    level: float = 0.95,
) -> Fit:
    """The common-effect ("fixed-effect") model: `w = 1/v`. Never the default of an analysis."""
    y, v, design = _prepare(yi, vi, x)
    _check_rank(design)
    k, p = design.shape
    if k < p:
        raise ModelError(f"cannot fit {p} parameters to {k} effects")
    fit = _wls(y, design, 1.0 / v)
    names = tuple(columns) if columns else _default_columns(p)
    se, stat, pval, lb, ub = _coefficient_table(fit.beta, fit.vb, None, level)
    het = _heterogeneity(y, v, design, 0.0, level, with_ci=False) if k > p else None
    qm, qm_df, qm_p = _omnibus(fit.beta, fit.vb, None, names)
    return Fit(
        model="common-effect",
        k=k,
        columns=names,
        beta=tuple(fit.beta),
        se=tuple(se),
        stat=tuple(stat),
        pval=tuple(pval),
        ci_lb=tuple(lb),
        ci_ub=tuple(ub),
        df=None,
        level=level,
        tau2=0.0,
        tau2_method=None,
        ci_method="wald",
        hk_truncation=None,
        heterogeneity=het,
        vb=_matrix(fit.vb),
        qm=qm,
        qm_df=qm_df,
        qm_p=qm_p,
        conventions={"weights": "1/v", "i2": "Q-based", "alias": "fixed-effect"},
    )


def random_effects(
    yi: Sequence[float],
    vi: Sequence[float],
    *,
    method: str = "REML",
    ci_method: str = "knapp-hartung",
    x: Sequence[Sequence[float]] | None = None,
    columns: Sequence[str] | None = None,
    level: float = 0.95,
    hk_truncation: bool = True,
    tau2: float | None = None,
) -> Fit:
    """The random-effects model with weights `1/(v + tau^2)`.

    `ci_method="knapp-hartung"` (the default) inflates the variance by the weighted residual mean
    square, uses `t` on `k - p` degrees of freedom, and, unless `hk_truncation=False`, never lets
    the standard error fall below the Wald one (`metafor`'s `test="adhoc"`).
    """
    if ci_method not in CI_METHODS:
        raise ModelError(f"ci_method must be one of {', '.join(CI_METHODS)}, got {ci_method!r}")
    y, v, design = _prepare(yi, vi, x)
    _check_rank(design)
    k, p = design.shape
    if k < p:
        raise ModelError(f"cannot fit {p} parameters to {k} effects")
    if ci_method == "knapp-hartung" and k <= p:
        raise ModelError(
            f"Knapp-Hartung intervals need more effects than parameters (k = {k}, p = {p}); "
            "use ci_method='wald'"
        )
    iterations: int | None = None
    if tau2 is None:
        if method not in TAU2_METHODS:
            raise ModelError(
                f"tau^2 estimator must be one of {', '.join(TAU2_METHODS)}, got {method!r}"
            )
        tau2_hat, iterations = _estimate_tau2(y, v, design, method)
    else:
        if tau2 < 0 or not math.isfinite(tau2):
            raise ModelError("a fixed tau^2 must be finite and non-negative")
        tau2_hat = float(tau2)
    fit = _wls(y, design, 1.0 / (v + tau2_hat))
    vb = fit.vb
    truncated: bool | None = None
    df: int | None = None
    if ci_method == "knapp-hartung":
        df = k - p
        s2w = 0.0 if fit.rss <= np.finfo(float).eps else fit.rss / df
        truncated = False
        if hk_truncation and s2w < 1.0:
            s2w = 1.0
            truncated = True
        vb = s2w * fit.vb
    names = tuple(columns) if columns else _default_columns(p)
    se, stat, pval, lb, ub = _coefficient_table(fit.beta, vb, df, level)
    het = _heterogeneity(y, v, design, tau2_hat, level, with_ci=k > p)
    qm, qm_df, qm_p = _omnibus(fit.beta, vb, df, names)
    r2 = None
    warnings: list[str] = []
    if p > 1:
        base, _ = (
            _estimate_tau2(y, v, np.ones((k, 1)), method) if tau2 is None else (tau2_hat, None)
        )
        r2 = max(0.0, 100.0 * (base - tau2_hat) / base) if base > 0 else 0.0
        if k / p < 10:
            warnings.append(f"meta-regression:k-per-parameter:k={k}:p={p}")
    prediction = None
    if p == 1:
        prediction = prediction_interval(float(fit.beta[0]), float(se[0]), tau2_hat, k, level)
    conventions: dict[str, Any] = {
        "weights": "1/(v+tau2)",
        "i2": "Q-based",
        "prediction_df": "k-2",
        "tau2_estimator": method if tau2 is None else "fixed",
    }
    if ci_method == "knapp-hartung":
        conventions["hk_truncation"] = hk_truncation
    return Fit(
        model="random-effects",
        k=k,
        columns=names,
        beta=tuple(fit.beta),
        se=tuple(se),
        stat=tuple(stat),
        pval=tuple(pval),
        ci_lb=tuple(lb),
        ci_ub=tuple(ub),
        df=df,
        level=level,
        tau2=tau2_hat,
        tau2_method=method if tau2 is None else None,
        ci_method=ci_method,
        hk_truncation=truncated,
        heterogeneity=het,
        vb=_matrix(vb),
        prediction=prediction,
        qm=qm,
        qm_df=qm_df,
        qm_p=qm_p,
        r2=r2,
        iterations=iterations,
        conventions=conventions,
        warnings=tuple(warnings),
    )


def _matrix(m: np.ndarray) -> tuple[tuple[float, ...], ...]:
    return tuple(tuple(float(c) for c in row) for row in m)


def _default_columns(p: int) -> tuple[str, ...]:
    return ("intrcpt",) if p == 1 else ("intrcpt", *(f"x{i}" for i in range(1, p)))


# --- moderators ------------------------------------------------------------------------------


@dataclass(frozen=True)
class ModeratorSpec:
    name: str
    type: str  # "continuous" | "categorical"
    centering: str | None = None  # "mean" | None (continuous only)
    reference: str | None = None  # categorical only


@dataclass(frozen=True)
class Design:
    columns: tuple[str, ...]
    matrix: tuple[tuple[float, ...], ...]
    centering: dict[str, float]
    references: dict[str, str]


def build_design(rows: Sequence[dict[str, Any]], moderators: Sequence[ModeratorSpec]) -> Design:
    """The model matrix for `moderators`: an intercept, continuous moderators (mean-centred where
    asked, the centring constant reported), and categorical moderators dummy-coded against their
    declared reference level (the first level, alphabetically, when none is declared).

    A row missing a moderator value is an error here; the analysis layer decides how to exclude it.
    """
    columns = ["intrcpt"]
    centering: dict[str, float] = {}
    references: dict[str, str] = {}
    cells: list[list[float]] = [[1.0] for _ in rows]
    for spec in moderators:
        values = [row.get(spec.name) for row in rows]
        if any(value is None for value in values):
            raise ModelError(f"moderator {spec.name!r} is missing for some effects")
        if spec.type == "continuous":
            numbers = np.asarray([float(str(value)) for value in values], dtype=float)
            if not np.all(np.isfinite(numbers)):
                raise ModelError(f"moderator {spec.name!r} must be finite")
            if spec.centering == "mean":
                centre = float(numbers.mean())
                centering[spec.name] = centre
                numbers = numbers - centre
            elif spec.centering not in (None, "none"):
                raise ModelError(f"centering must be 'mean' or 'none', got {spec.centering!r}")
            columns.append(spec.name)
            for cell, number in zip(cells, numbers, strict=True):
                cell.append(float(number))
        elif spec.type == "categorical":
            levels = sorted({str(value) for value in values})
            reference = spec.reference if spec.reference is not None else levels[0]
            if reference not in levels:
                raise ModelError(
                    f"the reference level {reference!r} of {spec.name!r} does not occur "
                    f"among {levels}"
                )
            references[spec.name] = reference
            for level_name in (lv for lv in levels if lv != reference):
                columns.append(f"{spec.name}[{level_name}]")
                for cell, value in zip(cells, values, strict=True):
                    cell.append(1.0 if str(value) == level_name else 0.0)
        else:
            raise ModelError(
                f"moderator type must be 'continuous' or 'categorical', got {spec.type!r}"
            )
    return Design(tuple(columns), tuple(tuple(c) for c in cells), centering, references)


def meta_regression(
    yi: Sequence[float],
    vi: Sequence[float],
    design: Design,
    *,
    method: str = "REML",
    ci_method: str = "knapp-hartung",
    level: float = 0.95,
    hk_truncation: bool = True,
) -> Fit:
    """Weighted least squares on `W = diag(1/(v + tau^2))`; refuses when `k <= p` and warns when
    `k / p < 10` (openspec:pooling-models#meta-regression)."""
    k = len(list(yi))
    p = len(design.columns)
    if k <= p:
        raise ModelError(
            f"cannot fit a meta-regression with {p} parameters to {k} effects: "
            "it needs more effects than parameters"
        )
    fit = random_effects(
        yi,
        vi,
        method=method,
        ci_method=ci_method,
        x=design.matrix,
        columns=design.columns,
        level=level,
        hk_truncation=hk_truncation,
    )
    conventions = {
        **fit.conventions,
        "centering": dict(design.centering),
        "references": dict(design.references),
    }
    return replace(fit, conventions=conventions)
