"""Correcting a record, adding a criterion, assigning reviewers:
openspec:web-ui#correcting-a-record, openspec:web-ui#adding-a-criterion,
openspec:web-ui#assigning-reviewers.

A thin adapter, like every route module: each handler reads a form, refuses what cannot be
recorded *before* anything is written, calls the operation `strata fix`, `strata criteria add` or
`strata assign` calls (`strata.core.operations`) and renders the outcome. What a correction, a
criterion or an assignment *is* is decided there, so a screen and its command record the same
thing.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse

from strata.core import actor as actor_mod
from strata.core import fieldedit as fieldedit_mod
from strata.core import operations as ops
from strata.core import records as records_mod
from strata.core.commit import RationaleRejectedError
from strata.core.repo import LockTimeoutError, Repo
from strata.core.validate import SchemaValidationError
from strata.protocol import criteria as criteria_mod
from strata.protocol import screening as screening_mod
from strata.web.common import go
from strata.web.common import state_of as _state
from strata.web.routes import _error, _render, record_detail_context

router = APIRouter()

_PREVIEW_TITLES = 5


# ------------------------------------------------------------------------------- correct a record


@router.post("/records/{record_id}/fix", response_model=None)
def record_fix(
    request: Request, record_id: str
) -> HTMLResponse | RedirectResponse | PlainTextResponse:
    state = _state(request)
    repo = state.open_repo()
    record = records_mod.get_record(repo, record_id)
    if record is None:
        return _error(f"unknown record {record_id!r}", status_code=404)
    form = request.state.form
    values = {
        "field": str(form.get("field") or ""),
        "value": str(form.get("value") or ""),
        "rationale": str(form.get("rationale") or ""),
    }

    def refuse(message: str, status_code: int = 422) -> HTMLResponse:
        return _render(
            request,
            "record_detail.html",
            record_detail_context(state, repo, record, error=message, fix_values=values),
            status_code=status_code,
        )

    try:
        changes = records_mod.preview_amendment(
            repo, record_id=record_id, field=values["field"], value=values["value"]
        )
    except (fieldedit_mod.FixFieldError, records_mod.RecordNotFoundError) as exc:
        return refuse(str(exc))
    if not changes:
        return go(f"/records/{record_id}?unchanged=1")  # the record has that value: nothing to say
    problem = ops.rationale_problem(repo, values["rationale"])
    if problem is not None:
        return refuse(problem)
    try:
        ops.amend_record(
            repo,
            record_id=record_id,
            field=values["field"],
            value=values["value"],
            actor=state.actor,
            rationale=values["rationale"].strip() or None,
        )
    except (
        fieldedit_mod.FixFieldError,
        records_mod.RecordNotFoundError,
        RationaleRejectedError,
    ) as exc:
        return refuse(str(exc))
    except LockTimeoutError as exc:
        return _error(str(exc), status_code=503)
    return go(f"/records/{record_id}")


# ------------------------------------------------------------------------------- add a criterion


def _criterion_form(
    request: Request,
    repo: Repo,
    values: dict[str, Any],
    *,
    error: str | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    state = _state(request)
    return _render(
        request,
        "criteria_new.html",
        {
            "values": values,
            "stages": screening_mod.configured_stages(repo),
            "kinds": (("inclusion", "Includes papers"), ("exclusion", "Excludes papers")),
            "version": criteria_mod.read_criteria_doc(repo)["version"],
            "session_token": state.session_token,
            "error": error,
        },
        status_code=status_code,
    )


@router.get("/criteria/new", response_class=HTMLResponse)
def criterion_new(request: Request) -> HTMLResponse:
    repo = _state(request).open_repo()
    values = {"kind": "", "label": "", "definition": "", "applies_at": [], "rationale": ""}
    return _criterion_form(request, repo, values)


@router.post("/criteria", response_model=None)
def criterion_create(request: Request) -> HTMLResponse | RedirectResponse | PlainTextResponse:
    state = _state(request)
    repo = state.open_repo()
    form = request.state.form
    values: dict[str, Any] = {
        "kind": str(form.get("kind") or ""),
        "label": str(form.get("label") or ""),
        "definition": str(form.get("definition") or ""),
        "applies_at": [str(v) for v in form.getlist("applies_at")],
        "rationale": str(form.get("rationale") or ""),
    }

    def refuse(message: str, status_code: int = 422) -> HTMLResponse:
        return _criterion_form(request, repo, values, error=message, status_code=status_code)

    # A criterion's rationale is recorded in its own event, so it is required whatever
    # `git.require_rationale` says (openspec:criteria-management).
    problem = ops.rationale_problem(repo, values["rationale"], always=True)
    if problem is not None:
        return refuse(problem)
    if not values["kind"]:
        return refuse("Say whether this criterion includes or excludes papers.")
    try:
        added = ops.add_criterion(
            repo,
            kind=values["kind"],
            label=values["label"].strip(),
            definition=values["definition"].strip(),
            applies_at=values["applies_at"],
            actor=state.actor,
            rationale=values["rationale"],
        )
    except (criteria_mod.CriteriaError, SchemaValidationError, RationaleRejectedError) as exc:
        return refuse(str(exc))
    except LockTimeoutError as exc:
        return _error(str(exc), status_code=503)
    return go(f"/criteria?added={added.criterion['id']}")


# ----------------------------------------------------------------------- assign reviewers


def _assign_page(
    request: Request,
    repo: Repo,
    stage: str,
    *,
    filter_expr: str,
    chosen: list[str],
    rationale: str,
    error: str | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    """The assignment screen: who is queued now, what a filter would match, and the form."""
    state = _state(request)
    actors = actor_mod.active_actors(repo)
    all_ids = ops.matching_record_ids(repo)
    preview: dict[str, Any] | None = None
    filter_error: str | None = None
    if filter_expr.strip():
        try:
            matched = ops.matching_record_ids(repo, filter_expr)
        except ops.FilterError as exc:
            filter_error = f"invalid filter: {exc.detail}"
            if exc.record_id is not None:
                filter_error = f"the filter failed on record {exc.record_id}: {exc.detail}"
        else:
            by_id = {r["id"]: r for r in records_mod.read_records(repo)}
            preview = {
                "count": len(matched),
                "titles": [by_id[i].get("title") or i for i in matched[:_PREVIEW_TITLES]],
            }
    queues = [
        {
            "handle": a["handle"],
            "name": a.get("name") or a["handle"],
            "waiting": len(screening_mod.stage_queue(repo, stage, a["handle"])),
        }
        for a in actors
    ]
    return _render(
        request,
        "assign.html",
        {
            "stage": stage,
            "total": len(all_ids),
            "actors": actors,
            "queues": queues,
            "filter_expr": filter_expr,
            "filter_error": filter_error,
            "preview": preview,
            "chosen": chosen,
            "rationale": rationale,
            "error": error,
            "done": request.query_params.get("done") == "1",
            "session_token": state.session_token,
        },
        status_code=status_code,
    )


def _known_stage(repo: Repo, stage: str) -> PlainTextResponse | None:
    if stage not in screening_mod.configured_stages(repo):
        return _error(
            f"unknown stage {stage!r}; configured stages are "
            f"{screening_mod.configured_stages(repo)!r}",
            status_code=404,
        )
    return None


@router.get("/assign/{stage}", response_class=HTMLResponse, response_model=None)
def assign_view(request: Request, stage: str) -> HTMLResponse | PlainTextResponse:
    repo = _state(request).open_repo()
    unknown = _known_stage(repo, stage)
    if unknown is not None:
        return unknown
    return _assign_page(
        request,
        repo,
        stage,
        filter_expr=request.query_params.get("filter") or "",
        chosen=[],
        rationale="",
    )


@router.post("/assign/{stage}", response_model=None)
def assign_submit(
    request: Request, stage: str
) -> HTMLResponse | RedirectResponse | PlainTextResponse:
    state = _state(request)
    repo = state.open_repo()
    unknown = _known_stage(repo, stage)
    if unknown is not None:
        return unknown
    form = request.state.form
    filter_expr = str(form.get("filter") or "")
    chosen = [str(v) for v in form.getlist("actors")]
    rationale = str(form.get("rationale") or "")

    def refuse(message: str, status_code: int = 422) -> HTMLResponse:
        return _assign_page(
            request,
            repo,
            stage,
            filter_expr=filter_expr,
            chosen=chosen,
            rationale=rationale,
            error=message,
            status_code=status_code,
        )

    problem = ops.rationale_problem(repo, rationale)
    if problem is not None:
        return refuse(problem)
    if not chosen:
        return refuse("Choose at least one reviewer.")
    try:
        ops.assign_reviewers(
            repo,
            stage=stage,
            actors=chosen,
            actor=state.actor,
            filter_expr=filter_expr.strip() or None,
            rationale=rationale.strip() or None,
        )
    except ops.FilterError as exc:
        return refuse(f"invalid filter: {exc.detail}")
    except (screening_mod.ScreeningError, RationaleRejectedError) as exc:
        return refuse(str(exc))
    except LockTimeoutError as exc:
        return _error(str(exc), status_code=503)
    return go(f"/assign/{stage}?done=1")
