"""Forest, funnel, Baujat and bubble plots from a finished analysis
(openspec:analysis-plots).

Plots are drawn on the canvas layer (`strata.stats.canvas`), so they are deterministic SVG (or PDF)
with content-derived ids, a colour-blind-safe palette in light and dark, and shapes/dashes/labels
that never rely on colour alone. The values behind every plot are in `studies.tsv`.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np

from strata.analysis.engine import EngineResult, Unit
from strata.analysis.spec import AnalysisSpec
from strata.stats import canvas as cv
from strata.stats import models

FORMATS = ("svg", "pdf", "png")
LOG_MEASURES = ("logOR", "logRR", "logHR")


class PlotError(ValueError):
    """A plot cannot be drawn (or its output format is unavailable)."""


# --- scales -----------------------------------------------------------------------------------


class _Scale:
    def __init__(self, lo: float, hi: float, a: float, b: float) -> None:
        if hi == lo:
            lo, hi = lo - 0.5, hi + 0.5
        self.lo, self.hi, self.a, self.b = lo, hi, a, b

    def __call__(self, v: float) -> float:
        return self.a + (v - self.lo) / (self.hi - self.lo) * (self.b - self.a)


def _nice_ticks(lo: float, hi: float, count: int = 5) -> list[float]:
    span = hi - lo
    raw = span / max(count, 1)
    magnitude = 10 ** math.floor(math.log10(raw)) if raw > 0 else 1.0
    for step in (1, 2, 2.5, 5, 10):
        if step * magnitude >= raw:
            unit = step * magnitude
            break
    start = math.ceil(lo / unit - 1e-9) * unit
    ticks = []
    value = start
    while value <= hi + 1e-9:
        ticks.append(round(value, 10))
        value += unit
    return ticks


def _tick_label(measure: str, value: float) -> str:
    shown = math.exp(value) if measure in LOG_MEASURES else value
    return cv.fmt(round(shown, 2))


def _est(measure: str, value: float) -> str:
    shown = math.exp(value) if measure in LOG_MEASURES else value
    return f"{shown:.2f}"


def _width(text: str, size: float) -> float:
    return 0.5 * size * len(text)


# --- forest -----------------------------------------------------------------------------------


def forest(spec: AnalysisSpec, result: EngineResult) -> cv.Canvas:
    measure = spec.measure
    units, weights = result.units, result.weights
    pooled = result.estimates["pooled"]
    coefficient = pooled["coefficients"][0]
    level = spec.section("model")["level"]
    from scipy import stats

    crit = float(stats.norm.ppf((1 + level) / 2))
    row_h, top, left = 20.0, 56.0, 10.0
    plot_l, plot_r = 300.0, 520.0
    groups = _subgroups(spec, result)
    extra_rows = 3 + sum(1 + 1 for _ in groups)
    rows_n = len(units) + extra_rows
    height = top + rows_n * row_h + 80
    width = 760.0
    title = f"Forest plot: {spec.title}"
    desc = (
        f"Forest plot of {len(units)} effects ({measure}) with the pooled estimate "
        f"{_est(measure, coefficient['estimate'])}"
        + (
            " and a prediction interval"
            if pooled.get("prediction_interval", {}).get("lb") is not None
            else ""
        )
        + "."
    )
    canvas = cv.Canvas(width, height, title, desc)
    lows = [u.yi - crit * math.sqrt(u.vi) for u in units]
    highs = [u.yi + crit * math.sqrt(u.vi) for u in units]
    pi = pooled.get("prediction_interval") or {}
    lo = min([*lows, coefficient["ci_lb"], *([pi["lb"]] if pi.get("lb") is not None else [])])
    hi = max([*highs, coefficient["ci_ub"], *([pi["ub"]] if pi.get("ub") is not None else [])])
    pad = 0.05 * (hi - lo or 1.0)
    scale = _Scale(lo - pad, hi + pad, plot_l, plot_r)
    null = scale(0.0) if scale.lo <= 0.0 <= scale.hi else None

    canvas.add(cv.Text(left, 18, title, "ink", size=13, bold=True))
    if not spec.preregistered:
        canvas.add(cv.Text(left, 34, "Exploratory analysis", "accent2", size=10, bold=True))
    header_y = top - 8
    canvas.add(
        cv.Text(left, header_y, "Study", "muted", size=10, bold=True),
        cv.Text(plot_l - 30, header_y, "n", "muted", size=10, bold=True, anchor="end"),
        cv.Text(
            plot_r + 12, header_y, f"{measure_label(measure)} [CI]", "muted", size=10, bold=True
        ),
        cv.Text(width - 10, header_y, "Weight", "muted", size=10, bold=True, anchor="end"),
    )
    max_w = max(weights) if weights else 1.0
    y = top + row_h / 2
    for unit, w, a, b in zip(units, weights, lows, highs, strict=True):
        half = 2.0 + 5.0 * math.sqrt(w / max_w)
        x = scale(unit.yi)
        canvas.add(
            cv.Text(left, y + 4, _clip(unit.label, 38), "ink", size=10),
            cv.Text(
                plot_l - 30,
                y + 4,
                "" if unit.n is None else str(unit.n),
                "muted",
                size=10,
                anchor="end",
            ),
            cv.Line(scale(a), y, scale(b), y, "ink"),
            cv.Rect(x - half, y - half, 2 * half, 2 * half, "accent"),
            cv.Text(
                plot_r + 12,
                y + 4,
                f"{_est(measure, unit.yi)} [{_est(measure, a)}, {_est(measure, b)}]",
                "ink",
                size=10,
            ),
            cv.Text(width - 10, y + 4, f"{w:.1f}%", "muted", size=10, anchor="end"),
        )
        y += row_h
    y += row_h / 2
    for name, summary in groups:
        canvas.add(cv.Text(left, y + 4, name, "ink", size=10, bold=True))
        y += row_h
        y = _diamond_row(canvas, scale, y, f"  {name} pooled", summary, measure, plot_r, width)
    y = _diamond_row(
        canvas,
        scale,
        y,
        "Pooled",
        (coefficient["estimate"], coefficient["ci_lb"], coefficient["ci_ub"]),
        measure,
        plot_r,
        width,
    )
    if pi.get("lb") is not None:
        mid = scale(coefficient["estimate"])
        x1, x2 = scale(pi["lb"]), scale(pi["ub"])
        canvas.add(
            cv.Text(left, y + 4, "Prediction interval", "ink", size=10),
            cv.Rect(x1, y - 5, x2 - x1, 10, "band"),
            cv.Rect(x1, y - 5, x2 - x1, 10, "accent", fill=False),
            cv.Line(mid, y - 7, mid, y + 7, "accent"),
            cv.Text(
                plot_r + 12,
                y + 4,
                f"[{_est(measure, pi['lb'])}, {_est(measure, pi['ub'])}]",
                "ink",
                size=10,
            ),
        )
        y += row_h
    axis_y = y + 4
    canvas.add(cv.Line(plot_l, axis_y, plot_r, axis_y, "ink"))
    for tick in _nice_ticks(scale.lo, scale.hi):
        canvas.add(
            cv.Line(scale(tick), axis_y, scale(tick), axis_y + 4, "ink"),
            cv.Text(
                scale(tick),
                axis_y + 16,
                _tick_label(measure, tick),
                "muted",
                size=9,
                anchor="middle",
            ),
        )
    if null is not None:
        canvas.add(cv.Line(null, top, null, axis_y, "muted", dash=True))
    het = pooled.get("heterogeneity")
    footer = f"k = {result.estimates['k_pooled']}"
    if het:
        p = het["Q_p"]
        footer += (
            f"; tau = {het['tau']:.3f}; I2 = {het['I2']:.1f}%; Q({het['Q_df']}) = {het['Q']:.2f}, "
            f"p = {_p_text(p)}"
        )
    canvas.add(cv.Text(left, axis_y + 38, footer, "muted", size=10))
    return canvas


def _p_text(p: float | None) -> str:
    if p is None:
        return "n/a"
    return "<0.001" if p < 0.001 else f"{p:.3f}"


def measure_label(measure: str) -> str:
    return {"logOR": "OR", "logRR": "RR", "logHR": "HR", "ZCOR": "z"}.get(measure, measure)


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "..."


def _diamond_row(
    canvas: cv.Canvas,
    scale: _Scale,
    y: float,
    label: str,
    summary: tuple[float, float, float],
    measure: str,
    plot_r: float,
    width: float,
) -> float:
    est, lb, ub = summary
    canvas.add(
        cv.Text(10, y + 4, label, "ink", size=10, bold=True),
        cv.Polygon(
            ((scale(lb), y), (scale(est), y - 7), (scale(ub), y), (scale(est), y + 7)), "accent2"
        ),
        cv.Text(
            plot_r + 12,
            y + 4,
            f"{_est(measure, est)} [{_est(measure, lb)}, {_est(measure, ub)}]",
            "ink",
            size=10,
            bold=True,
        ),
    )
    return y + 20.0


def _subgroups(
    spec: AnalysisSpec, result: EngineResult
) -> list[tuple[str, tuple[float, float, float]]]:
    """Per-level pooled estimates for the first categorical moderator, if one is declared."""
    categorical = [m for m in spec.section("moderators") if m["type"] == "categorical"]
    if not categorical:
        return []
    name = categorical[0]["name"]
    model = spec.section("model")
    out = []
    levels: dict[str, list[Unit]] = {}
    for unit in result.units:
        levels.setdefault(str(unit.values.get(name)), []).append(unit)
    for level_name in sorted(levels):
        members = levels[level_name]
        if len(members) < 2:
            continue
        try:
            fit = models.random_effects(
                [u.yi for u in members],
                [u.vi for u in members],
                method=model["tau2_estimator"],
                ci_method=model["ci_method"],
                level=model["level"],
            )
        except models.ModelError:
            continue
        out.append((f"{name} = {level_name}", (fit.beta[0], fit.ci_lb[0], fit.ci_ub[0])))
    return out


# --- funnel -----------------------------------------------------------------------------------


def funnel(spec: AnalysisSpec, result: EngineResult) -> cv.Canvas:
    measure = spec.measure
    units = result.units
    est = result.estimates["pooled"]["coefficients"][0]["estimate"]
    se = [math.sqrt(u.vi) for u in units]
    max_se = max(se) * 1.1
    half = max(abs(u.yi - est) for u in units)
    half = max(half, 2.6 * max_se * 0.5, 1e-6) * 1.05
    left, top, width, height = 70.0, 50.0, 560.0, 440.0
    plot_w, plot_h = width - left - 30, height - top - 60
    x = _Scale(est - half, est + half, left, left + plot_w)
    y = _Scale(0.0, max_se, top, top + plot_h)
    canvas = cv.Canvas(
        width,
        height,
        f"Funnel plot: {spec.title}",
        f"Contour-enhanced funnel plot of {len(units)} effects ({measure}); the vertical line "
        "is the "
        "pooled estimate and the shaded regions mark p < .10, .05 and .01 around no effect.",
    )
    canvas.add(cv.Text(10, 18, f"Funnel plot: {spec.title}", "ink", size=13, bold=True))
    contour = (
        result.estimates.get("publication_bias", {})
        .get("funnel", {})
        .get("contours", [0.10, 0.05, 0.01])
    )
    z_values = [1.6448536269514722, 1.959963984540054, 2.5758293035489004]
    tints = ["tint1", "tint2", "tint3"]
    # Regions where |yi / se| exceeds each threshold around no effect, widest tint first.
    for z, tint in zip(z_values, tints, strict=True):
        pts_r = ((x(0.0), y(0.0)), (x(z * max_se), y(max_se)), (x.b, y(max_se)), (x.b, y(0.0)))
        pts_l = ((x(0.0), y(0.0)), (x(-z * max_se), y(max_se)), (x.a, y(max_se)), (x.a, y(0.0)))
        canvas.add(
            cv.Polygon(tuple((min(max(px, x.a), x.b), py) for px, py in pts_r), tint),
            cv.Polygon(tuple((min(max(px, x.a), x.b), py) for px, py in pts_l), tint),
        )
    # Pseudo confidence limits around the pooled estimate.
    canvas.add(
        cv.Polygon(
            (
                (x(est), y(0.0)),
                (x(est - 1.959964 * max_se), y(max_se)),
                (x(est + 1.959964 * max_se), y(max_se)),
            ),
            "ink",
            fill=False,
        ),
        cv.Line(x(est), y(0.0), x(est), y(max_se), "accent2", width=1.5),
    )
    if x.lo <= 0.0 <= x.hi:
        canvas.add(cv.Line(x(0.0), y(0.0), x(0.0), y(max_se), "muted", dash=True))
    for unit, s in zip(units, se, strict=True):
        canvas.add(
            cv.Circle(x(unit.yi), y(s), 3.5, "accent"),
            cv.Circle(x(unit.yi), y(s), 3.5, "ink", fill=False),
        )
    axis_y = top + plot_h
    canvas.add(
        cv.Line(left, axis_y, left + plot_w, axis_y, "ink"), cv.Line(left, top, left, axis_y, "ink")
    )
    for tick in _nice_ticks(x.lo, x.hi):
        canvas.add(
            cv.Line(x(tick), axis_y, x(tick), axis_y + 4, "ink"),
            cv.Text(
                x(tick), axis_y + 16, _tick_label(measure, tick), "muted", size=9, anchor="middle"
            ),
        )
    for tick in _nice_ticks(0.0, max_se, 4):
        canvas.add(
            cv.Line(left - 4, y(tick), left, y(tick), "ink"),
            cv.Text(left - 8, y(tick) + 3, cv.fmt(round(tick, 3)), "muted", size=9, anchor="end"),
        )
    canvas.add(
        cv.Text(
            left + plot_w / 2, height - 20, measure_label(measure), "ink", size=10, anchor="middle"
        ),
        cv.Text(
            18, top + plot_h / 2, "Standard error", "ink", size=10, anchor="middle", rotate=-90
        ),
        cv.Text(
            left,
            height - 6,
            "Shaded regions: p < .10, p < .05, p < .01 (light to dark); "
            f"contours {', '.join(str(c) for c in contour)}.",
            "muted",
            size=9,
        ),
    )
    return canvas


# --- Baujat -----------------------------------------------------------------------------------


def baujat(spec: AnalysisSpec, result: EngineResult) -> cv.Canvas:
    units = result.units
    yi = np.asarray([u.yi for u in units])
    vi = np.asarray([u.vi for u in units])
    w = 1.0 / vi
    mu = float(np.sum(w * yi) / np.sum(w))
    contribution = (yi - mu) ** 2 / vi
    influence = []
    for i in range(len(units)):
        keep = np.arange(len(units)) != i
        mu_i = float(np.sum(w[keep] * yi[keep]) / np.sum(w[keep]))
        var_i = 1.0 / float(np.sum(w[keep]))
        influence.append((mu - mu_i) ** 2 / var_i)
    left, top, width, height = 70.0, 50.0, 520.0, 420.0
    plot_w, plot_h = width - left - 30, height - top - 60
    x = _Scale(0.0, float(contribution.max()) * 1.1 or 1.0, left, left + plot_w)
    y = _Scale(0.0, max(influence) * 1.1 or 1.0, top + plot_h, top)
    canvas = cv.Canvas(
        width,
        height,
        f"Baujat plot: {spec.title}",
        f"Baujat plot of {len(units)} effects: contribution to heterogeneity (x) against "
        "influence on the pooled estimate (y).",
    )
    canvas.add(cv.Text(10, 18, f"Baujat plot: {spec.title}", "ink", size=13, bold=True))
    axis_y = top + plot_h
    canvas.add(
        cv.Line(left, axis_y, left + plot_w, axis_y, "ink"), cv.Line(left, top, left, axis_y, "ink")
    )
    for tick in _nice_ticks(0.0, x.hi):
        canvas.add(
            cv.Line(x(tick), axis_y, x(tick), axis_y + 4, "ink"),
            cv.Text(x(tick), axis_y + 16, cv.fmt(tick), "muted", size=9, anchor="middle"),
        )
    for tick in _nice_ticks(0.0, y.hi, 4):
        canvas.add(
            cv.Line(left - 4, y(tick), left, y(tick), "ink"),
            cv.Text(left - 8, y(tick) + 3, cv.fmt(tick), "muted", size=9, anchor="end"),
        )
    for i, (cx, cy) in enumerate(zip(contribution, influence, strict=True), start=1):
        canvas.add(
            cv.Polygon(
                (
                    (x(float(cx)), y(cy) - 5),
                    (x(float(cx)) + 5, y(cy) + 4),
                    (x(float(cx)) - 5, y(cy) + 4),
                ),
                "accent",
            ),
            cv.Text(x(float(cx)) + 7, y(cy) - 4, str(i), "ink", size=9),
        )
    canvas.add(
        cv.Text(
            left + plot_w / 2,
            height - 20,
            "Contribution to overall heterogeneity",
            "ink",
            size=10,
            anchor="middle",
        ),
        cv.Text(
            18,
            top + plot_h / 2,
            "Influence on the pooled estimate",
            "ink",
            size=10,
            anchor="middle",
            rotate=-90,
        ),
        cv.Text(left, height - 6, "Numbers are the rows of studies.tsv.", "muted", size=9),
    )
    return canvas


# --- bubble -----------------------------------------------------------------------------------


def bubble(spec: AnalysisSpec, result: EngineResult) -> cv.Canvas:
    continuous = [m for m in spec.section("moderators") if m["type"] == "continuous"]
    if not continuous:
        raise PlotError("a bubble plot needs a continuous moderator in the analysis specification")
    name = continuous[0]["name"]
    units = result.units
    xs = [float(u.values[name]) for u in units]
    ys = [u.yi for u in units]
    model = spec.section("model")
    fit = models.meta_regression(
        ys,
        [u.vi for u in units],
        models.build_design([{name: v} for v in xs], [models.ModeratorSpec(name, "continuous")]),
        method=model["tau2_estimator"],
        ci_method=model["ci_method"],
        level=model["level"],
    )
    left, top, width, height = 70.0, 50.0, 560.0, 440.0
    plot_w, plot_h = width - left - 30, height - top - 60
    lo_x, hi_x = min(xs), max(xs)
    span = (hi_x - lo_x) or 1.0
    grid = [lo_x - 0.05 * span + i * 1.1 * span / 40 for i in range(41)]
    band = []
    for g in grid:
        vec = np.array([1.0, g])
        fitted = float(vec @ np.asarray(fit.beta))
        se = float(np.sqrt(vec @ np.asarray(fit.vb) @ vec))
        crit = 1.96 if fit.df is None else _t_crit(fit.df, fit.level)
        band.append((g, fitted, fitted - crit * se, fitted + crit * se))
    lo_y = min(min(ys), min(b[2] for b in band))
    hi_y = max(max(ys), max(b[3] for b in band))
    pad_y = 0.05 * ((hi_y - lo_y) or 1.0)
    x = _Scale(grid[0], grid[-1], left, left + plot_w)
    y = _Scale(lo_y - pad_y, hi_y + pad_y, top + plot_h, top)
    canvas = cv.Canvas(
        width,
        height,
        f"Bubble plot: {spec.title}",
        f"Bubble plot of effect size against {name}; bubble area is proportional to weight, "
        "with the fitted line and its confidence band.",
    )
    canvas.add(cv.Text(10, 18, f"Bubble plot: {spec.title}", "ink", size=13, bold=True))
    upper = tuple((x(g), y(u)) for g, _f, _l, u in band)
    lower = tuple((x(g), y(lo)) for g, _f, lo, _u in reversed(band))
    canvas.add(cv.Polygon(upper + lower, "band"), cv.Polygon(upper + lower, "accent", fill=False))
    canvas.add(
        cv.Line(x(band[0][0]), y(band[0][1]), x(band[-1][0]), y(band[-1][1]), "accent2", width=2)
    )
    axis_y = top + plot_h
    canvas.add(
        cv.Line(left, axis_y, left + plot_w, axis_y, "ink"), cv.Line(left, top, left, axis_y, "ink")
    )
    for tick in _nice_ticks(x.lo, x.hi):
        canvas.add(
            cv.Line(x(tick), axis_y, x(tick), axis_y + 4, "ink"),
            cv.Text(x(tick), axis_y + 16, cv.fmt(tick), "muted", size=9, anchor="middle"),
        )
    for tick in _nice_ticks(y.lo, y.hi, 5):
        canvas.add(
            cv.Line(left - 4, y(tick), left, y(tick), "ink"),
            cv.Text(
                left - 8,
                y(tick) + 3,
                _tick_label(spec.measure, tick),
                "muted",
                size=9,
                anchor="end",
            ),
        )
    max_w = max(result.weights)
    for unit, xv, w in zip(units, xs, result.weights, strict=True):
        r = 3.0 + 14.0 * math.sqrt(w / max_w)
        canvas.add(
            cv.Circle(x(xv), y(unit.yi), r, "accent"),
            cv.Circle(x(xv), y(unit.yi), r, "ink", fill=False),
        )
    canvas.add(
        cv.Text(left + plot_w / 2, height - 20, name, "ink", size=10, anchor="middle"),
        cv.Text(
            18,
            top + plot_h / 2,
            measure_label(spec.measure),
            "ink",
            size=10,
            anchor="middle",
            rotate=-90,
        ),
        cv.Text(
            left,
            height - 6,
            "Bubble area is proportional to weight; the band is the confidence interval "
            "of the fitted line.",
            "muted",
            size=9,
        ),
    )
    return canvas


def _t_crit(df: int, level: float) -> float:
    from scipy import stats

    return float(stats.t.ppf((1 + level) / 2, df))


# --- writing ----------------------------------------------------------------------------------

BUILDERS = {"forest": forest, "funnel": funnel, "baujat": baujat, "bubble": bubble}


def render(canvas: cv.Canvas, fmt: str) -> bytes:
    if fmt == "svg":
        return canvas.render_svg().encode("utf-8")
    if fmt == "pdf":
        return canvas.render_pdf()
    if fmt == "png":
        try:
            import cairosvg  # type: ignore[import-not-found,unused-ignore]
        except ImportError:
            raise PlotError(
                "PNG output needs the optional 'cairosvg' package (pip install cairosvg); "
                "use --plot-format svg or pdf"
            ) from None
        return bytes(cairosvg.svg2png(bytestring=canvas.render_svg().encode("utf-8")))
    raise PlotError(f"plot format must be one of {', '.join(FORMATS)}, got {fmt!r}")


def write_plots(
    spec: AnalysisSpec, result: EngineResult, directory: Path, fmt: str = "svg"
) -> list[str]:
    """Write each requested plot under `directory`; returns the relative file names written."""
    requested: list[Any] = spec.section("plots")
    written = []
    for name in requested:
        canvas = BUILDERS[name](spec, result)
        directory.mkdir(parents=True, exist_ok=True)
        data = render(canvas, fmt)
        (directory / f"{name}.{fmt}").write_bytes(data)
        written.append(f"plots/{name}.{fmt}")
    return written
