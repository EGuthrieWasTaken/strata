"""Analysis results screens: openspec:web-ui (M4 addition).

`/analysis` lists the analysis specifications and whether their committed results are current;
`/analysis/<id>` shows one analysis's pooled estimate, heterogeneity, guardrail warnings, plots and
the values behind them. The screens only read what `strata analyze` committed: running an
analysis stays a deliberate command-line act (openspec:analysis-specification#running-analyses),
so a stale result is reported, never silently recomputed. Everything is served from local assets;
the generated SVG plots carry their own inline stylesheet (light and dark), so they are served
with a policy of their own that allows nothing else.
"""

from __future__ import annotations

import json
import re
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, Response

from strata.analysis import run as analysis_run
from strata.analysis import spec as analysis_spec
from strata.core.repo import Repo
from strata.web.app import AppState
from strata.web.routes import _error, _render

router = APIRouter()

_PLOT_FILE = re.compile(r"^[a-z][a-z0-9_-]*\.(svg|pdf|png)$")
_PLOT_TYPES = {"svg": "image/svg+xml", "pdf": "application/pdf", "png": "image/png"}
_PLOT_CSP = "default-src 'none'; style-src 'unsafe-inline'; img-src 'self' data:; sandbox"
_STATE_TEXT = {
    "missing": "No results have been produced for this analysis yet.",
    "stale-data": "These results are out of date: the effect data or the specification changed "
    "since they were produced.",
    "stale-tool": "These results were produced by another version of strata and may differ if "
    "rerun.",
    "unchecked": "Whether these results are current could not be checked.",
}
_UNKNOWN = "no analysis {analysis_id!r}"


def _state(repo: Repo, analysis_id: str) -> str:
    try:
        return analysis_run.results_state(repo, analysis_id)
    except ValueError:
        return "unchecked"


def _read_json(path: Any) -> dict[str, Any] | None:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return loaded if isinstance(loaded, dict) else None


def _studies_table(path: Any) -> tuple[list[str], list[list[str]]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return [], []
    if not lines:
        return [], []
    return lines[0].split("\t"), [line.split("\t") for line in lines[1:]]


@router.get("/analysis", response_class=HTMLResponse, response_model=None)
async def analysis_index(request: Request) -> HTMLResponse:
    state: AppState = request.app.state.strata
    repo = state.open_repo()
    rows = []
    for analysis_id in analysis_spec.list_analyses(repo):
        try:
            spec = analysis_spec.load_spec(repo, analysis_id)
            title, label = spec.title, spec.label
        except ValueError as exc:
            title, label = f"invalid specification: {exc}", "invalid"
        rows.append(
            {"id": analysis_id, "title": title, "label": label, "state": _state(repo, analysis_id)}
        )
    return _render(request, "analysis_index.html", {"actor": state.actor, "analyses": rows})


@router.get("/analysis/{analysis_id}", response_class=HTMLResponse, response_model=None)
async def analysis_detail(request: Request, analysis_id: str) -> HTMLResponse | PlainTextResponse:
    state: AppState = request.app.state.strata
    repo = state.open_repo()
    if analysis_id not in analysis_spec.list_analyses(repo):
        return _error(_UNKNOWN.format(analysis_id=analysis_id), status_code=404)
    try:
        spec = analysis_spec.load_spec(repo, analysis_id)
    except ValueError as exc:
        return _error(str(exc), status_code=422)
    directory = analysis_spec.results_dir(repo, analysis_id)
    estimates = _read_json(directory / "estimates.json")
    run = _read_json(directory / "run.json") or {}
    headers, rows = _studies_table(directory / "studies.tsv")
    plots = sorted(p.name for p in (directory / "plots").glob("*.svg")) if estimates else []
    results_state = _state(repo, analysis_id)
    return _render(
        request,
        "analysis.html",
        {
            "actor": state.actor,
            "id": analysis_id,
            "spec": spec,
            "state": results_state,
            "state_text": _STATE_TEXT.get(results_state),
            "estimates": estimates,
            "run": run,
            "warnings": run.get("warnings", []),
            "forced": run.get("forced_bypasses", []),
            "plots": plots,
            "study_headers": headers,
            "study_rows": rows,
        },
    )


@router.get("/analysis/{analysis_id}/plots/{name}", response_model=None)
async def analysis_plot(request: Request, analysis_id: str, name: str) -> Response:
    state: AppState = request.app.state.strata
    repo = state.open_repo()
    if analysis_id not in analysis_spec.list_analyses(repo) or not _PLOT_FILE.match(name):
        return _error("no such plot", status_code=404)
    path = analysis_spec.results_dir(repo, analysis_id) / "plots" / name
    if not path.is_file():
        return _error("no such plot", status_code=404)
    return Response(
        path.read_bytes(),
        media_type=_PLOT_TYPES[name.rsplit(".", 1)[1]],
        headers={"Content-Security-Policy": _PLOT_CSP, "Cache-Control": "no-store"},
    )
