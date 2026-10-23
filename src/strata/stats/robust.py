"""Statistically dependent effect sizes: aggregation, multilevel (correlated-and-hierarchical
effects) models, and cluster-robust inference
(openspec:pooling-models#dependent-effect-sizes-are-never-ignored-silently).

Pure numerics (openspec:architecture#statistics-know-nothing-of-the-repository). Three tools:

- `aggregate_effects`: collapse each study's effects to one (Borenstein et al., an unweighted mean
  with the variance of that mean under an assumed within-study correlation `rho`);
- `fit_multilevel`: a REML random-effects model with a study-level and an effect-level variance
  component and sampling errors correlated at `rho` within a study (the "CHE" working model); with
  `rho = 0` and a higher-level grouping it is the usual three-level model;
- `cluster_robust`: sandwich standard errors clustered on study with the CR2 small-sample
  adjustment and Satterthwaite degrees of freedom (Tipton 2015; Pustejovsky & Tipton 2018), around
  any working covariance, which is how `clubSandwich` does it.

All are checked against `metafor` (`rma.mv`, `aggregate.escalc`) and `clubSandwich` fixtures.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from scipy import optimize, stats


class DependenceError(ValueError):
    """The dependent-effects model cannot be fitted or evaluated for these data."""


# --- aggregation --------------------------------------------------------------------------------


@dataclass(frozen=True)
class Aggregated:
    study: object
    yi: float
    vi: float
    n_effects: int


def aggregate_effects(
    study: Sequence[object], yi: Sequence[float], vi: Sequence[float], rho: float
) -> list[Aggregated]:
    """One effect per study: `y = mean(y_i)`, `v = (sum v_i + sum_{i != j} rho sqrt(v_i v_j))/m^2`.

    `rho` must be given explicitly (it is an assumption, and the analysis sweeps it). Studies are
    returned in order of first appearance.
    """
    if not 0.0 <= rho <= 1.0:
        raise DependenceError("rho must lie between 0 and 1")
    y = np.asarray(yi, dtype=float)
    v = np.asarray(vi, dtype=float)
    if not (y.size == v.size == len(study)) or y.size == 0:
        raise DependenceError("study, yi and vi must be the same non-zero length")
    if not (np.all(np.isfinite(y)) and np.all(np.isfinite(v)) and np.all(v > 0)):
        raise DependenceError("every effect size must be finite and every variance positive")
    order: list[object] = []
    members: dict[object, list[int]] = {}
    for i, s in enumerate(study):
        if s not in members:
            members[s] = []
            order.append(s)
        members[s].append(i)
    out = []
    for s in order:
        idx = members[s]
        m = len(idx)
        sd = np.sqrt(v[idx])
        cross = float(np.sum(np.outer(sd, sd)) - np.sum(v[idx]))  # sum over i != j of sqrt(v_i v_j)
        variance = (float(np.sum(v[idx])) + rho * cross) / m**2
        out.append(Aggregated(s, float(np.mean(y[idx])), variance, m))
    return out


# --- clusters -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Cluster:
    label: object
    idx: np.ndarray


def _clusters(labels: Sequence[object]) -> list[_Cluster]:
    order: list[object] = []
    members: dict[object, list[int]] = {}
    for i, s in enumerate(labels):
        if s not in members:
            members[s] = []
            order.append(s)
        members[s].append(i)
    return [_Cluster(s, np.asarray(members[s])) for s in order]


# --- multilevel REML ----------------------------------------------------------------------------


@dataclass(frozen=True)
class MultilevelFit:
    """A fitted two-variance-component model. `sigma2` is `(top level, nested level)`."""

    sigma2: tuple[float, float]
    beta: tuple[float, ...]
    se: tuple[float, ...]
    vb: tuple[tuple[float, ...], ...]
    loglik: float
    k: int
    n_clusters: int
    columns: tuple[str, ...]
    rho: float
    working: tuple[np.ndarray, ...]  # the fitted marginal covariance of each cluster
    clusters: tuple[tuple[int, ...], ...]
    iterations: int

    def __hash__(self) -> int:  # arrays are not hashable; identity is enough
        return id(self)


def _design(x: Sequence[Sequence[float]] | None, n: int) -> np.ndarray:
    if x is None:
        return np.ones((n, 1))
    design = np.asarray(x, dtype=float)
    if design.ndim != 2 or design.shape[0] != n:
        raise DependenceError("the design matrix needs one row per effect")
    return design


def _blocks(
    v: np.ndarray, top: list[_Cluster], mid: Sequence[object], rho: float
) -> list[tuple[np.ndarray, np.ndarray, np.ndarray]]:
    """Per cluster: the sampling covariance and the top-level and nested-level indicators."""
    out = []
    for c in top:
        sd = np.sqrt(v[c.idx])
        sampling = rho * np.outer(sd, sd)
        np.fill_diagonal(sampling, v[c.idx])
        groups = [mid[i] for i in c.idx]
        nested = np.asarray([[1.0 if a == b else 0.0 for b in groups] for a in groups])
        out.append((sampling, np.ones((c.idx.size, c.idx.size)), nested))
    return out


def fit_multilevel(
    yi: Sequence[float],
    vi: Sequence[float],
    top: Sequence[object],
    nested: Sequence[object],
    *,
    rho: float = 0.0,
    x: Sequence[Sequence[float]] | None = None,
    columns: Sequence[str] | None = None,
) -> MultilevelFit:
    """REML fit of `y = X b + u_top + u_nested + e` with `Var(e) = V` (variances `v`, correlation
    `rho` between effects of the same `top` cluster).

    `nested` labels the unit sharing the second random effect within a cluster (each effect for the
    CHE model; each study for a district/study three-level model). Raises `DependenceError` when the
    optimiser fails; it never returns the last iterate.
    """
    y = np.asarray(yi, dtype=float)
    v = np.asarray(vi, dtype=float)
    n = y.size
    if not (v.size == n == len(top) == len(nested)) or n == 0:
        raise DependenceError("yi, vi, top and nested must be the same non-zero length")
    if not (np.all(np.isfinite(y)) and np.all(np.isfinite(v)) and np.all(v > 0)):
        raise DependenceError("every effect size must be finite and every variance positive")
    if not 0.0 <= rho < 1.0:
        raise DependenceError("rho must lie in [0, 1)")
    design = _design(x, n)
    p = design.shape[1]
    clusters = _clusters(top)
    if len(clusters) < 2:
        raise DependenceError("a multilevel model needs at least 2 clusters")
    if n <= p:
        raise DependenceError("a multilevel model needs more effects than parameters")
    blocks = _blocks(v, clusters, list(nested), rho)

    def components(theta: np.ndarray) -> tuple[list[np.ndarray], np.ndarray, np.ndarray, float]:
        sigmas = []
        a = np.zeros((p, p))
        b = np.zeros(p)
        logdet = 0.0
        for c, (sampling, ztop, zmid) in zip(clusters, blocks, strict=True):
            sigma = sampling + theta[0] * ztop + theta[1] * zmid
            sign, ld = np.linalg.slogdet(sigma)
            if sign <= 0:
                raise DependenceError("the marginal covariance is not positive definite")
            logdet += ld
            inv = np.linalg.inv(sigma)
            xj = design[c.idx]
            a += xj.T @ inv @ xj
            b += xj.T @ inv @ y[c.idx]
            sigmas.append(inv)
        return sigmas, a, b, logdet

    def objective(theta: np.ndarray) -> tuple[float, np.ndarray]:
        invs, a, b, logdet = components(theta)
        m = np.linalg.inv(a)
        beta = m @ b
        quad = 0.0
        grad = np.zeros(2)
        r_all = []
        for c, inv in zip(clusters, invs, strict=True):
            res = y[c.idx] - design[c.idx] @ beta
            r = inv @ res
            r_all.append(r)
            quad += float(res @ r)
        _sign, logdet_a = np.linalg.slogdet(a)
        value = 0.5 * (logdet + logdet_a + quad)
        for k_index in (0, 1):
            total = 0.0
            for c, inv, r, blk in zip(clusters, invs, r_all, blocks, strict=True):
                z = blk[1 + k_index]
                xj = design[c.idx]
                total += float(np.trace(inv @ z))
                total -= float(np.trace(m @ xj.T @ inv @ z @ inv @ xj))
                total -= float(r @ z @ r)
            grad[k_index] = 0.5 * total
        return value, grad

    start_scale = max(float(np.var(y)), 1e-8)
    best = None
    for shares in ((0.5, 0.5), (0.9, 0.1), (0.1, 0.9), (0.0, 0.5), (0.5, 0.0)):
        theta0 = np.asarray(shares) * start_scale
        try:
            res = optimize.minimize(
                lambda t: objective(t)[0],
                theta0,
                jac=lambda t: objective(t)[1],
                method="L-BFGS-B",
                bounds=[(0.0, None), (0.0, None)],
                options={"maxiter": 2000, "ftol": 1e-16, "gtol": 1e-13, "maxcor": 20},
            )
        except DependenceError:
            continue
        if best is None or res.fun < best.fun - 1e-12:
            best = res
    if best is None or not np.all(np.isfinite(best.x)):
        raise DependenceError("the REML fit of the multilevel model did not converge")
    theta = np.maximum(best.x, 0.0)
    # Polish: Newton steps on the strictly positive parameters, with a numerical Hessian.
    for _ in range(25):
        free = [i for i in (0, 1) if theta[i] > 1e-12]
        if not free:
            break
        _value, grad = objective(theta)
        step = 1e-6 * max(theta[free].max(), 1e-6)
        hess = np.zeros((len(free), len(free)))
        for a_i, i in enumerate(free):
            bump = theta.copy()
            bump[i] += step
            hess[a_i] = (objective(bump)[1][free] - grad[free]) / step
        hess = 0.5 * (hess + hess.T)
        try:
            delta = np.linalg.solve(hess, -grad[free])
        except np.linalg.LinAlgError:
            break
        trial = theta.copy()
        trial[free] = np.maximum(theta[free] + delta, 0.0)
        if objective(trial)[0] <= objective(theta)[0] + 1e-15:
            change = float(np.max(np.abs(trial - theta)))
            theta = trial
            if change < 1e-13:
                break
        else:
            break

    invs, a, b, logdet = components(theta)
    m = np.linalg.inv(a)
    beta = m @ b
    quad = 0.0
    for c, inv in zip(clusters, invs, strict=True):
        res = y[c.idx] - design[c.idx] @ beta
        quad += float(res @ inv @ res)
    _s, logdet_a = np.linalg.slogdet(a)
    _s, logdet_xx = np.linalg.slogdet(design.T @ design)
    loglik = (
        -0.5 * (n - p) * math.log(2 * math.pi)
        + 0.5 * logdet_xx
        - 0.5 * logdet
        - 0.5 * logdet_a
        - 0.5 * quad
    )
    working = tuple(blk[0] + theta[0] * blk[1] + theta[1] * blk[2] for blk in blocks)
    return MultilevelFit(
        (float(theta[0]), float(theta[1])),
        tuple(float(b_) for b_ in beta),
        tuple(float(s) for s in np.sqrt(np.diag(m))),
        tuple(tuple(float(c_) for c_ in row) for row in m),
        float(loglik),
        n,
        len(clusters),
        tuple(columns)
        if columns
        else (("intrcpt",) if p == 1 else tuple(f"x{i}" for i in range(p))),
        rho,
        working,
        tuple(tuple(int(i) for i in c.idx) for c in clusters),
        int(best.nit),
    )


# --- cluster-robust inference (CR2, Satterthwaite) ----------------------------------------------


@dataclass(frozen=True)
class RobustFit:
    beta: tuple[float, ...]
    se: tuple[float, ...]
    tval: tuple[float, ...]
    df: tuple[float, ...]
    pval: tuple[float, ...]
    ci_lb: tuple[float, ...]
    ci_ub: tuple[float, ...]
    n_clusters: int
    adjustment: str = "CR2"
    df_method: str = "Satterthwaite"


def _inv_sqrt(b: np.ndarray) -> np.ndarray:
    values, vectors = np.linalg.eigh(0.5 * (b + b.T))
    cutoff = max(values.max(), 0.0) * 1e-12
    inv = np.where(values > cutoff, 1.0 / np.sqrt(np.where(values > cutoff, values, 1.0)), 0.0)
    return (vectors * inv) @ vectors.T


def cluster_robust(
    yi: Sequence[float],
    clusters: Sequence[object],
    working: Sequence[np.ndarray],
    *,
    x: Sequence[Sequence[float]] | None = None,
    level: float = 0.95,
) -> RobustFit:
    """CR2 cluster-robust standard errors with Satterthwaite degrees of freedom.

    `working[j]` is the working covariance of cluster `j` (clusters in order of first appearance in
    `clusters`); coefficients are estimated by weighted least squares with its inverse. The working
    model is treated as the truth when computing degrees of freedom, as `clubSandwich` does.
    """
    y = np.asarray(yi, dtype=float)
    n = y.size
    design = _design(x, n)
    p = design.shape[1]
    parts = _clusters(clusters)
    if len(working) != len(parts):
        raise DependenceError("one working covariance block is needed per cluster")
    if len(parts) < 2:
        raise DependenceError("cluster-robust inference needs at least 2 clusters")
    for c, phi in zip(parts, working, strict=True):
        if phi.shape != (c.idx.size, c.idx.size):
            raise DependenceError("a working covariance block does not match its cluster size")
    winv = [np.linalg.inv(phi) for phi in working]
    a = sum(design[c.idx].T @ w @ design[c.idx] for c, w in zip(parts, winv, strict=True))
    m = np.linalg.inv(a)
    beta = m @ sum(design[c.idx].T @ w @ y[c.idx] for c, w in zip(parts, winv, strict=True))
    adjust = []
    for c, phi in zip(parts, working, strict=True):
        xj = design[c.idx]
        d = np.linalg.cholesky(phi).T  # phi = d.T @ d
        b = d @ (phi - xj @ m @ xj.T) @ d.T
        adjust.append(d.T @ _inv_sqrt(b) @ d)
    se, tval, dfs, pval, lb, ub = [], [], [], [], [], []
    crit_tail = (1.0 + level) / 2.0
    for coef in range(p):
        e = np.zeros(p)
        e[coef] = 1.0
        b_vecs = [
            adj @ w @ design[c.idx] @ m @ e for c, adj, w in zip(parts, adjust, winv, strict=True)
        ]
        variance = sum(
            float(bv @ (y[c.idx] - design[c.idx] @ beta)) ** 2
            for c, bv in zip(parts, b_vecs, strict=True)
        )
        s_vecs = [design[c.idx].T @ bv for c, bv in zip(parts, b_vecs, strict=True)]
        count = len(parts)
        k_mat = np.empty((count, count))
        for j in range(count):
            for l_ in range(count):
                k_mat[j, l_] = -float(s_vecs[j] @ m @ s_vecs[l_])
            k_mat[j, j] += float(b_vecs[j] @ working[j] @ b_vecs[j])
        trace = float(np.trace(k_mat))
        df = trace**2 / float(np.sum(k_mat**2))
        s = math.sqrt(variance)
        t_value = float(beta[coef]) / s
        crit = float(stats.t.ppf(crit_tail, df))
        se.append(s)
        tval.append(t_value)
        dfs.append(df)
        pval.append(float(2 * stats.t.sf(abs(t_value), df)))
        lb.append(float(beta[coef]) - crit * s)
        ub.append(float(beta[coef]) + crit * s)
    return RobustFit(
        tuple(float(b_) for b_ in beta), tuple(se), tuple(tval), tuple(dfs), tuple(pval),
        tuple(lb), tuple(ub), len(parts),
    )  # fmt: skip


def cluster_robust_random_effects(
    yi: Sequence[float],
    vi: Sequence[float],
    clusters: Sequence[object],
    tau2: float,
    *,
    x: Sequence[Sequence[float]] | None = None,
    level: float = 0.95,
) -> RobustFit:
    """CR2 around the ordinary random-effects model: independent working errors `v + tau^2`."""
    v = np.asarray(vi, dtype=float)
    parts = _clusters(clusters)
    working = [np.diag(v[c.idx] + tau2) for c in parts]
    return cluster_robust(yi, clusters, working, x=x, level=level)


def cluster_robust_multilevel(
    yi: Sequence[float],
    fit: MultilevelFit,
    clusters: Sequence[object],
    *,
    x: Sequence[Sequence[float]] | None = None,
    level: float = 0.95,
) -> RobustFit:
    """CR2 around a fitted multilevel model, clustered on the model's top level."""
    return cluster_robust(yi, clusters, fit.working, x=x, level=level)


def cluster_warnings(n_clusters: int, min_df: float) -> list[str]:
    """Named warnings for few clusters: below 20 warn, below 10 warn strongly, naming the df."""
    found = []
    if n_clusters < 10:
        found.append(
            f"dependence:cluster-robust:few-clusters-strong:clusters={n_clusters}:satterthwaite-df={min_df:.1f}"
        )
    elif n_clusters < 20:
        found.append(
            f"dependence:cluster-robust:few-clusters:clusters={n_clusters}:satterthwaite-df={min_df:.1f}"
        )
    return found
