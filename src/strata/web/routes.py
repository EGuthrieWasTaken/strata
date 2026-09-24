"""Route handlers for `strata serve`: docs/spec/11-web-ui.md §2-§4.

Scope built so far (docs/m2-plan.md sub-objective 11 splits the web UI into
sittings): the dashboard (`/`), the title-abstract/full-text screening
surface (`/screen/<stage>`), the stale-queue re-screening surface
(`/rescreen/<stage>`), conflict resolution (`/adjudicate/<stage>`), the
criteria editor with its live, non-mutating impact preview (`/criteria`) --
the one web-UI piece the M2 roadmap acceptance checklist names outright
("The criteria editor's impact preview is correct and non-mutating,"
docs/spec/15-roadmap.md) -- and the read-only `/records`, `/records/<id>`,
`/history` screens (reusing exactly the CLI's own data paths: `core.filters`
for `--filter`, `core.provenance.build_provenance` for `strata why`,
`core.logcmd.domain_log` for `strata log`). All of it is server-rendered
with full-page-reload semantics (§5's hard "MUST function with JavaScript
disabled" requirement) plus a small keyboard-shortcut script layered on
top, not a JS-required SPA.

`/dedup` (the duplicate review queue) reuses `dedup.engine.preview_dedup`,
a non-mutating dry run added alongside this route specifically because
`run_dedup` itself always writes its auto-merges as a side effect --
`GET /dedup` renders the classification pass's result without ever
persisting it, and the two actual mutations (auto-merging for real,
merging or keeping one pair after review) are explicit `POST`s a reviewer
takes deliberately, each with its own rationale.

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
from urllib.parse import quote

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from strata import gitio
from strata.core import filters as filters_mod
from strata.core import logcmd as logcmd_mod
from strata.core import provenance as provenance_mod
from strata.core import records as records_mod
from strata.core import status as status_mod
from strata.core.commit import RationaleRejectedError, StructuredCommit, validate_rationale
from strata.dedup import engine as engine_mod
from strata.protocol import adjudication as adjudication_mod
from strata.protocol import criteria as criteria_mod
from strata.protocol import pool as pool_mod
from strata.protocol import rescreen as rescreen_mod
from strata.protocol import screening as screening_mod
from strata.web.app import AppState

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
    """
    pairs = [(key, value) for key, value in query.items() if value]
    if pairs:
        path += "?" + "&".join(f"{key}={quote(value, safe='')}" for key, value in pairs)
    return RedirectResponse(url=path, status_code=303)


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


@router.get("/screen/{stage}", response_class=HTMLResponse, response_model=None)
async def screen_stage(request: Request, stage: str) -> HTMLResponse | PlainTextResponse:
    state: AppState = request.app.state.strata
    repo = state.open_repo()

    if stage not in screening_mod.configured_stages(repo):
        return _error(f"unknown stage {stage!r}", status_code=404)

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

    return _redirect(f"/screen/{quote(stage, safe='')}", prev=record_id, skip=skip_csv)


# --------------------------------------------------------------- rescreen


@router.get("/rescreen/{stage}", response_class=HTMLResponse, response_model=None)
async def rescreen_stage(request: Request, stage: str) -> HTMLResponse | PlainTextResponse:
    """The stale queue (docs/spec/06 §6, docs/spec/11 §3.2): identical to
    `/screen/<stage>` (same statelessness, skip/undo design -- see this
    module's docstring), plus the prior decision/reason shown and a fourth
    `[k]eep previous` action. One difference forced by statelessness: `/
    screen`'s "N of M" position has a stable M (everything *assigned*) and
    an increasing N; here there is no "assigned but not yet stale" set to
    anchor M to, so M is `rescreen_queue`'s own current size and *shrinks*
    as the reviewer works through it (1 of 14, then 1 of 13, ...) rather
    than N climbing towards a fixed M -- still an accurate, honest count
    at every page load, just shaped differently.
    """
    state: AppState = request.app.state.strata
    repo = state.open_repo()

    try:
        full_queue = rescreen_mod.rescreen_queue(repo, stage, state.actor)
    except rescreen_mod.RescreenError:
        return _error(f"unknown stage {stage!r}", status_code=404)

    skip_ids = set(_parse_id_list(request.query_params.get("skip")))
    redo_id = request.query_params.get("redo")
    prev_id = request.query_params.get("prev")

    queue = [s for s in full_queue if s.record_id not in skip_ids]
    stale: rescreen_mod.StaleRecord | None = None
    if redo_id is not None:
        stale = next((s for s in full_queue if s.record_id == redo_id), None)
    if stale is None:
        stale = queue[0] if queue else None

    if stale is None:
        return _render(
            request,
            "rescreen.html",
            {"stage": stage, "actor": state.actor, "stale": None, "total": 0},
        )

    record = records_mod.get_record(repo, stale.record_id)
    assert record is not None
    active_criteria = sorted(
        screening_mod.active_criteria_for_stage(repo, stage).values(), key=lambda c: c["id"]
    )
    return _render(
        request,
        "rescreen.html",
        {
            "stage": stage,
            "actor": state.actor,
            "stale": stale,
            "record": record,
            "record_title": record.get("title") or "(no title)",
            "active_criteria": active_criteria,
            "total": len(queue),
            "prev_id": prev_id,
            "skip_csv": ",".join(sorted(skip_ids)),
            "skip_next_csv": ",".join(sorted(skip_ids | {stale.record_id})),
            "session_token": state.session_token,
        },
    )


@router.post("/rescreen/{stage}", response_model=None)
async def rescreen_stage_submit(
    request: Request, stage: str
) -> RedirectResponse | PlainTextResponse:
    state: AppState = request.app.state.strata
    repo = state.open_repo()
    form = request.state.form

    record_id = str(form.get("record_id") or "")
    decision = str(form.get("decision") or "")
    cited = [str(v) for v in form.getlist("criteria")]
    skip_csv = str(form.get("skip") or "")

    if decision == "keep":
        try:
            queue = rescreen_mod.rescreen_queue(repo, stage, state.actor)
        except rescreen_mod.RescreenError:
            return _error(f"unknown stage {stage!r}", status_code=404)
        stale = next((s for s in queue if s.record_id == record_id), None)
        if stale is None:
            return _error(
                f"{record_id!r} is no longer in the stale queue for {stage!r}", status_code=422
            )
        decision = stale.prior_decision
        cited = list(stale.prior_criteria)

    try:
        screening_mod.record_screen_decision(
            repo,
            stage=stage,
            record_id=record_id,
            decision=decision,  # type: ignore[arg-type]
            actor=state.actor,
            cited=cited,
        )
    except screening_mod.ScreeningError as exc:
        return _error(str(exc), status_code=422)

    return _redirect(f"/rescreen/{quote(stage, safe='')}", prev=record_id, skip=skip_csv)


# ------------------------------------------------------------- adjudicate


@router.get("/adjudicate/{stage}", response_class=HTMLResponse, response_model=None)
async def adjudicate_stage(request: Request, stage: str) -> HTMLResponse | PlainTextResponse:
    """Conflict resolution (docs/spec/06 §8). Same skip-list statelessness
    as `/screen`/`/rescreen`; there is no "undo" here since an adjudication
    is a one-way resolution of a disagreement, not a routine decision."""
    state: AppState = request.app.state.strata
    repo = state.open_repo()

    try:
        full_queue = adjudication_mod.conflict_queue(repo, stage)
    except adjudication_mod.AdjudicationError:
        return _error(f"unknown stage {stage!r}", status_code=404)

    skip_ids = set(_parse_id_list(request.query_params.get("skip")))
    queue = [rid for rid in full_queue if rid not in skip_ids]

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
    active_criteria = sorted(
        screening_mod.active_criteria_for_stage(repo, stage).values(), key=lambda c: c["id"]
    )
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
    state: AppState = request.app.state.strata
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
        return _error(str(exc), status_code=422)

    pool_mod.regenerate_all(repo)
    # Short subject: a record id is a ~20-char ULID, and
    # StructuredCommit.subject() enforces a 72-character line (docs/spec/04
    # §2.2) -- unlike the CLI's own `adjudicate`, which batches a whole
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
    gitio.add(repo.root, ["protocol/criteria.yaml", "events/criteria", "derived"])
    gitio.commit(repo.root, commit_obj.message())


@router.get("/criteria", response_class=HTMLResponse)
async def criteria_list(request: Request) -> HTMLResponse:
    state: AppState = request.app.state.strata
    repo = state.open_repo()
    criteria = sorted(criteria_mod.list_criteria(repo), key=lambda c: c["id"])
    version = criteria_mod.read_criteria_doc(repo)["version"]
    return _render(request, "criteria.html", {"criteria": criteria, "version": version})


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
    # The "Preview" button is a plain GET resubmit (§5's no-JS baseline),
    # which would otherwise reset the definition/rationale textareas to
    # their on-disk values on every preview refresh -- carry forward
    # whatever the reviewer already had typed instead.
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
        else request.query_params.get("definition", criterion.get("definition", "")),
        "rationale_value": rationale_value
        if rationale_value is not None
        else request.query_params.get("rationale", ""),
    }


@router.get("/criteria/{criterion_id}/edit", response_class=HTMLResponse, response_model=None)
async def criteria_edit_view(
    request: Request, criterion_id: str
) -> HTMLResponse | PlainTextResponse:
    state: AppState = request.app.state.strata
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
    state: AppState = request.app.state.strata
    repo = state.open_repo()
    criterion = criteria_mod.get_criterion(repo, criterion_id)
    if criterion is None:
        return _error(f"unknown criterion {criterion_id!r}", status_code=404)

    form = request.state.form
    direction = str(form.get("direction") or "")
    definition = str(form.get("definition") or "").strip() or None
    raw_rationale = str(form.get("rationale") or "")

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
    state: AppState = request.app.state.strata
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
    state: AppState = request.app.state.strata
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
    unconditionally (docs/spec/04-git-integration.md §2.3), so an empty
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
    gitio.add(repo.root, ["records", "events", "derived"])
    gitio.commit(repo.root, commit_obj.message())


@router.get("/dedup", response_class=HTMLResponse)
async def dedup_queue(request: Request) -> HTMLResponse:
    """Duplicate review queue (docs/spec/11-web-ui.md §2), backed by
    `dedup.engine.preview_dedup`'s non-mutating dry run -- see this
    module's docstring for why `run_dedup` itself can't back a `GET`
    directly. One pair at a time, same skip-list statelessness as `/
    adjudicate`; there is no "undo" here either, since a merge or a
    keep-both decision is a one-way resolution, not a routine re-decision
    (a merge can still be reversed, but only via `strata dedup --undo`,
    same as the CLI's own review flow -- not wired into this sitting's web
    surface).
    """
    state: AppState = request.app.state.strata
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
    state: AppState = request.app.state.strata
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
    """Resolve one pair from the review queue: `merge` (docs/spec/05-
    workflow-import.md §3.6) or `keep` (records a sticky `dedup-distinct`,
    §3.1, so the pair is never raised again). Re-checks the submitted pair
    against a fresh `preview_dedup` rather than trusting the form
    round-trip -- the queue can have moved since the page was rendered,
    the same re-validation `/rescreen`'s `keep-previous` submission does.
    """
    state: AppState = request.app.state.strata
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
    """Searchable/filterable record table (docs/spec/11-web-ui.md §2).
    Read-only, reusing exactly `cli.main.records_list`'s data path
    (`core.filters`'s `--filter` expression language, docs/spec/10-cli.md
    §3) -- unlike `/dedup` (which needed a new non-mutating dry run added
    to `dedup.engine`, see this module's docstring), nothing here needs
    any new preview infrastructure to compute what to show.
    """
    state: AppState = request.app.state.strata
    repo = state.open_repo()
    filter_expr = request.query_params.get("filter") or ""
    records = [
        r for r in records_mod.read_records(repo) if r.get("strata", {}).get("canonical", True)
    ]
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
        {"rows": rows, "filter_expr": filter_expr, "error": error},
    )


@router.get("/records/{record_id}", response_class=HTMLResponse, response_model=None)
async def record_detail_view(request: Request, record_id: str) -> HTMLResponse | PlainTextResponse:
    """Record detail + provenance timeline (`strata why`'s data,
    `core.provenance.build_provenance`)."""
    state: AppState = request.app.state.strata
    repo = state.open_repo()
    record = records_mod.get_record(repo, record_id)
    if record is None:
        return _error(f"unknown record {record_id!r}", status_code=404)
    provenance = provenance_mod.build_provenance(repo, record_id)
    return _render(
        request,
        "record_detail.html",
        {
            "record": record,
            "authors": _author_display(record),
            "year": _record_year(record),
            "provenance": provenance,
        },
    )


# ----------------------------------------------------------------- history


@router.get("/history", response_class=HTMLResponse)
async def history_view(request: Request) -> HTMLResponse:
    """Domain-level history read through `Strata-` commit trailers
    (`strata log`'s data, `core.logcmd.domain_log`) -- never raw commit
    messages, matching that module's own framing."""
    state: AppState = request.app.state.strata
    repo = state.open_repo()
    stage = request.query_params.get("stage") or None
    actor = request.query_params.get("actor") or None
    commits = logcmd_mod.domain_log(repo, stage=stage, actor=actor)
    return _render(request, "history.html", {"commits": commits, "stage": stage, "actor": actor})
