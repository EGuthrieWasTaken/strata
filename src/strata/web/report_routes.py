"""The live PRISMA flow diagram: openspec:web-ui (M5 addition).

`/prisma` draws the current flow diagram from the event log on every request, with the DRAFT
watermark while screening is unfinished or any decision is stale, beside the counts and whether
every reconciliation identity holds. `/prisma.svg` is the drawing itself, served with the same
inline-stylesheet-only policy as the analysis plots.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, Response

from strata.report import counts as counts_mod
from strata.report import flow as flow_mod
from strata.web.analysis_routes import _PLOT_CSP
from strata.web.app import AppState
from strata.web.routes import _error, _render

router = APIRouter()


def _columns(request: Request) -> str:
    asked = request.query_params.get("columns", "one")
    return asked if asked in flow_mod.COLUMNS else "one"


@router.get("/prisma", response_class=HTMLResponse, response_model=None)
async def prisma_page(request: Request) -> HTMLResponse:
    state: AppState = request.app.state.strata
    repo = state.open_repo()
    counts = counts_mod.compute(repo)
    return _render(
        request,
        "prisma.html",
        {
            "actor": state.actor,
            "columns": _columns(request),
            "counts": counts,
            "totals": counts.totals,
            "draft": not counts.complete,
            "draft_text": flow_mod.DRAFT_TEXT,
            "failures": counts.failures,
            "has_other_methods": bool(counts.other_methods.identified),
        },
    )


@router.get("/prisma.svg", response_model=None)
async def prisma_svg(request: Request) -> Response | PlainTextResponse:
    state: AppState = request.app.state.strata
    counts = counts_mod.compute(state.open_repo())
    if not counts.reconciled:
        return _error("the counts do not close: " + "; ".join(counts.failures), status_code=409)
    svg = flow_mod.render(counts, fmt="svg", columns=_columns(request))
    return Response(
        svg,
        media_type="image/svg+xml",
        headers={"Content-Security-Policy": _PLOT_CSP, "Cache-Control": "no-store"},
    )
