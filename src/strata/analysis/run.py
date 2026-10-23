"""Running an analysis and writing `analysis/results/<id>/`
(openspec:analysis-specification#running-analyses).

`estimates.json`, `studies.tsv`, `summary.md`, `run.json` and the plots are written only when the
user runs `strata analyze` deliberately, never as a side effect of another command. `run.json`
carries an `input_digest` over the exact effect rows and options fed to the estimator, so
`strata verify` can tell an analysis made stale by its data from one made stale by the tool.
"""

from __future__ import annotations

import hashlib
import json
import platform
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy
import scipy

from strata import __version__, gitio
from strata.analysis import engine as engine_mod
from strata.analysis import plots as plots_mod
from strata.analysis.rows import Selection, build_rows
from strata.analysis.spec import AnalysisSpec, load_spec, results_dir
from strata.core.canon import canonical_json
from strata.core.repo import Repo

ENGINE = "native"
RESULT_FILES = ("estimates.json", "studies.tsv", "summary.md", "run.json")


@dataclass
class Outcome:
    spec: AnalysisSpec
    result: engine_mod.EngineResult
    run: dict[str, Any]
    directory: Path
    written: list[str]


def input_digest(spec: AnalysisSpec, selection: Selection) -> str:
    """`sha256:` over the canonical serialisation of the exact effect rows and options."""
    names = [m["name"] for m in spec.section("moderators")]
    rows = [
        {
            "study_id": r.study_id,
            "effect_id": r.effect_id,
            "design": r.design,
            "measure": r.measure,
            "yi": r.yi,
            "vi": r.vi,
            "n": r.n,
            "moderators": {n: r.values().get(n) for n in names},
            "assumed_correlation": r.details.get("assumed_correlation"),
        }
        for r in selection.rows
    ]
    payload = canonical_json({"rows": engine_mod.clean(rows), "options": spec.doc})
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _criteria_version(repo: Repo) -> int:
    from strata.core.status import _read_criteria_version

    return int(_read_criteria_version(repo))


def _commit(repo: Repo) -> str | None:
    try:
        return gitio.current_commit(repo.root)[:7]
    except gitio.GitError:
        return None


def run_record(
    repo: Repo,
    spec: AnalysisSpec,
    selection: Selection,
    result: engine_mod.EngineResult,
    acknowledged: Iterable[str],
) -> dict[str, Any]:
    record: dict[str, Any] = engine_mod.clean(
        {
            "analysis": spec.id,
            "label": spec.label,
            "strata_version": __version__,
            "engine": ENGINE,
            "schema_version": repo.schema_version,
            "input_digest": input_digest(spec, selection),
            "inputs": {
                "studies": result.estimates["k_studies"],
                "effects": result.estimates["k_effects"],
                "criteria_version": _criteria_version(repo),
            },
            "seed": spec.section("seed"),
            "dependencies": {"numpy": numpy.__version__, "scipy": scipy.__version__},
            "platform": {"python": platform.python_version()},
            "warnings": [
                {
                    "code": w["code"],
                    "acknowledged": w["acknowledged"],
                    "forced": w["forced"],
                }
                for w in result.warnings
            ],
            "acknowledged": sorted(set(acknowledged)),
            "forced_bypasses": sorted(result.forced),
            "conventions": result.estimates["pooled"].get("conventions", {}),
            "generated_from_commit": _commit(repo),
        }
    )
    return record


def _dump(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def studies_tsv(result: engine_mod.EngineResult, spec: AnalysisSpec) -> str:
    """The values behind the plots, one row per pooled effect (openspec:analysis-plots)."""
    level = spec.section("model")["level"]
    from scipy import stats

    crit = float(stats.norm.ppf((1 + level) / 2))
    header = [
        "study_id",
        "effect_id",
        "label",
        "n",
        "year",
        "yi",
        "vi",
        "se",
        "ci_lb",
        "ci_ub",
        "weight_pct",
        "n_effects",
    ]
    lines = ["\t".join(header)]
    for unit, weight in zip(result.units, result.weights, strict=True):
        se = unit.vi**0.5
        cells = [
            unit.study_id,
            unit.effect_id,
            unit.label,
            "" if unit.n is None else str(unit.n),
            "" if unit.year is None else str(unit.year),
            _num(unit.yi),
            _num(unit.vi),
            _num(se),
            _num(unit.yi - crit * se),
            _num(unit.yi + crit * se),
            _num(weight),
            str(len(unit.rows)),
        ]
        lines.append("\t".join(c.replace("\t", " ").replace("\n", " ") for c in cells))
    return "\n".join(lines) + "\n"


def _num(value: float) -> str:
    cleaned = engine_mod.clean(float(value))
    return "" if cleaned is None else repr(cleaned)


def summary_md(spec: AnalysisSpec, result: engine_mod.EngineResult) -> str:
    e = result.estimates
    pooled = e["pooled"]
    first = pooled["coefficients"][0]
    lines = [f"# {spec.title}", ""]
    if not spec.preregistered:
        lines += [
            "> **Exploratory analysis.** This analysis is not marked preregistered; report it "
            "as exploratory.",
            "",
        ]
    lines += [f"Analysis `{spec.id}` ({spec.label}); effect measure {spec.measure}.", ""]
    het = pooled.get("heterogeneity")
    sentence = (
        f"Across {e['k_studies']} studies ({e['k_effects']} effects), the pooled {spec.measure} "
        f"was {_fmt(first['estimate'])} (95% CI {_fmt(first['ci_lb'])} to {_fmt(first['ci_ub'])})."
    )
    back = e.get("back_transformed")
    if back:
        sentence += (
            f" On the {back['scale']} scale this is {_fmt(back['estimate'])} "
            f"({_fmt(back['ci_lb'])} to {_fmt(back['ci_ub'])})."
        )
    lines += [sentence, ""]
    if het:
        lines += [
            f"Between-study heterogeneity: tau = {_fmt(het['tau'])} (tau^2 = {_fmt(het['tau2'])}), "
            f"I^2 = {_fmt(het['I2'], 1)}%, Q({het['Q_df']}) = {_fmt(het['Q'])}, "
            f"p = {_fmt(het['Q_p'], 4)}.",
            "",
        ]
    elif "variance_components" in pooled:
        vc = pooled["variance_components"]
        lines += [
            f"Variance components: between studies {_fmt(vc['study'])}, between effects within "
            f"studies {_fmt(vc['effect'])} (assumed within-study correlation rho = "
            f"{pooled['rho']}).",
            "",
        ]
    pi = pooled.get("prediction_interval")
    if pi and pi.get("lb") is not None:
        lines += [
            f"The 95% prediction interval, where a new study's true effect is expected to fall, is "
            f"{_fmt(pi['lb'])} to {_fmt(pi['ub'])} ({pi['convention']}).",
            "",
        ]
    elif pi:
        lines += [f"No prediction interval is reported: {pi['reason']}.", ""]
    bias = e.get("publication_bias")
    if bias:
        lines += ["## Small-study effects", ""]
        for key in ("egger", "begg"):
            if key in bias:
                lines.append(f"- {bias[key]['interpretation']}")
        if "pet_peese" in bias:
            lines.append(f"- {bias['pet_peese']['interpretation']}")
        if "trim_fill" in bias:
            lines.append(f"- {bias['trim_fill']['interpretation']}")
        lines += ["", "These are sensitivity analyses; none corrects for publication bias.", ""]
    if "sweeps" in e:
        lines += ["## Assumptions swept", ""]
        for sweep in e["sweeps"].values():
            lines.append(f"- {sweep['note']}:")
            for v in sweep["values"]:
                key = "rho" if "rho" in v else "r"
                lines.append(
                    f"  - {key} = {v[key]}: {_fmt(v['estimate'])} "
                    f"({_fmt(v['ci_lb'])} to {_fmt(v['ci_ub'])})"
                )
        lines.append("")
    shown = [w for w in result.warnings if not w["acknowledged"]]
    if shown:
        lines += ["## Warnings", ""]
        lines += [f"- **{w['code']}**: {w['message']}" for w in shown]
        lines.append("")
    lines += [
        "## Conventions",
        "",
        f"- Model: {e['model']['type']}; tau^2 estimator {e['model']['tau2_estimator']}; "
        f"interval {e['model']['ci_method']}.",
        "- I^2 and H^2 are Q-based; the prediction interval uses a t distribution on "
        "k - 2 degrees of freedom.",
        "",
    ]
    return "\n".join(lines)


def _fmt(value: Any, digits: int = 3) -> str:
    return "n/a" if value is None else f"{value:.{digits}f}"


def run_analysis(
    repo: Repo,
    analysis_id: str,
    *,
    force: bool = False,
    acknowledged: Iterable[str] = (),
    write: bool = True,
    plot_format: str = "svg",
) -> Outcome:
    """Run one analysis; with `write`, write `analysis/results/<id>/`."""
    spec = load_spec(repo, analysis_id)
    selection = build_rows(repo, spec)
    ack = sorted(set(acknowledged))
    result = engine_mod.run_analysis(spec, selection, force=force, acknowledged=ack)
    run = run_record(repo, spec, selection, result, ack)
    directory = results_dir(repo, analysis_id)
    written: list[str] = []
    if write:
        directory.mkdir(parents=True, exist_ok=True)
        files = {
            "estimates.json": _dump(result.estimates),
            "studies.tsv": studies_tsv(result, spec),
            "summary.md": summary_md(spec, result),
            "run.json": _dump(run),
        }
        for name, text in files.items():
            (directory / name).write_text(text, encoding="utf-8", newline="\n")
            written.append(name)
        written += plots_mod.write_plots(spec, result, directory / "plots", plot_format)
    return Outcome(spec, result, run, directory, written)


def results_state(repo: Repo, analysis_id: str) -> str:
    """`missing`, `fresh`, `stale-data` (the effect rows or options changed) or `stale-tool`."""
    directory = results_dir(repo, analysis_id)
    run_path = directory / "run.json"
    if not run_path.exists():
        return "missing"
    recorded = json.loads(run_path.read_text(encoding="utf-8"))
    spec = load_spec(repo, analysis_id)
    digest = input_digest(spec, build_rows(repo, spec))
    if recorded.get("input_digest") != digest:
        return "stale-data"
    if recorded.get("strata_version") != __version__:
        return "stale-tool"
    return "fresh"
