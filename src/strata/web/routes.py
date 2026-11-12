"""Route handlers for `strata serve`: openspec:web-ui.

Scope built so far (docs/m2-plan.md sub-objective 11 splits the web UI into
sittings): the dashboard (`/`), the title-abstract/full-text screening
surface (`/screen/<stage>`), the stale-queue re-screening surface
(`/rescreen/<stage>`), conflict resolution (`/adjudicate/<stage>`), the
criteria editor with its live, non-mutating impact preview (`/criteria`) --
the one web-UI piece the M2 roadmap acceptance checklist names outright
("The criteria editor's impact preview is correct and non-mutating,"
docs/roadmap.md, M2) -- and the read-only `/records`, `/records/<id>`,
`/history` screens (reusing exactly the CLI's own data paths: `core.filters`
for `--filter`, `core.provenance.build_provenance` for `strata why`,
`core.logcmd.domain_log` for `strata log`). All of it is server-rendered
with full-page-reload semantics (openspec:web-ui#technology's hard "MUST function with JavaScript
disabled" requirement) plus a small keyboard-shortcut script layered on
top, not a JS-required SPA.

`/dedup` (the duplicate review queue) reuses `dedup.engine.preview_dedup`,
a non-mutating dry run added alongside this route specifically because
`run_dedup` itself always writes its auto-merges as a side effect --
`GET /dedup` renders the classification pass's result without ever
persisting it, and the two actual mutations (auto-merging for real,
merging or keeping one pair after review) are explicit `POST`s a reviewer
takes deliberately, each with its own rationale.

**Statelessness and "undo"/"skip".** openspec:web-ui#strictly-local requires the server be stateless
with respect to the repository, so there is no server-side session
tracking "what have I shown this browser." The one record `/screen/<stage>`
shows is always a pure function of the request: the actor's queue (web-ui S14,
deterministic, sorted by id) minus a `skip` query parameter carrying
forward ids the reviewer chose not to decide yet, or a `redo` parameter
naming a specific record to redecide (how `[u]ndo`, web-ui S7, is implemented --
the *previous* page's redirect carries the just-decided id forward as
`prev`, and the current page turns that into a `redo` link). This keeps
every request self-contained (also what makes web-ui S8, "closing the tab and
returning resumes at the same record," true for free: the queue itself
already excludes whatever has actually been decided) at the cost of a
`skip` list that lives only in the URL for that browsing session -- a
documented, acceptable trade against a much larger stateful-session design
this sitting does not have the scope for.

**Commit policy.** openspec:git-integration#batched-screening-commits: a decision is appended
(and fsynced) the moment it is made and committed later in a batch of its reviewer's own. The
batch is committed when the reviewer ends the session (the "Finish session" button, going to any
page other than the screening screens, or stopping the server), at the 200th uncommitted decision,
after 15 minutes without one, and before anything else commits; `strata serve` also commits what
an earlier server left behind when it starts. The triggers live in `strata.web.app` and
`strata.web.server`; the batch itself is `strata.core.screen_batches`. A decision that changes the
reviewer's own earlier one needs a reason, kept in the event's note and listed in the batch's
message.
"""

from __future__ import annotations

from typing import Any, cast
from urllib.parse import quote, urlparse

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from strata import gitio
from strata.core import agent_ops as agent_ops_mod
from strata.core import agents as agents_mod
from strata.core import fieldedit as fieldedit_mod
from strata.core import filters as filters_mod
from strata.core import logcmd as logcmd_mod
from strata.core import provenance as provenance_mod
from strata.core import records as records_mod
from strata.core import status as status_mod
from strata.core.commit import RationaleRejectedError, StructuredCommit, validate_rationale
from strata.core.screen_batches import flush_pending_screening, flush_under_lock, own_decision
from strata.dedup import engine as engine_mod
from strata.ingest import pipeline as pipeline_mod
from strata.protocol import adjudication as adjudication_mod
from strata.protocol import blinding as blinding_mod
from strata.protocol import criteria as criteria_mod
from strata.protocol import pool as pool_mod
from strata.protocol import rescreen as rescreen_mod
from strata.protocol import screening as screening_mod
from strata.web import timeline as timeline_mod
from strata.web.app import AppState, state_of
from strata.web.messages import for_reviewer, named

router = APIRouter()

_DIRECTIONS = ("tightened", "loosened", "both", "editorial")


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


def _error(message: str, *, status_code: int) -> PlainTextResponse:
    """A short, non-templated error message (an unknown stage/id, a
    rejected decision, a domain-validation failure). These carry no HTML
    markup, so they belong on `text/plain`, not `text/html`: several of
    them interpolate a path or form value the caller controls (`stage`,
    `record_id`, `criterion_id`, ...) straight into the string, and a
    `text/html` response would let a value like `<script>` execute in the
    browser (reflected XSS) even though nothing here is meant to be
    rendered as markup in the first place. `text/plain` closes that off
    entirely rather than escaping around it."""
    return PlainTextResponse(message, status_code=status_code)


def _redirect(path: str, **query: str) -> RedirectResponse:
    """Build a same-origin redirect, percent-encoding every query value
    (skip lists, record ids carried forward as `prev`/`redo`) so none of
    them can break out of the query string into a different path or inject
    a header -- decoded back losslessly by Starlette's own query-param
    parsing on the next request, so this changes nothing a caller can
    observe. Callers percent-encode any *path* segment themselves (e.g.
    `stage`) with the same `urllib.parse.quote` before it reaches here.

    Every caller only ever passes a same-origin relative path, so also
    parse the finished URL and refuse to redirect anywhere a scheme or
    host appears (CodeQL py/url-redirection's exact concern: a value that
    could send the browser off this app entirely) -- structurally
    impossible given the percent-encoding above, but checked explicitly
    rather than left implicit.
    """
    pairs = [(key, value) for key, value in query.items() if value]
    if pairs:
        path += "?" + "&".join(f"{key}={quote(value, safe='')}" for key, value in pairs)
    parsed = urlparse(path)
    if parsed.scheme or parsed.netloc:
        raise ValueError(f"refusing to redirect to a non-relative target: {path!r}")
    return RedirectResponse(url=path, status_code=303)


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request) -> HTMLResponse:
    state: AppState = state_of(request)
    repo = state.open_repo()
    report = status_mod.compute_status(repo)
    enabled = agents_mod.is_enabled(repo)
    return _render(
        request,
        "dashboard.html",
        {
            "report": report,
            "actor": state.actor,
            "finished": request.query_params.get("finished") == "1",
            # The stage table counts records; a reviewer rescreens their own decisions, which is
            # a different number, so the table shows both and says which is which.
            "my_stale": {
                stage.stage: len(rescreen_mod.rescreen_queue(repo, stage.stage, state.actor))
                for stage in report.stages
            },
            "awaiting_export": pipeline_mod.searches_awaiting_import(repo),
            "ai_enabled": enabled,
            "ai_policy": {
                kind: mode for kind, mode in agents_mod.policy(repo).items() if mode != "off"
            },
            "ai_pending": len(agent_ops_mod.visible_pending(repo, state.actor)) if enabled else 0,
        },
    )


def _canonical_ids(repo: Any) -> list[str]:
    return sorted(
        r["id"]
        for r in records_mod.read_records(repo)
        if r.get("strata", {}).get("canonical", True)
    )


_DECISIONS = ("include", "exclude", "maybe")


def _reasons_for_stage(repo: Any, stage: str) -> list[dict[str, Any]]:
    """The active criteria a decision at `stage` may cite, in the order `strata screen` numbers
    them, so `3` means the same criterion on the command line and in the browser."""
    return [c for c in criteria_mod.list_criteria(repo, at=stage) if c["status"] == "active"]


def _needs_a_reason(
    repo: Any, *, stage: str, record_id: str, actor: str, decision: str, note: str | None
) -> str | None:
    """What to tell a reviewer who is changing their own earlier decision without saying why
    (openspec:git-integration#batched-screening-commits); `None` when nothing is missing."""
    if decision not in _DECISIONS or note:
        return None
    before = own_decision(repo, stage=stage, record_id=record_id, actor=actor)
    if before is None or before.get("decision") == decision:
        return None
    return (
        f"You decided {str(before.get('decision')).upper()} for this record before. "
        f"Say why it is now {decision.upper()} in the box below, then choose again."
    )


def _screen_page(
    request: Request,
    stage: str,
    *,
    skip_ids: set[str],
    redo_id: str | None,
    prev_id: str | None,
    again: bool = False,
    error: str | None = None,
    error_detail: str | None = None,
    ticked: list[str] | None = None,
    note: str = "",
    status_code: int = 200,
) -> HTMLResponse | RedirectResponse:
    """`/screen/<stage>` for one request: the record to show and where the reviewer is in the
    queue. The same page answers a decision that was turned away, with the reason on it."""
    state: AppState = state_of(request)
    repo = state.open_repo()

    canonical_ids = _canonical_ids(repo)
    assign_events = screening_mod.all_assign_events(repo)
    total_assigned = sum(
        1
        for rid in canonical_ids
        if state.actor
        in screening_mod.assigned_actors(repo, stage, rid, assign_events=assign_events)
    )
    undecided = screening_mod.stage_queue(repo, stage, state.actor)
    queue = [rid for rid in undecided if rid not in skip_ids]
    skipped = [rid for rid in undecided if rid in skip_ids]
    # Decisions made, whatever was skipped: a skipped record is not a decided one.
    decided = total_assigned - len(undecided)

    record_id: str | None
    if redo_id is not None and records_mod.get_record(repo, redo_id) is not None:
        record_id = redo_id
    elif queue:
        record_id = queue[0]
    elif skipped:
        # Everything else is decided: offer the skipped records again, in order, rather than
        # saying nothing is left while some are still undecided.
        return _redirect(f"/screen/{quote(stage, safe='')}", prev=prev_id or "", again="1")
    else:
        record_id = None

    base = {
        "stage": stage,
        "actor": state.actor,
        "total": total_assigned,
        "decided": decided,
        "prev_id": prev_id,
        "skip_csv": ",".join(sorted(skip_ids)),
        "session_token": state.session_token,
        "pending_commit": state.hosted is None,
    }
    if record_id is None:
        return _render(request, "screen.html", {**base, "record": None, "position": decided})

    record = records_mod.get_record(repo, record_id)
    # `record_id` came from either the validated `redo` id or the queue
    # itself, both already checked against the live record set above.
    assert record is not None
    screening_config = repo.config.get("screening", {})
    before = own_decision(repo, stage=stage, record_id=record_id, actor=state.actor)
    return _render(
        request,
        "screen.html",
        {
            **base,
            "record": record,
            "record_title": record.get("title") or "(no title)",
            "record_abstract": record.get("abstract"),
            "record_authors": _author_display(record),
            "record_year": _record_year(record),
            "record_journal": record.get("container-title"),
            "blind_metadata": bool(screening_config.get("blind_metadata", False)),
            "active_criteria": _reasons_for_stage(repo, stage),
            "require_exclusion_reason": bool(
                screening_config.get("require_exclusion_reason", True)
            ),
            # A record being decided again is one of those already counted.
            "position": decided if before is not None else decided + 1,
            "skipped": len(skipped),
            "again": again,
            "before": before,
            "skip_next_csv": ",".join(sorted(skip_ids | {record_id})),
            "error": error,
            "error_detail": error_detail,
            "ticked": ticked or [],
            "note": note,
        },
        status_code=status_code,
    )


@router.get("/screen/{stage}", response_model=None)
async def screen_stage(
    request: Request, stage: str
) -> HTMLResponse | RedirectResponse | PlainTextResponse:
    state: AppState = state_of(request)
    if stage not in screening_mod.configured_stages(state.open_repo()):
        return _error(f"unknown stage {stage!r}", status_code=404)
    return _screen_page(
        request,
        stage,
        skip_ids=set(_parse_id_list(request.query_params.get("skip"))),
        redo_id=request.query_params.get("redo"),
        prev_id=request.query_params.get("prev"),
        again=request.query_params.get("again") == "1",
    )


@router.post("/screen/{stage}", response_model=None)
async def screen_stage_submit(
    request: Request, stage: str
) -> RedirectResponse | HTMLResponse | PlainTextResponse:
    state: AppState = state_of(request)
    repo = state.open_repo()
    if stage not in screening_mod.configured_stages(repo):
        return _error(f"unknown stage {stage!r}", status_code=404)
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

    def turned_away(
        message: str, detail: str | None = None
    ) -> HTMLResponse | RedirectResponse | PlainTextResponse:
        if records_mod.get_record(repo, record_id) is None:
            return _error(message, status_code=422)
        # The same page, where the reviewer was, with what they had ticked and typed.
        return _screen_page(
            request,
            stage,
            skip_ids=set(_parse_id_list(skip_csv)),
            redo_id=record_id,
            prev_id=None,
            error=message,
            error_detail=detail,
            ticked=cited,
            note=note or "",
            status_code=422,
        )

    missing = _needs_a_reason(
        repo, stage=stage, record_id=record_id, actor=state.actor, decision=decision, note=note
    )
    if missing is not None:
        return turned_away(missing)
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
        shown = for_reviewer(exc)
        return turned_away(shown.text, shown.detail)

    return _redirect(f"/screen/{quote(stage, safe='')}", prev=record_id, skip=skip_csv)


@router.post("/session/finish", response_model=None)
async def finish_session(request: Request) -> RedirectResponse:
    """End a screening session: commit the decisions it recorded
    (openspec:git-integration#batched-screening-commits). The request is not a screening one, so
    whatever is pending was committed before this handler ran (`strata.web.app`, and a hosted
    instance likewise); this is the safety net and the way back to the dashboard."""
    state: AppState = state_of(request)
    if state.hosted is None:
        flush_under_lock(state.open_repo())
        state.batches.clear()
    return _redirect("/", finished="1")


# --------------------------------------------------------------- rescreen


def _rescreen_page(
    request: Request,
    stage: str,
    *,
    skip_ids: set[str],
    redo_id: str | None,
    prev_id: str | None,
    error: str | None = None,
    error_detail: str | None = None,
    ticked: list[str] | None = None,
    note: str | None = None,
    status_code: int = 200,
) -> HTMLResponse | PlainTextResponse:
    state: AppState = state_of(request)
    repo = state.open_repo()
    try:
        full_queue = rescreen_mod.rescreen_queue(repo, stage, state.actor)
    except rescreen_mod.RescreenError:
        return _error(f"unknown stage {stage!r}", status_code=404)

    queue = [s for s in full_queue if s.record_id not in skip_ids]
    stale: rescreen_mod.StaleRecord | None = None
    if redo_id is not None:
        stale = next((s for s in full_queue if s.record_id == redo_id), None)
    if stale is None:
        # Skipped records come round again once the others are done.
        stale = queue[0] if queue else (full_queue[0] if full_queue else None)

    if stale is None:
        return _render(
            request,
            "rescreen.html",
            {
                "stage": stage,
                "actor": state.actor,
                "stale": None,
                "total": 0,
                "session_token": state.session_token,
            },
        )

    if not queue:
        skip_ids = set()
    record = records_mod.get_record(repo, stale.record_id)
    assert record is not None
    return _render(
        request,
        "rescreen.html",
        {
            "stage": stage,
            "actor": state.actor,
            "stale": stale,
            "record": record,
            "record_title": record.get("title") or "(no title)",
            "active_criteria": _reasons_for_stage(repo, stage),
            "total": len(full_queue),
            "skipped": len(full_queue) - len(queue) if queue else 0,
            "prev_id": prev_id,
            "skip_csv": ",".join(sorted(skip_ids)),
            "skip_next_csv": ",".join(sorted(skip_ids | {stale.record_id})),
            "session_token": state.session_token,
            "error": error,
            "error_detail": error_detail,
            "ticked": ticked or [],
            # What the reviewer said last time is offered again: one criterion change usually
            # turns many decisions for the same reason.
            "note": note if note is not None else state.batches.last_reason(state.actor, stage),
        },
        status_code=status_code,
    )


@router.get("/rescreen/{stage}", response_class=HTMLResponse, response_model=None)
async def rescreen_stage(request: Request, stage: str) -> HTMLResponse | PlainTextResponse:
    """The stale queue (openspec:staleness, openspec:web-ui#re-screening-mode): identical to
    `/screen/<stage>` (same statelessness, skip/undo design -- see this
    module's docstring), plus the prior decision/reason shown and a fourth
    `[k]eep previous` action. One difference forced by statelessness: `/
    screen`'s "N of M" position has a stable M (everything *assigned*) and
    an increasing N; here there is no "assigned but not yet stale" set to
    anchor M to, so the count is the reviewer's own stale decisions at the stage and *shrinks*
    as they work through it (14 left, then 13, ...) -- an accurate, honest count
    at every page load, just shaped differently.
    """
    return _rescreen_page(
        request,
        stage,
        skip_ids=set(_parse_id_list(request.query_params.get("skip"))),
        redo_id=request.query_params.get("redo"),
        prev_id=request.query_params.get("prev"),
    )


@router.post("/rescreen/{stage}", response_model=None)
async def rescreen_stage_submit(
    request: Request, stage: str
) -> RedirectResponse | HTMLResponse | PlainTextResponse:
    state: AppState = state_of(request)
    repo = state.open_repo()
    form = request.state.form

    record_id = str(form.get("record_id") or "")
    decision = str(form.get("decision") or "")
    cited = [str(v) for v in form.getlist("criteria")]
    note = str(form.get("note") or "").strip() or None
    skip_csv = str(form.get("skip") or "")

    try:
        queue = rescreen_mod.rescreen_queue(repo, stage, state.actor)
    except rescreen_mod.RescreenError:
        return _error(f"unknown stage {stage!r}", status_code=404)
    stale = next((s for s in queue if s.record_id == record_id), None)

    def turned_away(message: str, detail: str | None = None) -> HTMLResponse | PlainTextResponse:
        if stale is None:
            return _error(message, status_code=422)
        return _rescreen_page(
            request,
            stage,
            skip_ids=set(_parse_id_list(skip_csv)),
            redo_id=record_id,
            prev_id=None,
            error=message,
            error_detail=detail,
            ticked=cited,
            note=note or "",
            status_code=422,
        )

    kept = decision == "keep"
    if kept:
        if stale is None:
            return _error(
                f"{record_id!r} is no longer in the stale queue for {stage!r}", status_code=422
            )
        decision = stale.prior_decision
        cited = list(stale.prior_criteria)
        note = None  # the reason box is for a changed decision; keeping one changes nothing
    else:
        missing = _needs_a_reason(
            repo, stage=stage, record_id=record_id, actor=state.actor, decision=decision, note=note
        )
        if missing is not None:
            return turned_away(missing)

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
        shown = for_reviewer(exc)
        return turned_away(shown.text, shown.detail)
    if note and not kept:
        state.batches.remember_reason(state.actor, stage, note)

    return _redirect(f"/rescreen/{quote(stage, safe='')}", prev=record_id, skip=skip_csv)


# ------------------------------------------------------------- adjudicate


@router.get("/adjudicate/{stage}", response_class=HTMLResponse, response_model=None)
async def adjudicate_stage(request: Request, stage: str) -> HTMLResponse | PlainTextResponse:
    """Conflict resolution (openspec:adjudication). Same skip-list statelessness
    as `/screen`/`/rescreen`; there is no "undo" here since an adjudication
    is a one-way resolution of a disagreement, not a routine decision."""
    state: AppState = state_of(request)
    repo = state.open_repo()

    try:
        full_queue = adjudication_mod.conflict_queue(repo, stage)
    except adjudication_mod.AdjudicationError:
        return _error(f"unknown stage {stage!r}", status_code=404)

    skip_ids = set(_parse_id_list(request.query_params.get("skip")))
    queue = [rid for rid in full_queue if rid not in skip_ids]
    if state.hosted is not None:
        # openspec:hosted-deployment#blinding-between-users: a conflict shows both opinions, so
        # it is not shown to a member who has yet to decide that record themselves.
        hidden = blinding_mod.blinded_records(repo, state.actor).get(stage, frozenset())
        queue = [rid for rid in queue if rid not in hidden]

    if not queue:
        return _render(
            request,
            "adjudicate.html",
            {"stage": stage, "actor": state.actor, "record": None, "total": 0},
        )

    record_id = queue[0]
    record = records_mod.get_record(repo, record_id)
    assert record is not None
    conflict_state = screening_mod.resolve_record_state(repo, stage, record_id)
    opinions = sorted(conflict_state.opinions.items(), key=lambda kv: kv[0])
    active_criteria = _reasons_for_stage(repo, stage)  # numbered as the screening screens do
    return _render(
        request,
        "adjudicate.html",
        {
            "stage": stage,
            "actor": state.actor,
            "record": record,
            "record_title": record.get("title") or "(no title)",
            "opinions": opinions,
            "active_criteria": active_criteria,
            "is_adjudicator": adjudication_mod.is_adjudicator(repo, state.actor),
            "view_only": named("not-an-adjudicator"),
            "total": len(queue),
            "skip_csv": ",".join(sorted(skip_ids)),
            "skip_next_csv": ",".join(sorted(skip_ids | {record_id})),
            "session_token": state.session_token,
        },
    )


@router.post("/adjudicate/{stage}", response_model=None)
async def adjudicate_stage_submit(
    request: Request, stage: str
) -> RedirectResponse | PlainTextResponse:
    state: AppState = state_of(request)
    repo = state.open_repo()
    form = request.state.form

    record_id = str(form.get("record_id") or "")
    decision = str(form.get("decision") or "")
    cited = [str(v) for v in form.getlist("criteria")]
    raw_rationale = str(form.get("rationale") or "")
    skip_csv = str(form.get("skip") or "")

    try:
        rationale = validate_rationale(raw_rationale)
        adjudication_mod.record_adjudication(
            repo,
            stage=stage,
            record_id=record_id,
            decision=decision,  # type: ignore[arg-type]
            actor=state.actor,
            rationale=rationale,
            cited=cited,
        )
    except (RationaleRejectedError, adjudication_mod.AdjudicationError) as exc:
        return _error(for_reviewer(exc).text, status_code=422)

    pool_mod.regenerate_all(repo)
    # Short subject: a record id is a ~20-char ULID, and
    # StructuredCommit.subject() enforces a 72-character line (
    # openspec:git-integration#structured-commit-messages) -- unlike the CLI's own `adjudicate`,
    # which batches a whole
    # session into one commit (`strata adjudicate N conflict(s)`, no id),
    # the web surface commits one adjudication at a time, so the id has to
    # fit in the summary itself.
    commit_obj = StructuredCommit(
        op="adjudicate",
        scope=stage,
        summary=f"adjudicate {record_id}",
        body=rationale,
        trailers={"Op": "adjudicate", "Stage": stage, "Record": record_id, "Actor": state.actor},
    )
    flush_pending_screening(repo)
    gitio.add(repo.root, ["records", "events", "derived"])
    gitio.commit(repo.root, commit_obj.message())

    return _redirect(f"/adjudicate/{quote(stage, safe='')}", skip=skip_csv)


# ---------------------------------------------------------------- criteria


def _commit_criteria_change(
    repo: Any, *, op: str, criterion_id: str, summary: str, actor: str, rationale: str
) -> None:
    """Mirrors `cli.main._commit_criteria_op`'s shape (regenerate derived
    views, one structured commit) -- the web surface always commits a
    criteria change immediately, unlike screening decisions (see this
    module's docstring on the deferred batched-commit policy), since a
    criteria edit is a single, deliberate, already-confirmed action with
    its own rationale, not one of many decisions in a session."""
    pool_mod.regenerate_all(repo)
    commit_obj = StructuredCommit(
        op=op,
        scope=criterion_id,
        summary=summary,
        body=rationale,
        trailers={"Op": op, "Criterion": criterion_id, "Actor": actor},
    )
    flush_pending_screening(repo)
    gitio.add(repo.root, ["protocol/criteria.yaml", "events/criteria", "derived"])
    gitio.commit(repo.root, commit_obj.message())


@router.get("/criteria", response_class=HTMLResponse)
async def criteria_list(request: Request) -> HTMLResponse:
    state: AppState = state_of(request)
    repo = state.open_repo()
    criteria = sorted(criteria_mod.list_criteria(repo), key=lambda c: c["id"])
    version = criteria_mod.read_criteria_doc(repo)["version"]
    added = request.query_params.get("added")
    if added is not None and criteria_mod.get_criterion(repo, added) is None:
        added = None  # the note only names a criterion that exists, whatever the link said
    return _render(
        request, "criteria.html", {"criteria": criteria, "version": version, "added": added}
    )


def _criteria_edit_context(
    request: Request,
    state: AppState,
    repo: Any,
    criterion: dict[str, Any],
    *,
    mode: str,
    error: str | None = None,
    definition_value: str | None = None,
    rationale_value: str | None = None,
    direction_override: str | None = None,
) -> dict[str, Any]:
    direction = (
        direction_override
        or request.query_params.get("direction")
        or ("loosened" if mode == "retire" else None)
    )
    preview: list[rescreen_mod.StaleRecord] | None = None
    if mode == "retire":
        preview = rescreen_mod.preview_criterion_change_impact(
            repo, criterion_id=criterion["id"], direction="loosened", origin="retired"
        )
    elif direction in _DIRECTIONS:
        preview = rescreen_mod.preview_criterion_change_impact(
            repo, criterion_id=criterion["id"], direction=direction
        )
    if preview is not None and state.hosted is not None:
        # Each stale entry names a prior decision
        # (openspec:hosted-deployment#blinding-between-users).
        preview = blinding_mod.visible(preview, blinding_mod.blinded_records(repo, state.actor))
    # The "Preview" button posts the form (it works without JavaScript, openspec:web-ui#technology),
    # and the page it answers with is rendered from what was posted, so the definition and reason
    # the reviewer had typed come back in the boxes. Nothing typed is ever read from the address:
    # the session token is the form's CSRF field, so a GET form would put it, and the reason, in
    # the URL.
    return {
        "criterion": criterion,
        "mode": mode,
        "direction": direction,
        "directions": _DIRECTIONS,
        "preview": preview,
        "session_token": state.session_token,
        "error": error,
        "definition_value": definition_value
        if definition_value is not None
        else criterion.get("definition", ""),
        "rationale_value": rationale_value if rationale_value is not None else "",
    }


@router.get("/criteria/{criterion_id}/edit", response_class=HTMLResponse, response_model=None)
async def criteria_edit_view(
    request: Request, criterion_id: str
) -> HTMLResponse | PlainTextResponse:
    state: AppState = state_of(request)
    repo = state.open_repo()
    criterion = criteria_mod.get_criterion(repo, criterion_id)
    if criterion is None:
        return _error(f"unknown criterion {criterion_id!r}", status_code=404)
    return _render(
        request,
        "criteria_edit.html",
        _criteria_edit_context(request, state, repo, criterion, mode="edit"),
    )


@router.post("/criteria/{criterion_id}/edit", response_model=None)
async def criteria_edit_submit(
    request: Request, criterion_id: str
) -> RedirectResponse | HTMLResponse | PlainTextResponse:
    state: AppState = state_of(request)
    repo = state.open_repo()
    criterion = criteria_mod.get_criterion(repo, criterion_id)
    if criterion is None:
        return _error(f"unknown criterion {criterion_id!r}", status_code=404)

    form = request.state.form
    direction = str(form.get("direction") or "")
    definition = str(form.get("definition") or "").strip() or None
    raw_rationale = str(form.get("rationale") or "")

    if form.get("intent") == "preview":
        # The impact preview: computed from the posted direction, saving nothing, and the form comes
        # back as it was filled in (openspec:web-ui#criteria-editor-impact-preview).
        return _render(
            request,
            "criteria_edit.html",
            _criteria_edit_context(
                request,
                state,
                repo,
                criterion,
                mode="edit",
                definition_value=str(form.get("definition") or criterion.get("definition", "")),
                rationale_value=raw_rationale,
                direction_override=direction or None,
            ),
        )

    try:
        rationale = validate_rationale(raw_rationale)
        criteria_mod.edit_criterion(
            repo,
            criterion_id,
            direction=direction,  # type: ignore[arg-type]
            actor=state.actor,
            rationale=rationale,
            definition=definition,
        )
    except (RationaleRejectedError, criteria_mod.CriteriaError) as exc:
        context = _criteria_edit_context(
            request,
            state,
            repo,
            criterion,
            mode="edit",
            error=str(exc),
            definition_value=str(form.get("definition") or criterion.get("definition", "")),
            rationale_value=raw_rationale,
            direction_override=direction or None,
        )
        return _render(request, "criteria_edit.html", context, status_code=422)

    _commit_criteria_change(
        repo,
        op="criteria-edit",
        criterion_id=criterion_id,
        summary=f"edit criterion {criterion_id} ({direction})",
        actor=state.actor,
        rationale=rationale,
    )
    return RedirectResponse(url="/criteria", status_code=303)


@router.get("/criteria/{criterion_id}/retire", response_class=HTMLResponse, response_model=None)
async def criteria_retire_view(
    request: Request, criterion_id: str
) -> HTMLResponse | PlainTextResponse:
    state: AppState = state_of(request)
    repo = state.open_repo()
    criterion = criteria_mod.get_criterion(repo, criterion_id)
    if criterion is None:
        return _error(f"unknown criterion {criterion_id!r}", status_code=404)
    return _render(
        request,
        "criteria_edit.html",
        _criteria_edit_context(request, state, repo, criterion, mode="retire"),
    )


@router.post("/criteria/{criterion_id}/retire", response_model=None)
async def criteria_retire_submit(
    request: Request, criterion_id: str
) -> RedirectResponse | HTMLResponse | PlainTextResponse:
    state: AppState = state_of(request)
    repo = state.open_repo()
    criterion = criteria_mod.get_criterion(repo, criterion_id)
    if criterion is None:
        return _error(f"unknown criterion {criterion_id!r}", status_code=404)

    form = request.state.form
    raw_rationale = str(form.get("rationale") or "")

    try:
        rationale = validate_rationale(raw_rationale)
        criteria_mod.retire_criterion(repo, criterion_id, actor=state.actor, rationale=rationale)
    except (RationaleRejectedError, criteria_mod.CriteriaError) as exc:
        context = _criteria_edit_context(
            request,
            state,
            repo,
            criterion,
            mode="retire",
            error=str(exc),
            rationale_value=raw_rationale,
        )
        return _render(request, "criteria_edit.html", context, status_code=422)

    _commit_criteria_change(
        repo,
        op="criteria-retire",
        criterion_id=criterion_id,
        summary=f"retire criterion {criterion_id}",
        actor=state.actor,
        rationale=rationale,
    )
    return RedirectResponse(url="/criteria", status_code=303)


# ------------------------------------------------------------------ dedup


def _dedup_rationale(repo: Any, raw: str) -> tuple[str | None, str | None]:
    """Mirrors `cli.main._get_rationale`'s config-dependent requirement
    (`git.require_rationale`, default `True`) -- unlike `/adjudicate` and
    `/criteria`, the spec doesn't mandate a rationale for dedup decisions
    unconditionally (openspec:git-integration#eliciting-the-rationale), so an empty
    field is only rejected when the repo's own config requires one.
    Returns `(rationale, error)`; exactly one side is `None`.
    """
    require = bool(repo.config.get("git", {}).get("require_rationale", True))
    if not raw.strip() and not require:
        return None, None
    try:
        return validate_rationale(raw), None
    except RationaleRejectedError as exc:
        return None, str(exc)


def _commit_dedup_change(
    repo: Any,
    *,
    op: str,
    scope: str | None,
    summary: str,
    actor: str,
    rationale: str | None,
    extra_trailers: dict[str, str] | None = None,
) -> None:
    commit_obj = StructuredCommit(
        op=op,
        scope=scope,
        summary=summary,
        body=rationale,
        trailers={"Op": op, "Actor": actor, **(extra_trailers or {})},
    )
    # The pool and the identified and duplicate counts move with every merge, as they do for
    # `strata dedup`.
    pool_mod.regenerate_all(repo)
    flush_pending_screening(repo)
    gitio.add(repo.root, ["records", "events", "derived"])
    gitio.commit(repo.root, commit_obj.message())


@router.get("/dedup", response_class=HTMLResponse)
async def dedup_queue(request: Request) -> HTMLResponse:
    """Duplicate review queue (openspec:web-ui#screens), backed by
    `dedup.engine.preview_dedup`'s non-mutating dry run -- see this
    module's docstring for why `run_dedup` itself can't back a `GET`
    directly. One pair at a time, same skip-list statelessness as `/
    adjudicate`; there is no "undo" here either, since a merge or a
    keep-both decision is a one-way resolution, not a routine re-decision
    (a merge can still be reversed, but only via `strata dedup --undo`,
    same as the CLI's own review flow -- not wired into this sitting's web
    surface).
    """
    state: AppState = state_of(request)
    repo = state.open_repo()
    outcome = engine_mod.preview_dedup(repo)

    skip_ids = set(_parse_id_list(request.query_params.get("skip")))
    queue = [c for c in outcome.review_queue if f"{c.record_a}:{c.record_b}" not in skip_ids]
    would_auto_merge = [
        {
            "canonical": records_mod.get_record(repo, canonical_id),
            "absorbed": records_mod.get_record(repo, absorbed_id),
        }
        for canonical_id, absorbed_id in outcome.auto_merged
    ]

    base_context = {
        "actor": state.actor,
        "candidate_pairs_considered": outcome.candidate_pairs_considered,
        "would_auto_merge": would_auto_merge,
        "blocking_warnings": outcome.blocking_warnings,
        "session_token": state.session_token,
    }

    if not queue:
        return _render(request, "dedup.html", {**base_context, "candidate": None, "total": 0})

    candidate = queue[0]
    record_a = records_mod.get_record(repo, candidate.record_a)
    record_b = records_mod.get_record(repo, candidate.record_b)
    assert record_a is not None
    assert record_b is not None
    pair_key = f"{candidate.record_a}:{candidate.record_b}"
    return _render(
        request,
        "dedup.html",
        {
            **base_context,
            "candidate": candidate,
            "record_a": record_a,
            "record_a_authors": _author_display(record_a),
            "record_a_year": _record_year(record_a),
            "record_b": record_b,
            "record_b_authors": _author_display(record_b),
            "record_b_year": _record_year(record_b),
            "total": len(queue),
            "skip_csv": ",".join(sorted(skip_ids)),
            "skip_next_csv": ",".join(sorted(skip_ids | {pair_key})),
        },
    )


@router.post("/dedup/run", response_model=None)
async def dedup_run(request: Request) -> RedirectResponse | PlainTextResponse:
    """Run the real auto-merge pass (`run_dedup`) -- the one `/dedup`
    action not scoped to a single pair. An explicit, deliberate `POST` a
    reviewer takes after seeing the "would auto-merge" list on `GET
    /dedup`; never triggered automatically."""
    state: AppState = state_of(request)
    repo = state.open_repo()
    form = request.state.form
    raw_rationale = str(form.get("rationale") or "")

    rationale, error = _dedup_rationale(repo, raw_rationale)
    if error is not None:
        return _error(error, status_code=422)

    outcome = engine_mod.run_dedup(repo, actor=state.actor)
    if outcome.auto_merged:
        _commit_dedup_change(
            repo,
            op="dedup",
            scope=None,
            summary=f"auto-merged {len(outcome.auto_merged)} duplicate pair(s)",
            actor=state.actor,
            rationale=rationale,
        )
    return RedirectResponse(url="/dedup", status_code=303)


@router.post("/dedup/decide", response_model=None)
async def dedup_decide(request: Request) -> RedirectResponse | PlainTextResponse:
    """Resolve one pair from the review queue: `merge`
    (openspec:deduplication#review-queue) or `keep` (records a sticky `dedup-distinct`,
    openspec:deduplication#sticky-reversible-conservative-explainable, so the pair is never raised
    again). Re-checks the submitted pair
    against a fresh `preview_dedup` rather than trusting the form
    round-trip -- the queue can have moved since the page was rendered,
    the same re-validation `/rescreen`'s `keep-previous` submission does.
    """
    state: AppState = state_of(request)
    repo = state.open_repo()
    form = request.state.form

    record_a_id = str(form.get("record_a") or "")
    record_b_id = str(form.get("record_b") or "")
    decision = str(form.get("decision") or "")
    raw_rationale = str(form.get("rationale") or "")
    skip_csv = str(form.get("skip") or "")

    if decision not in ("merge", "keep"):
        return _error(f"unknown decision {decision!r}", status_code=422)

    outcome = engine_mod.preview_dedup(repo)
    candidate = next(
        (
            c
            for c in outcome.review_queue
            if c.record_a == record_a_id and c.record_b == record_b_id
        ),
        None,
    )
    if candidate is None:
        return _error(
            f"{record_a_id!r}/{record_b_id!r} is no longer pending review", status_code=422
        )

    rationale, error = _dedup_rationale(repo, raw_rationale)
    if error is not None:
        return _error(error, status_code=422)

    engine_mod.apply_review_decision(
        repo,
        record_a_id=candidate.record_a,
        record_b_id=candidate.record_b,
        result=candidate.result,
        decision="merge" if decision == "merge" else "distinct",
        actor=state.actor,
    )
    # `choose_canonical` inside `apply_review_decision` may pick either side
    # as canonical -- the CLI's own `--review` flow (cli.main.dedup_command)
    # doesn't surface that choice back to the caller either, so this
    # matches its existing trailer convention (`record_a` as scope,
    # `record_b` as the named other party) rather than inventing a
    # different one here.
    if decision == "merge":
        op, summary, trailer_key = "dedup", "merged a duplicate after review", "Absorbed"
    else:
        op, summary, trailer_key = (
            "dedup-distinct",
            "kept a pair distinct after review",
            "Other",
        )
    _commit_dedup_change(
        repo,
        op=op,
        scope=candidate.record_a,
        summary=summary,
        actor=state.actor,
        rationale=rationale,
        extra_trailers={trailer_key: candidate.record_b},
    )

    return _redirect("/dedup", skip=skip_csv)


# ----------------------------------------------------------------- records


@router.get("/records", response_class=HTMLResponse)
async def records_list_view(request: Request) -> HTMLResponse:
    """Searchable/filterable record table (openspec:web-ui#screens).
    Read-only, reusing exactly `cli.main.records_list`'s data path
    (`core.filters`'s `--filter` expression language,
    openspec:filter-language) -- unlike `/dedup` (which needed a new non-mutating dry run added
    to `dedup.engine`, see this module's docstring), nothing here needs
    any new preview infrastructure to compute what to show.
    """
    state: AppState = state_of(request)
    repo = state.open_repo()
    filter_expr = request.query_params.get("filter") or ""
    everything = records_mod.read_records(repo)
    records = [r for r in everything if r.get("strata", {}).get("canonical", True)]
    distinct = len(records)
    error: str | None = None
    if filter_expr:
        try:
            ast = filters_mod.parse(filter_expr)
            records = [
                r
                for r in records
                if filters_mod.evaluate(ast, records_mod.record_field_resolver(r))
            ]
        except filters_mod.FilterSyntaxError as exc:
            error = f"invalid filter: {exc}"
        except filters_mod.FilterEvaluationError as exc:
            error = f"filter failed: {exc}"
    records.sort(key=lambda r: str(r["id"]))
    rows = [
        {
            "id": r["id"],
            "year": _record_year(r),
            "authors": _author_display(r),
            "title": r.get("title") or "",
        }
        for r in records
    ]
    return _render(
        request,
        "records.html",
        {
            "rows": rows,
            "filter_expr": filter_expr,
            "error": error,
            "distinct": distinct,
            "merged": len(everything) - distinct,
        },
    )


def record_detail_context(
    state: AppState,
    repo: Any,
    record: dict[str, Any],
    *,
    error: str | None = None,
    fix_values: dict[str, str] | None = None,
    unchanged: bool = False,
) -> dict[str, Any]:
    """What `record_detail.html` shows; also what the correction form re-renders with when it is
    turned away (openspec:web-ui#correcting-a-record)."""
    return {
        "record": record,
        "authors": _author_display(record),
        "year": _record_year(record),
        "timeline": timeline_mod.timeline(
            provenance_mod.build_provenance(repo, record["id"]),
            record_id=record["id"],
            commits=logcmd_mod.domain_log(repo),
        ),
        "editable_fields": sorted(fieldedit_mod.EDITABLE_FIELDS),
        "current_values": {
            name: fieldedit_mod.format_field_value(
                "issued" if name == "year" else name,
                record.get("issued" if name == "year" else name),
            )
            for name in fieldedit_mod.EDITABLE_FIELDS
        },
        "shares_identity": records_mod.records_sharing_identity(repo, record),
        "unchanged": unchanged,
        "session_token": state.session_token,
        "error": error,
        "fix_values": fix_values or {"field": "title", "value": "", "rationale": ""},
    }


@router.get("/records/{record_id}", response_class=HTMLResponse, response_model=None)
async def record_detail_view(request: Request, record_id: str) -> HTMLResponse | PlainTextResponse:
    """Record detail + provenance timeline (`strata why`'s data,
    `core.provenance.build_provenance`)."""
    state: AppState = state_of(request)
    repo = state.open_repo()
    record = records_mod.get_record(repo, record_id)
    if record is None:
        return _error(f"unknown record {record_id!r}", status_code=404)
    return _render(
        request,
        "record_detail.html",
        record_detail_context(
            state, repo, record, unchanged=request.query_params.get("unchanged") == "1"
        ),
    )


# ----------------------------------------------------------------- history


@router.get("/history", response_class=HTMLResponse)
async def history_view(request: Request) -> HTMLResponse:
    """Domain-level history read through `Strata-` commit trailers
    (`strata log`'s data, `core.logcmd.domain_log`) -- never raw commit
    messages, matching that module's own framing."""
    state: AppState = state_of(request)
    repo = state.open_repo()
    stage = request.query_params.get("stage") or None
    actor = request.query_params.get("actor") or None
    commits = [
        {
            "sha": c.sha,
            "subject": c.subject,
            "trailers": c.trailers,
            "date": c.date,
            "when": timeline_mod.when(c.date),
            "reason": c.reason,
        }
        for c in logcmd_mod.domain_log(repo, stage=stage, actor=actor)
    ]
    return _render(request, "history.html", {"commits": commits, "stage": stage, "actor": actor})
