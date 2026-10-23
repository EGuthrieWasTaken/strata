"""Leave-one-out, influence diagnostics, and cumulative meta-analysis
(openspec:bias-and-sensitivity#sensitivity-analyses-and-diagnostics).

Pure numerics. The influence measures follow `metafor::influence.rma.uni()`: each study is left out,
the model (including `tau^2`) is re-estimated, and the departure of the full-data fit from the
reduced one is summarised. Diagnostics flag studies; they never remove anything.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from strata.stats import models

# openspec:bias-and-sensitivity: |rstudent| > 1.96, Cook's D > 0.45, hat > 3p/k (3/k when p = 1).
RSTUDENT_CUTOFF = 1.96
COOK_CUTOFF = 0.45


class DiagnosticsError(ValueError):
    """The diagnostic cannot be computed for these data."""


@dataclass(frozen=True)
class Influence:
    rstudent: float
    dffits: float
    cook_d: float
    cov_r: float
    tau2_del: float
    qe_del: float
    hat: float
    weight: float  # percent of the total weight
    dfbs: tuple[float, ...]
    flags: tuple[str, ...]


@dataclass(frozen=True)
class LeaveOneOut:
    omitted: int
    estimate: float
    se: float
    ci_lb: float
    ci_ub: float
    tau2: float
    q: float
    i2: float
    k: int
    ci_method: (
        str  # the interval actually used (Wald when too few studies remain for Knapp-Hartung)
    )


@dataclass(frozen=True)
class Cumulative:
    index: int  # position in the order (0-based)
    study: int  # index of the study just added
    estimate: float
    se: float
    ci_lb: float
    ci_ub: float
    tau2: float
    q: float
    k: int
    ci_method: str


def _fit(
    y: np.ndarray,
    v: np.ndarray,
    x: np.ndarray,
    *,
    method: str,
    ci_method: str,
    level: float,
    hk_truncation: bool,
) -> models.Fit:
    """Fit, falling back to a Wald interval when Knapp-Hartung needs more studies than remain."""
    p = x.shape[1]
    use = ci_method
    if ci_method == "knapp-hartung" and y.size <= p:
        use = "wald"
    return models.random_effects(
        y, v, method=method, ci_method=use, x=x.tolist(), level=level, hk_truncation=hk_truncation
    )


def _inputs(
    yi: Sequence[float], vi: Sequence[float], x: Sequence[Sequence[float]] | None
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    y = np.asarray(yi, dtype=float)
    v = np.asarray(vi, dtype=float)
    design = np.ones((y.size, 1)) if x is None else np.asarray(x, dtype=float)
    if y.size < 2:
        raise DiagnosticsError("diagnostics need at least 2 studies")
    if design.shape[0] != y.size or v.shape != y.shape:
        raise DiagnosticsError("yi, vi and the design must have one row per study")
    return y, v, design


def influence_diagnostics(
    yi: Sequence[float],
    vi: Sequence[float],
    *,
    method: str = "REML",
    ci_method: str = "knapp-hartung",
    x: Sequence[Sequence[float]] | None = None,
    level: float = 0.95,
    hk_truncation: bool = True,
) -> list[Influence]:
    """Externally standardised residual, DFFITS, Cook's distance, covariance ratio, leave-one-out
    `tau^2` and `Q_E`, hat value, weight, and DFBETAS for every study, with flags."""
    y, v, design = _inputs(yi, vi, x)
    k, p = design.shape
    if k - 1 <= p:
        raise DiagnosticsError(
            "influence diagnostics refit the model without each study, which needs more than "
            f"{p + 1} studies"
        )
    full = _fit(
        y, v, design, method=method, ci_method=ci_method, level=level, hk_truncation=hk_truncation
    )
    beta = np.asarray(full.beta)
    vb_full = np.asarray(full.vb)
    w_full = 1.0 / (v + full.tau2)
    a_inv = np.linalg.inv((design.T * w_full) @ design)
    hat = w_full * np.einsum("ij,jk,ik->i", design, a_inv, design)
    weights = 100.0 * w_full / float(np.sum(w_full))
    btt = list(range(1, p)) if p > 1 else [0]
    svb = np.linalg.inv(vb_full[np.ix_(btt, btt)])
    det_full = float(np.linalg.det(vb_full[np.ix_(btt, btt)]))
    pred_full = design @ beta

    out: list[Influence] = []
    for i in range(k):
        keep = np.arange(k) != i
        fit = _fit(
            y[keep], v[keep], design[keep],
            method=method, ci_method=ci_method, level=level, hk_truncation=hk_truncation,
        )  # fmt: skip
        beta_del = np.asarray(fit.beta)
        vb_del_fit = np.asarray(fit.vb)
        s2w = fit.s2w
        tau2_del = fit.tau2
        xi = design[i]
        delpred = float(xi @ beta_del)
        vdelpred = float(xi @ vb_del_fit @ xi)
        qe_del = fit.heterogeneity.q if fit.heterogeneity is not None else 0.0
        denom = math.sqrt(s2w * hat[i] * (tau2_del + v[i]))
        dffits = (pred_full[i] - delpred) / denom
        w_del = 1.0 / (v + tau2_del)
        vb_del = np.linalg.inv((design.T * w_del) @ design)
        dfb = beta - beta_del
        dfbs = dfb / np.sqrt(s2w * np.diag(vb_del))
        dfb_btt = dfb[btt]
        cook = float(dfb_btt @ svb @ dfb_btt)
        cov_r = float(np.linalg.det(vb_del_fit[np.ix_(btt, btt)])) / det_full
        resid = y[i] - delpred
        if abs(resid) < 100 * np.finfo(float).eps:
            resid = 0.0
        seresid = math.sqrt(v[i] * s2w + vdelpred + tau2_del * s2w)
        rstudent = resid / seresid
        flags = []
        if abs(rstudent) > RSTUDENT_CUTOFF:
            flags.append("rstudent")
        if cook > COOK_CUTOFF:
            flags.append("cook")
        if hat[i] > 3.0 * p / k:
            flags.append("hat")
        out.append(
            Influence(
                rstudent,
                float(dffits),
                cook,
                cov_r,
                tau2_del,
                float(qe_del),
                float(hat[i]),
                float(weights[i]),
                tuple(float(d) for d in dfbs),
                tuple(flags),
            )  # fmt: skip
        )
    return out


def _q_i2(fit: models.Fit) -> tuple[float, float]:
    het = fit.heterogeneity
    return (het.q, het.i2) if het is not None else (0.0, 0.0)


def leave_one_out(
    yi: Sequence[float],
    vi: Sequence[float],
    *,
    method: str = "REML",
    ci_method: str = "knapp-hartung",
    level: float = 0.95,
    hk_truncation: bool = True,
) -> list[LeaveOneOut]:
    """The pooled estimate, `tau^2` and `I^2` with each study omitted in turn."""
    y, v, design = _inputs(yi, vi, None)
    results = []
    for i in range(y.size):
        keep = np.arange(y.size) != i
        fit = _fit(
            y[keep], v[keep], design[keep],
            method=method, ci_method=ci_method, level=level, hk_truncation=hk_truncation,
        )  # fmt: skip
        q, i2 = _q_i2(fit)
        results.append(
            LeaveOneOut(
                i,
                fit.beta[0],
                fit.se[0],
                fit.ci_lb[0],
                fit.ci_ub[0],
                fit.tau2,
                q,
                i2,
                fit.k,
                fit.ci_method,
            )  # fmt: skip
        )
    return results


def cumulative(
    yi: Sequence[float],
    vi: Sequence[float],
    order: Sequence[int],
    *,
    method: str = "REML",
    ci_method: str = "knapp-hartung",
    level: float = 0.95,
    hk_truncation: bool = True,
) -> list[Cumulative]:
    """Cumulative meta-analysis: pool the first study, the first two, and so on, in `order`
    (indices into the input; e.g. sorted by year or by a moderator)."""
    y, v, design = _inputs(yi, vi, None)
    idx = list(order)
    if sorted(idx) != list(range(y.size)):
        raise DiagnosticsError("order must be a permutation of the study indices")
    results = []
    for n in range(1, len(idx) + 1):
        pick = idx[:n]
        fit = _fit(
            y[pick], v[pick], design[pick],
            method=method, ci_method=ci_method, level=level, hk_truncation=hk_truncation,
        )  # fmt: skip
        q, _i2 = _q_i2(fit)
        results.append(
            Cumulative(
                n - 1,
                idx[n - 1],
                fit.beta[0],
                fit.se[0],
                fit.ci_lb[0],
                fit.ci_ub[0],
                fit.tau2,
                q,
                fit.k,
                fit.ci_method,
            )  # fmt: skip
        )
    return results
