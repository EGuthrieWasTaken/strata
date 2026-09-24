"""Route handlers for `strata serve`: docs/spec/11-web-ui.md §2-§4.

Scope of this sitting (docs/m2-plan.md sub-objective 11 splits the web UI
into two): the dashboard (`/`) and the title-abstract/full-text screening
surface (`/screen/<stage>`), server-rendered with full-page-reload
semantics (§5's hard "MUST function with JavaScript disabled" requirement)
plus a small keyboard-shortcut script layered on top, not a JS-required
SPA. `/rescreen`, `/adjudicate`, `/dedup`, `/records*`, `/criteria`, and
everything M3-shaped (`/extract/*`, `/rob/*`, `/analysis/*`, `/prisma`) are
explicitly deferred, tracked in that same plan entry.

**Statelessness and "undo"/"skip".** §1 requires the server be stateless
with respect to the repository, so there is no server-side session
tracking "what have I shown this browser." The one record `/screen/<stage>`
shows is always a pure function of the request: the actor's queue (§S14,
deterministic, sorted by id) minus a `skip` query parameter carrying
forward ids the reviewer chose not to decide yet, or a `redo` parameter
naming a specific record to redecide (how `[u]ndo`, §S7, is implemented --
the *previous* page's redirect carries the just-decided id forward as
`prev`, and the current page turns that into a `redo` link). This keeps
every request self-contained (also what makes §S8, "closing the tab and
returning resumes at the same record," true for free: the queue itself
already excludes whatever has actually been decided) at the cost of a
`skip` list that lives only in the URL for that browsing session -- a
documented, acceptable trade against a much larger stateful-session design
this sitting does not have the scope for.

**Commit policy.** docs/spec/04-git-integration.md §2.4 batches screening
commits (session end, 200 decisions, or 15 minutes idle) rather than
committing per decision. This sitting appends every decision immediately
(`record_screen_decision` already fsyncs, so nothing is lost --
tests/e2e/test_e2e_09_interrupted_screening.py already validates that
guarantee for the same underlying call) but does not yet implement any of
§2.4's three commit triggers for the web session specifically; a user ends
a web screening session the same way as today, via the CLI (`strata sync`
or a plain `git commit`) or by leaving it for their next `strata screen`
CLI session to close out. Wiring an explicit session-end action is tracked
alongside sitting (b).
"""

from __future__ import annotations

from typing import Any, cast

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from strata.core import records as records_mod
from strata.core import status as status_mod
from strata.protocol import screening as screening_mod
from strata.web.app import AppState

router = APIRouter()


def _author_display(record: dict[str, Any]) -> str:
    names = []
    for author in record.get("author") or []:
        if isinstance(author, dict):
            names.append(author.get("family") or author.get("literal") or "")
        else:
            names.append(str(author))
    return ", ".join(n for n in names if n)


def _record_year(record: dict[str, Any]) -> int | None:
    parts = ((record.get("issued") or {}).get("date-parts")) or [[None]]
    return parts[0][0] if parts else None


def _parse_id_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [part for part in raw.split(",") if part]


def _render(
    request: Request,
    name: str,
    context: dict[str, Any],
    *,
    status_code: int = 200,
) -> HTMLResponse:
    """`Jinja2Templates.TemplateResponse` typed as `Any` upstream; this is
    the one place that asserts it back to `HTMLResponse`."""
    templates: Jinja2Templates = request.app.state.templates
    return cast(
        HTMLResponse,
        templates.TemplateResponse(request, name, context, status_code=status_code),
    )


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request) -> HTMLResponse:
    state: AppState = request.app.state.strata
    repo = state.open_repo()
    report = status_mod.compute_status(repo)
    return _render(request, "dashboard.html", {"report": report, "actor": state.actor})


def _canonical_ids(repo: Any) -> list[str]:
    return sorted(
        r["id"]
        for r in records_mod.read_records(repo)
        if r.get("strata", {}).get("canonical", True)
    )


@router.get("/screen/{stage}", response_class=HTMLResponse)
async def screen_stage(request: Request, stage: str) -> HTMLResponse:
    state: AppState = request.app.state.strata
    repo = state.open_repo()

    if stage not in screening_mod.configured_stages(repo):
        return HTMLResponse(f"unknown stage {stage!r}", status_code=404)

    skip_ids = set(_parse_id_list(request.query_params.get("skip")))
    redo_id = request.query_params.get("redo")
    prev_id = request.query_params.get("prev")

    canonical_ids = _canonical_ids(repo)
    assign_events = screening_mod.all_assign_events(repo)
    total_assigned = sum(
        1
        for rid in canonical_ids
        if state.actor
        in screening_mod.assigned_actors(repo, stage, rid, assign_events=assign_events)
    )

    only_ids = {rid for rid in canonical_ids if rid not in skip_ids}
    queue = screening_mod.stage_queue(repo, stage, state.actor, only_ids=only_ids)
    remaining = len(queue)
    decided = total_assigned - remaining

    record_id: str | None
    if redo_id is not None and records_mod.get_record(repo, redo_id) is not None:
        record_id = redo_id
    else:
        record_id = queue[0] if queue else None

    if record_id is None:
        return _render(
            request,
            "screen.html",
            {
                "stage": stage,
                "actor": state.actor,
                "record": None,
                "total": total_assigned,
                "position": total_assigned,
                "prev_id": prev_id,
                "skip_csv": ",".join(sorted(skip_ids)),
            },
        )

    record = records_mod.get_record(repo, record_id)
    # `record_id` came from either the validated `redo` id or the queue
    # itself, both already checked against the live record set above.
    assert record is not None
    active_criteria = sorted(
        screening_mod.active_criteria_for_stage(repo, stage).values(), key=lambda c: c["id"]
    )
    require_exclusion_reason = bool(
        repo.config.get("screening", {}).get("require_exclusion_reason", True)
    )
    blind_metadata = bool(repo.config.get("screening", {}).get("blind_metadata", False))

    return _render(
        request,
        "screen.html",
        {
            "stage": stage,
            "actor": state.actor,
            "record": record,
            "record_title": record.get("title") or "(no title)",
            "record_abstract": record.get("abstract"),
            "record_authors": _author_display(record),
            "record_year": _record_year(record),
            "record_journal": record.get("container-title"),
            "blind_metadata": blind_metadata,
            "active_criteria": active_criteria,
            "require_exclusion_reason": require_exclusion_reason,
            "total": total_assigned,
            "position": decided + 1,
            "prev_id": prev_id,
            "skip_csv": ",".join(sorted(skip_ids)),
            "skip_next_csv": ",".join(sorted(skip_ids | {record_id})),
            "session_token": state.session_token,
        },
    )


@router.post("/screen/{stage}", response_model=None)
async def screen_stage_submit(request: Request, stage: str) -> RedirectResponse | HTMLResponse:
    state: AppState = request.app.state.strata
    repo = state.open_repo()
    # The security middleware already parsed and CSRF-validated this form
    # (and stashed it on `request.state`, since it read the request body
    # before this handler's own `Request` instance ever saw it -- see
    # app.py's `SecurityMiddleware` for why re-reading here would come
    # back empty).
    form = request.state.form

    record_id = str(form.get("record_id") or "")
    decision = str(form.get("decision") or "")
    cited = [str(v) for v in form.getlist("criteria")]
    note = str(form.get("note") or "").strip() or None
    skip_csv = str(form.get("skip") or "")

    try:
        screening_mod.record_screen_decision(
            repo,
            stage=stage,
            record_id=record_id,
            decision=decision,  # type: ignore[arg-type]
            actor=state.actor,
            cited=cited,
            note=note,
        )
    except screening_mod.ScreeningError as exc:
        record = records_mod.get_record(repo, record_id)
        active_criteria = sorted(
            screening_mod.active_criteria_for_stage(repo, stage).values(),
            key=lambda c: c["id"],
        )
        return _render(
            request,
            "screen.html",
            {
                "stage": stage,
                "actor": state.actor,
                "record": record,
                "record_title": (record or {}).get("title") or "(no title)",
                "record_abstract": (record or {}).get("abstract"),
                "record_authors": _author_display(record or {}),
                "record_year": _record_year(record or {}),
                "record_journal": (record or {}).get("container-title"),
                "blind_metadata": False,
                "active_criteria": active_criteria,
                "require_exclusion_reason": True,
                "total": 0,
                "position": 0,
                "prev_id": None,
                "skip_csv": skip_csv,
                "skip_next_csv": skip_csv,
                "session_token": state.session_token,
                "error": str(exc),
            },
            status_code=422,
        )

    redirect_url = f"/screen/{stage}?prev={record_id}"
    if skip_csv:
        redirect_url += f"&skip={skip_csv}"
    return RedirectResponse(url=redirect_url, status_code=303)
