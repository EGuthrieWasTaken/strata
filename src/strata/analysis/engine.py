"""The native analysis engine: from selected effect rows to pooled results, bias tests,
sensitivity analyses, sweeps, and guardrails (openspec:analysis-specification, pooling-models,
bias-and-sensitivity).

It is repository-free: `run_analysis` takes a validated `AnalysisSpec` and a `Selection` of rows and
returns plain data. Every number comes from `strata.stats` (validated against `metafor`); this
module only decides which model to fit, with what, and what to say about it.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from strata.analysis import guardrails
from strata.analysis.rows import EffectRow, RowError, Selection, compute_row, rows_by_filter
from strata.analysis.spec import R_SWEEP, RHO_SWEEP, AnalysisSpec
from strata.extract import effects as effects_mod
from strata.stats import bias as bias_mod
from strata.stats import diagnostics as diag_mod
from strata.stats import escalc as es
from strata.stats import models, robust


class AnalysisError(ValueError):
    """The analysis cannot be run as specified (a specific, actionable message)."""


@dataclass
class Unit:
    """One thing pooled: an effect, or a study's aggregated effect."""

    study_id: str
    effect_id: str
    label: str
    yi: float
    vi: float
    n: int | None
    year: int | None
    values: dict[str, Any]
    rows: list[EffectRow]


@dataclass
class EngineResult:
    estimates: dict[str, Any]
    units: list[Unit]
    weights: list[float]
    warnings: list[dict[str, Any]]
    forced: list[str] = field(default_factory=list)
    plot_data: dict[str, Any] = field(default_factory=dict)


# --- helpers ----------------------------------------------------------------------------------


def clean(value: Any) -> Any:
    """JSON-ready, platform-stable numbers: Python floats at 12 significant digits, no NaN/inf."""
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if isinstance(value, (np.floating, float)):
        number = float(value)
        return float(f"{number:.12g}") if math.isfinite(number) else None
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, np.bool_):
        return bool(value)
    return value


def _units_from_rows(rows: Sequence[EffectRow]) -> list[Unit]:
    return [
        Unit(r.study_id, r.effect_id, r.label, r.yi, r.vi, r.n, r.year, r.values(), [r])
        for r in rows
    ]


def _aggregate(rows: Sequence[EffectRow], rho: float) -> list[Unit]:
    merged = robust.aggregate_effects(
        [r.study_id for r in rows], [r.yi for r in rows], [r.vi for r in rows], rho
    )
    by_study: dict[str, list[EffectRow]] = {}
    for r in rows:
        by_study.setdefault(r.study_id, []).append(r)
    units = []
    for agg in merged:
        members = by_study[str(agg.study)]
        first = members[0]
        sizes = [r.n for r in members if r.n]
        units.append(
            Unit(
                first.study_id,
                f"{first.study_id}:aggregate" if len(members) > 1 else first.effect_id,
                first.label.split(" [")[0]
                + (f" ({len(members)} effects)" if len(members) > 1 else ""),
                agg.yi,
                agg.vi,
                max(sizes) if sizes else None,
                first.year,
                first.values(),
                members,
            )
        )
    return units


def _moderator_specs(spec: AnalysisSpec) -> list[models.ModeratorSpec]:
    return [
        models.ModeratorSpec(m["name"], m["type"], m.get("centering"), m.get("reference"))
        for m in spec.section("moderators")
    ]


def _usable(units: list[Unit], spec: AnalysisSpec, notes: dict[str, list[str]]) -> list[Unit]:
    """Drop units missing a declared moderator, and say which."""
    names = [m["name"] for m in spec.section("moderators")]
    kept = []
    for unit in units:
        missing = [n for n in names if unit.values.get(n) is None]
        if missing:
            notes.setdefault("missing moderator: " + ", ".join(missing), []).append(unit.effect_id)
        else:
            kept.append(unit)
    return kept


def _coefficients(fit: models.Fit) -> list[dict[str, Any]]:
    return [
        {
            "name": name,
            "estimate": fit.beta[i],
            "se": fit.se[i],
            "statistic": fit.stat[i],
            "df": fit.df,
            "p": fit.pval[i],
            "ci_lb": fit.ci_lb[i],
            "ci_ub": fit.ci_ub[i],
        }
        for i, name in enumerate(fit.columns)
    ]


def _fit_dict(fit: models.Fit) -> dict[str, Any]:
    het = fit.heterogeneity
    out: dict[str, Any] = {
        "model": fit.model,
        "k": fit.k,
        "coefficients": _coefficients(fit),
        "tau2": fit.tau2,
        "tau": math.sqrt(fit.tau2),
        "tau2_estimator": fit.tau2_method,
        "ci_method": fit.ci_method,
        "hk_truncation": fit.hk_truncation,
        "level": fit.level,
        "conventions": fit.conventions,
    }
    if het is not None:
        out["heterogeneity"] = {
            "Q": het.q,
            "Q_df": het.df,
            "Q_p": het.p,
            "I2": het.i2,
            "H2": het.h2,
            "tau2": het.tau2,
            "tau": het.tau,
            "tau2_ci": list(het.tau2_ci) if het.tau2_ci else None,
            "tau_ci": list(het.tau_ci) if het.tau_ci else None,
        }
    if fit.prediction is not None:
        out["prediction_interval"] = {
            "lb": fit.prediction.lb,
            "ub": fit.prediction.ub,
            "df": fit.prediction.df,
            "reason": fit.prediction.reason,
            "convention": "t distribution on k-2 degrees of freedom",
        }
    if fit.qm is not None:
        out["moderators"] = {
            "QM": fit.qm,
            "QM_df": list(fit.qm_df or ()),
            "QM_p": fit.qm_p,
            "R2": fit.r2,
        }
    return out


def _back_transformed(
    measure: str, estimate: float, lb: float, ub: float, sizes: list[int]
) -> dict[str, Any] | None:
    if measure == "PFT":
        harmonic = len(sizes) / sum(1 / s for s in sizes) if sizes else None
        if harmonic is None:
            return None
        values = [es.inverse_freeman_tukey(v, harmonic) for v in (estimate, lb, ub)]
        scale = "proportion"
    elif measure in ("ZCOR", "logOR", "logRR", "logHR", "PLO"):
        values = [es.back_transform(measure, v) for v in (estimate, lb, ub)]
        scale = {"ZCOR": "correlation", "PLO": "proportion"}.get(measure, "ratio")
    else:
        return None
    return {"scale": scale, "estimate": values[0], "ci_lb": values[1], "ci_ub": values[2]}


# --- the pooled model -------------------------------------------------------------------------


def _pool(
    units: list[Unit],
    spec: AnalysisSpec,
    handling: str,
    rho: float | None,
    rows: Sequence[EffectRow],
) -> tuple[dict[str, Any], list[float], list[str]]:
    """Fit the specified model to `units` (or to `rows` for the dependent-effects models).

    Returns the result dictionary, the plotting weights (percent), and warnings from the fit.
    """
    model, level = spec.section("model"), spec.section("model")["level"]
    notes: list[str] = []
    moderators = _moderator_specs(spec)
    use = units
    if handling in ("cluster-robust", "multilevel"):
        return _pool_dependent(spec, handling, rho or 0.0, list(rows))
    values = [u.values for u in use]
    yi, vi = [u.yi for u in use], [u.vi for u in use]
    if moderators:
        design = models.build_design(values, moderators)
        if model["type"] == "common-effect":
            fit = models.common_effect(yi, vi, x=design.matrix, columns=design.columns, level=level)
        else:
            fit = models.meta_regression(
                yi,
                vi,
                design,
                method=model["tau2_estimator"],
                ci_method=model["ci_method"],
                level=level,
            )
    elif model["type"] == "common-effect":
        fit = models.common_effect(yi, vi, level=level)
    else:
        fit = models.random_effects(
            yi, vi, method=model["tau2_estimator"], ci_method=model["ci_method"], level=level
        )
    out = _fit_dict(fit)
    out["warnings_from_fit"] = list(fit.warnings)
    tau2 = fit.tau2
    w = [1.0 / (v + tau2) for v in vi]
    total = sum(w)
    return out, [100.0 * x / total for x in w], notes


def _che_inputs(rows: Sequence[EffectRow]) -> tuple[list[float], list[float], list[str], list[int]]:
    return (
        [r.yi for r in rows],
        [r.vi for r in rows],
        [r.study_id for r in rows],
        list(range(len(rows))),
    )


def _pool_dependent(
    spec: AnalysisSpec, handling: str, rho: float, rows: list[EffectRow]
) -> tuple[dict[str, Any], list[float], list[str]]:
    level = spec.section("model")["level"]
    moderators = _moderator_specs(spec)
    yi, vi, study, effect = _che_inputs(rows)
    x = None
    columns: tuple[str, ...] | None = None
    if moderators:
        design = models.build_design([r.values() for r in rows], moderators)
        x, columns = design.matrix, design.columns
    fit = robust.fit_multilevel(yi, vi, study, effect, rho=rho, x=x, columns=columns)
    names = fit.columns
    out: dict[str, Any] = {
        "model": f"{handling} (correlated-and-hierarchical effects, REML)",
        "k": len(rows),
        "n_studies": fit.n_clusters,
        "variance_components": {"study": fit.sigma2[0], "effect": fit.sigma2[1]},
        "tau2": fit.sigma2[0] + fit.sigma2[1],
        "tau": math.sqrt(fit.sigma2[0] + fit.sigma2[1]),
        "rho": rho,
        "loglik": fit.loglik,
        "level": level,
        "conventions": {
            "working_model": (
                "CHE: study and effect random effects, sampling errors correlated at rho"
            ),
            "estimation": "REML",
        },
    }
    notes: list[str] = []
    if handling == "cluster-robust":
        cr = robust.cluster_robust_multilevel(yi, fit, study, x=x, level=level)
        out["coefficients"] = [
            {
                "name": n,
                "estimate": cr.beta[i],
                "se": cr.se[i],
                "statistic": cr.tval[i],
                "df": cr.df[i],
                "p": cr.pval[i],
                "ci_lb": cr.ci_lb[i],
                "ci_ub": cr.ci_ub[i],
            }
            for i, n in enumerate(names)
        ]
        out["ci_method"] = "CR2 cluster-robust, Satterthwaite df"
        out["clusters"] = {"n": cr.n_clusters, "min_df": min(cr.df)}
        notes.extend(robust.cluster_warnings(cr.n_clusters, min(cr.df)))
    else:
        from scipy import stats as scipy_stats

        crit = float(scipy_stats.norm.ppf((1 + level) / 2))
        out["coefficients"] = [
            {
                "name": n,
                "estimate": fit.beta[i],
                "se": fit.se[i],
                "statistic": fit.beta[i] / fit.se[i],
                "df": None,
                "p": float(2 * scipy_stats.norm.sf(abs(fit.beta[i] / fit.se[i]))),
                "ci_lb": fit.beta[i] - crit * fit.se[i],
                "ci_ub": fit.beta[i] + crit * fit.se[i],
            }
            for i, n in enumerate(names)
        ]
        out["ci_method"] = "Wald (z)"
    tau2 = out["tau2"]
    w = [1.0 / (v + tau2) for v in vi]
    total = sum(w)
    return out, [100.0 * x_ / total for x_ in w], notes


# --- main entry point -------------------------------------------------------------------------


def run_analysis(
    spec: AnalysisSpec,
    selection: Selection,
    *,
    force: bool = False,
    acknowledged: Iterable[str] = (),
) -> EngineResult:
    """Run `spec` over `selection`. Raises `guardrails.BlockingGuardrail` for a blocking guardrail
    unless `force`; raises `AnalysisError` for anything that cannot be computed."""
    rows = list(selection.rows)
    notes: dict[str, list[str]] = {}
    if not rows:
        raise AnalysisError(
            "no effects match this analysis (check effect_size.measure and include.filter)"
        )
    dependency = spec.section("dependency")
    studies = Counter(r.study_id for r in rows)
    multi = sorted(s for s, n in studies.items() if n > 1)
    handling = dependency.get("handling") or ("cluster-robust" if multi else "none")
    if multi and "handling" not in dependency:
        raise AnalysisError(
            f"{len(multi)} study(ies) contribute more than one effect; declare dependency.handling "
            "(aggregate, cluster-robust or multilevel) and dependency.rho, or none to pool them as "
            "independent (which raises a prominent warning)"
        )
    rho = dependency.get("rho")
    forced: list[str] = []
    warnings: list[dict[str, Any]] = []
    model = spec.section("model")

    # Units to pool.
    units = _aggregate(rows, rho) if handling == "aggregate" else _units_from_rows(rows)
    if spec.section("moderators"):
        usable = _usable(units, spec, notes)
        if handling in ("cluster-robust", "multilevel"):
            keep = {u.effect_id for u in usable}
            rows = [r for r in rows if r.effect_id in keep]
        units = usable
        for reason, ids in notes.items():
            selection.excluded.setdefault(reason, []).extend(ids)
    if not units:
        raise AnalysisError("no effects remain after removing those missing a declared moderator")

    sizes = [u.n for u in units if u.n]
    main, weights, fit_notes = _pool(units, spec, handling, rho, rows)
    estimates: dict[str, Any] = {
        "analysis": spec.id,
        "title": spec.title,
        "label": spec.label,
        "measure": spec.measure,
        "direction": spec.section("effect_size")["direction"],
        "k_effects": len(rows),
        "k_studies": len(studies),
        "k_pooled": len(units),
        "dependency": {"handling": handling, "rho": rho, "studies_with_multiple_effects": multi},
        "excluded": {reason: sorted(ids) for reason, ids in sorted(selection.excluded.items())},
        "pooled": main,
    }
    primary = main["coefficients"][0]
    transformed = _back_transformed(
        spec.measure, primary["estimate"], primary["ci_lb"], primary["ci_ub"], sizes
    )
    if transformed is not None:
        estimates["back_transformed"] = transformed
    n_double_zero = sum(len(ids) for why, ids in selection.excluded.items() if "double-zero" in why)
    estimates["double_zero_excluded"] = n_double_zero

    # Sweeps over assumptions.
    sweeps: dict[str, Any] = {}
    if handling in ("aggregate", "cluster-robust", "multilevel"):
        sweeps["rho"] = _rho_sweep(spec, rows, handling, rho)
    assumed = [r for r in rows if r.details.get("assumed_correlation") is not None]
    if assumed:
        sweeps["assumed_correlation"] = _correlation_sweep(spec, rows, handling, rho)
    if sweeps:
        estimates["sweeps"] = sweeps

    # Publication bias and small-study effects, on one effect per study.
    bias_units = units if handling in ("none", "aggregate") else _aggregate(rows, rho or 0.5)
    _bias(spec, bias_units, estimates, force, forced)

    # Sensitivity analyses.
    sensitivity = _sensitivity(
        spec,
        bias_units if handling not in ("none", "aggregate") else units,
        selection,
        rows,
        handling,
        rho,
    )
    if sensitivity:
        estimates["sensitivity"] = sensitivity

    # Guardrails.
    context = guardrails.Context(
        spec=spec,
        k=len(units),
        n_params=len(main["coefficients"]),
        i2=main.get("heterogeneity", {}).get("I2"),
        multi_effect_studies=multi,
        handling=handling,
        p_value_effects=[r.effect_id for r in rows if r.details.get("derived_from_pvalue")],
        assumed_correlation_effects=[r.effect_id for r in assumed],
        fit_warnings=[*main.get("warnings_from_fit", []), *fit_notes],
        freeman_tukey=es.freeman_tukey_warning([float(s) for s in sizes])
        if spec.measure == "PFT"
        else None,
        double_zero=n_double_zero,
        hk_truncated=bool(main.get("hk_truncation")),
        bias_requested=bool(set(spec.section("publication_bias")) & {"egger", "begg", "pet_peese"}),
        forced=forced,
    )
    warnings = guardrails.evaluate(context, set(acknowledged))
    estimates["warnings"] = [w["code"] for w in warnings]
    estimates["model"] = {
        "type": model["type"],
        "tau2_estimator": model["tau2_estimator"],
        "ci_method": main.get("ci_method"),
        "level": model["level"],
    }
    return EngineResult(
        clean(estimates),
        units,
        weights,
        warnings,
        forced,
        {"handling": handling, "rho": rho, "fit": main},
    )


# --- bias -------------------------------------------------------------------------------------


def _bias(
    spec: AnalysisSpec, units: list[Unit], estimates: dict[str, Any], force: bool, forced: list[str]
) -> None:
    requested = spec.section("publication_bias")
    if not requested:
        return
    yi, vi = [u.yi for u in units], [u.vi for u in units]
    k = len(units)
    out: dict[str, Any] = {
        "k": k,
        "note": "small-study-effect tests are not corrections for publication bias",
    }
    method = spec.section("model")["tau2_estimator"]

    def guarded(name: str) -> bool:
        under = bias_mod.require_adequate_studies(k, name, force=force)  # raises when blocked
        if under:
            forced.append(name)
        return under

    try:
        if "egger" in requested:
            under = guarded("Egger's test")
            counts = _binary_counts(units) if spec.measure == "logOR" else None
            if counts is not None:
                result = bias_mod.harbord(*counts)
                out["egger"] = {**_test_dict(result), "used": "harbord (log odds ratio)"}
            else:
                result = bias_mod.egger(yi, vi)
                out["egger"] = {**_test_dict(result), "used": "egger"}
            out["egger"]["forced_underpowered"] = under
        if "begg" in requested:
            under = guarded("Begg's rank correlation")
            result = bias_mod.begg(yi, vi)
            out["begg"] = {**_test_dict(result), "forced_underpowered": under}
        if "pet_peese" in requested:
            under = guarded("PET-PEESE")
            pp = bias_mod.pet_peese(yi, vi)
            out["pet_peese"] = {
                "selected": pp.selected,
                "estimate": pp.estimate,
                "se": pp.se,
                "pet": _line_dict(pp.pet),
                "peese": _line_dict(pp.peese),
                "pet_p_one_tailed": pp.pet_p_one_tailed,
                "label": pp.label,
                "interpretation": bias_mod.describe(pp),
                "forced_underpowered": under,
            }
        if "trim_fill" in requested and k >= 2:
            tf = bias_mod.trim_and_fill(yi, vi, method=method)
            out["trim_fill"] = {
                "estimator": tf.estimator,
                "side": tf.side,
                "k0": tf.k0,
                "estimate_original": tf.estimate_original,
                "estimate": tf.estimate,
                "se": tf.se,
                "label": tf.label,
                "interpretation": bias_mod.describe(tf),
                "filled": [
                    {"yi": a, "vi": b} for a, b in zip(tf.filled_yi, tf.filled_vi, strict=True)
                ],
            }
    except bias_mod.UnderpoweredError as exc:
        raise guardrails.BlockingGuardrail("k-lt-10-bias-tests", str(exc)) from None
    except bias_mod.BiasMethodError as exc:
        out["error"] = str(exc)
    if "funnel" in requested:
        out["funnel"] = {"contour_enhanced": True, "contours": [0.10, 0.05, 0.01]}
    estimates["publication_bias"] = out


def _test_dict(result: bias_mod.SmallStudyTest) -> dict[str, Any]:
    return {
        "method": result.method,
        "k": result.k,
        "bias": result.bias,
        "bias_se": result.bias_se,
        "statistic": result.statistic,
        "df": result.df,
        "p": result.p,
        "interpretation": result.interpretation,
    }


def _line_dict(line: bias_mod.Line) -> dict[str, Any]:
    return {
        "intercept": line.intercept,
        "intercept_se": line.intercept_se,
        "intercept_p": line.intercept_p,
        "slope": line.slope,
        "slope_se": line.slope_se,
        "slope_p": line.slope_p,
        "df": line.df,
    }


def _binary_counts(
    units: list[Unit],
) -> tuple[list[float], list[float], list[float], list[float]] | None:
    """Per-study event counts for Harbord's test; `None` unless every unit is one 2x2 effect."""
    cols: tuple[list[float], list[float], list[float], list[float]] = ([], [], [], [])
    for unit in units:
        if len(unit.rows) != 1 or unit.rows[0].design != "two-group-binary":
            return None
        inputs = unit.rows[0].inputs
        for column, name in zip(cols, ("events1", "n1", "events2", "n2"), strict=True):
            column.append(float(inputs[name]))
    return cols


# --- sweeps -----------------------------------------------------------------------------------


def _summary(result: dict[str, Any]) -> dict[str, Any]:
    first = result["coefficients"][0]
    return {
        "estimate": first["estimate"],
        "se": first["se"],
        "ci_lb": first["ci_lb"],
        "ci_ub": first["ci_ub"],
        "tau2": result.get("tau2"),
    }


def _rho_sweep(
    spec: AnalysisSpec, rows: list[EffectRow], handling: str, primary: float | None
) -> dict[str, Any]:
    out = []
    for rho in RHO_SWEEP:
        if handling == "aggregate":
            units = _aggregate(rows, rho)
            result, _w, _n = _pool(units, spec, "aggregate", rho, rows)
        else:
            result, _w, _n = _pool_dependent(spec, handling, rho, rows)
        out.append({"rho": rho, **_summary(result)})
    return {
        "values": out,
        "primary": primary,
        "note": "the assumed within-study correlation is swept automatically",
    }


def _correlation_sweep(
    spec: AnalysisSpec, rows: list[EffectRow], handling: str, rho: float | None
) -> dict[str, Any]:
    out = []
    for r in R_SWEEP:
        swept: list[EffectRow] = []
        for row in rows:
            if row.details.get("assumed_correlation") is None:
                swept.append(row)
                continue
            try:
                computed = compute_row(row.design, row.inputs, override_correlation=r)
            except (effects_mod.EffectInputError, es.EffectSizeError) as exc:
                raise AnalysisError(f"cannot recompute {row.effect_id} at r = {r}: {exc}") from None
            clone = EffectRow(**{**row.__dict__, "yi": computed.yi, "vi": computed.vi})
            swept.append(clone)
        units = (
            _aggregate(swept, rho or 0.5) if handling == "aggregate" else _units_from_rows(swept)
        )
        result, _w, _n = _pool(units, spec, handling, rho, swept)
        out.append({"r": r, **_summary(result)})
    return {
        "values": out,
        "note": "the pre-post correlation was assumed; the result is shown at r = 0.3, 0.5, 0.7",
    }


# --- sensitivity ------------------------------------------------------------------------------


def _sensitivity(
    spec: AnalysisSpec,
    units: list[Unit],
    selection: Selection,
    rows: list[EffectRow],
    handling: str,
    rho: float | None,
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    model = spec.section("model")
    method, ci = model["tau2_estimator"], model["ci_method"]
    level = model["level"]
    yi, vi = [u.yi for u in units], [u.vi for u in units]
    for item in spec.section("sensitivity"):
        kind, ident = item["type"], item["id"]
        try:
            if kind == "leave_one_out":
                results = diag_mod.leave_one_out(yi, vi, method=method, ci_method=ci, level=level)
                out[ident] = {
                    "type": kind,
                    "results": [
                        {
                            "omitted": units[r.omitted].effect_id,
                            "label": units[r.omitted].label,
                            "estimate": r.estimate,
                            "se": r.se,
                            "ci_lb": r.ci_lb,
                            "ci_ub": r.ci_ub,
                            "tau2": r.tau2,
                            "I2": r.i2,
                        }
                        for r in results
                    ],
                }
            elif kind == "influence_diagnostics":
                infl = diag_mod.influence_diagnostics(
                    yi, vi, method=method, ci_method=ci, level=level
                )
                out[ident] = {
                    "type": kind,
                    "note": "studies are flagged, never removed",
                    "results": [
                        {
                            "effect_id": u.effect_id,
                            "label": u.label,
                            "rstudent": r.rstudent,
                            "dffits": r.dffits,
                            "cook_d": r.cook_d,
                            "cov_r": r.cov_r,
                            "tau2_del": r.tau2_del,
                            "QE_del": r.qe_del,
                            "hat": r.hat,
                            "weight": r.weight,
                            "flags": list(r.flags),
                        }
                        for u, r in zip(units, infl, strict=True)
                    ],
                }
            elif kind == "cumulative":
                key = item.get("order") or "year"
                order = _order(units, key)
                cumulative = diag_mod.cumulative(
                    yi, vi, order, method=method, ci_method=ci, level=level
                )
                out[ident] = {
                    "type": kind,
                    "order_by": key,
                    "results": [
                        {
                            "added": units[c.study].effect_id,
                            "label": units[c.study].label,
                            "estimate": c.estimate,
                            "se": c.se,
                            "ci_lb": c.ci_lb,
                            "ci_ub": c.ci_ub,
                            "tau2": c.tau2,
                            "k": c.k,
                        }
                        for c in cumulative
                    ],
                }
            else:  # subset
                subset_rows = rows_by_filter(rows, item["filter"])
                if not subset_rows:
                    out[ident] = {
                        "type": kind,
                        "filter": item["filter"],
                        "k": 0,
                        "error": "no effects match",
                    }
                    continue
                subset_units = (
                    _aggregate(subset_rows, rho or 0.5)
                    if handling == "aggregate"
                    else _units_from_rows(subset_rows)
                )
                result, _w, _n = _pool(subset_units, spec, handling, rho, subset_rows)
                out[ident] = {
                    "type": kind,
                    "filter": item["filter"],
                    "k": len(subset_units),
                    "pooled": result,
                }
        except (diag_mod.DiagnosticsError, models.ModelError, robust.DependenceError) as exc:
            out[ident] = {"type": kind, "error": str(exc)}
        except RowError as exc:
            raise AnalysisError(f"sensitivity {ident!r}: {exc}") from None
    return out


def _order(units: list[Unit], key: str) -> list[int]:
    values = [u.values.get(key) for u in units]
    if any(v is None for v in values):
        raise AnalysisError(
            f"cumulative meta-analysis cannot order by {key!r}: it is missing for some effects"
        )
    return sorted(range(len(units)), key=lambda i: (values[i], i))


def check_analysis(
    spec: AnalysisSpec, selection: Selection, acknowledged: Iterable[str] = ()
) -> list[dict[str, Any]]:
    """The guardrails that can be known from the specification and the selected rows alone, without
    fitting anything (`strata analyze --check`)."""
    rows = selection.rows
    studies = Counter(r.study_id for r in rows)
    multi = sorted(s for s, n in studies.items() if n > 1)
    handling = spec.section("dependency").get("handling") or ("cluster-robust" if multi else "none")
    assumed = [r.effect_id for r in rows if r.details.get("assumed_correlation") is not None]
    context = guardrails.Context(
        spec=spec,
        k=len(studies) if handling != "none" else len(rows),
        n_params=1 + len(spec.section("moderators")),
        i2=None,
        multi_effect_studies=multi,
        handling=handling,
        p_value_effects=[r.effect_id for r in rows if r.details.get("derived_from_pvalue")],
        assumed_correlation_effects=assumed,
        fit_warnings=[],
        freeman_tukey=None,
        double_zero=sum(
            len(ids) for why, ids in selection.excluded.items() if "double-zero" in why
        ),
        hk_truncated=False,
        bias_requested=bool(set(spec.section("publication_bias")) & {"egger", "begg", "pet_peese"}),
    )
    return guardrails.evaluate(context, set(acknowledged))
