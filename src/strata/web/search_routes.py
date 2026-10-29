"""Searches and imports in the browser: openspec:web-ui#search-and-import-screens,
openspec:web-ui#review-before-importing, openspec:web-ui#imports-from-other-methods.

A thin adapter, like every route module: it reads a form, calls `strata.core.operations` (the same
operations `strata search add` and `strata import` call) and the import pipeline's own read-only
functions, and renders the result. What a search or an import *is* is decided there.

The flow for a database search with its export:

    POST /searches                    record the search (commit 1), stage the files
    GET  /import/review/<batch>       what each file would do (the pipeline's dry run)
    POST /import/review/<batch>       import each file (one commit apiece), discard the batch

Choices about how to read a file (a workbook's sheet, a CSV's columns) are made on the review page
and carried as `sheet_<i>` / `map_<i>_<field>` fields, so the server holds no state about them:
every request is a function of the form and the staged files, as the rest of the web interface is.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from starlette.datastructures import UploadFile

from strata.core import actor as actor_mod
from strata.core import operations as ops
from strata.core.commit import RationaleRejectedError
from strata.core.repo import LockTimeoutError, Repo
from strata.core.validate import SchemaValidationError
from strata.ingest import pipeline
from strata.protocol import searches as searches_mod
from strata.web import uploads
from strata.web.app import AppState
from strata.web.common import go as _go
from strata.web.common import state_of as _state
from strata.web.routes import _error, _render

router = APIRouter()

_METHODS = (
    ("citation-searching", "Citation searching (reference lists and forward citations)"),
    ("website", "A website"),
    ("organisation", "An organisation"),
    ("registry", "A trial or study registry"),
    ("contact", "Contact with experts"),
)
_METHOD_LABELS = dict(_METHODS)

_FIELD_LABELS = {
    "title": "Title",
    "author": "Authors",
    "year": "Year",
    "container-title": "Journal",
    "DOI": "DOI",
    "PMID": "PubMed ID",
    "abstract": "Abstract",
    "keyword": "Keywords",
    "volume": "Volume",
    "issue": "Issue",
    "page": "Pages",
    "page-start": "First page",
    "page-end": "Last page",
    "ISBN": "ISBN",
    "URL": "URL",
}
_FIELD_ORDER = [f for f in _FIELD_LABELS if f in pipeline.MAPPABLE_FIELDS] + [
    f for f in pipeline.MAPPABLE_FIELDS if f not in _FIELD_LABELS
]

_SEARCH_FIELDS = (
    "database",
    "platform",
    "executed",
    "executed_by",
    "query",
    "hits",
    "notes",
    "peer_reviewed_by",
    "rationale",
    "supersedes",
)
_REJECTED_SHOWN = 50


# ------------------------------------------------------------------------------------ helpers


def _context(request: Request, extra: dict[str, Any]) -> dict[str, Any]:
    state = _state(request)
    return {
        "session_token": state.session_token,
        "max_upload_mb": state.max_upload_bytes // uploads.MIB,
        **extra,
    }


def _uploaded_files(form: Any) -> list[tuple[str, Any]]:
    """The files in a submitted form; a browser sends an empty part when none was chosen."""
    return [
        (item.filename, item.file)
        for item in form.getlist("files")
        if isinstance(item, UploadFile) and item.filename
    ]


def _stage_literature(
    state: AppState, uploaded: list[tuple[str, Any]], context: dict[str, Any]
) -> uploads.StagedBatch:
    """Stage the files and turn the batch away, whole, if any file is not a bibliographic export."""
    batch = state.staging.stage(uploaded, context=context)
    try:
        for staged in batch.files:
            uploads.check_literature_file(staged.path, staged.label)
    except uploads.UploadRefused:
        state.staging.discard(batch.id)
        raise
    return batch


def _size_text(size: int) -> str:
    if size >= uploads.MIB:
        return f"{size / uploads.MIB:.1f} MB"
    return f"{max(size, 1) / 1024:.0f} KB"


def _open_batch(
    state: AppState, batch_id: str
) -> tuple[uploads.StagedBatch | None, PlainTextResponse | None]:
    try:
        return state.staging.open(batch_id), None
    except uploads.ExpiredBatch as exc:
        return None, _error(str(exc), status_code=410)
    except uploads.UnknownBatch as exc:
        return None, _error(str(exc), status_code=404)


# ------------------------------------------------------------------------------ search list


@router.get("/searches", response_class=HTMLResponse)
def searches_index(request: Request) -> HTMLResponse:
    repo = _state(request).open_repo()
    rows = []
    for overview in pipeline.search_overview(repo):
        rows.append(
            {
                **overview.search,
                "query_pending": overview.query_pending,
                "replaced_by": overview.replaced_by,
                "import_count": len(overview.imports),
                "records": sum(int(m["records_created"]) for m in overview.imports),
            }
        )
    return _render(request, "searches.html", _context(request, {"searches": rows}))


def _search_page(
    request: Request,
    repo: Repo,
    search_id: str,
    *,
    error: str | None = None,
    status_code: int = 200,
) -> HTMLResponse | PlainTextResponse:
    for overview in pipeline.search_overview(repo):
        if overview.search["id"] == search_id:
            return _render(
                request,
                "search_detail.html",
                _context(
                    request,
                    {
                        "search": overview.search,
                        "query_pending": overview.query_pending,
                        "replaced_by": overview.replaced_by,
                        "imports": overview.imports,
                        "error": error,
                    },
                ),
                status_code=status_code,
            )
    return _error(f"no search {search_id!r}", status_code=404)


@router.get("/searches/new", response_class=HTMLResponse)
def search_new(request: Request) -> HTMLResponse:
    state = _state(request)
    repo = state.open_repo()
    values = _blank_values(state)
    prior_id = request.query_params.get("supersedes")
    prior = searches_mod.get_search(repo, prior_id) if prior_id else None
    if prior is not None:
        values.update(
            database=str(prior["database"]),
            platform=str(prior["platform"]),
            notes=str(prior.get("notes") or ""),
            peer_reviewed_by=str(prior.get("peer_reviewed_by") or ""),
            supersedes=str(prior["id"]),
        )
        if prior["query"] != searches_mod.PENDING_QUERY:
            values["query"] = str(prior["query"])
    return _search_form(request, repo, values)


@router.get("/searches/{search_id}", response_class=HTMLResponse, response_model=None)
def search_detail(request: Request, search_id: str) -> HTMLResponse | PlainTextResponse:
    return _search_page(request, _state(request).open_repo(), search_id)


# --------------------------------------------------------------------------- record a search


def _blank_values(state: AppState) -> dict[str, str]:
    values = {name: "" for name in _SEARCH_FIELDS}
    values.update(executed=date.today().isoformat(), executed_by=state.actor)
    return values


def _search_form(
    request: Request,
    repo: Repo,
    values: dict[str, str],
    *,
    error: str | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    return _render(
        request,
        "search_new.html",
        _context(
            request,
            {"values": values, "actors": actor_mod.active_actors(repo), "error": error},
        ),
        status_code=status_code,
    )


@router.post("/searches", response_model=None)
def search_create(request: Request) -> HTMLResponse | RedirectResponse | PlainTextResponse:
    state = _state(request)
    repo = state.open_repo()
    form = request.state.form
    values = {name: str(form.get(name) or "") for name in _SEARCH_FIELDS}

    def refuse(message: str, status_code: int = 422) -> HTMLResponse:
        return _search_form(request, repo, values, error=message, status_code=status_code)

    if not values["database"].strip() or not values["platform"].strip():
        return refuse("Say which database you searched and which platform you used.")
    problem = ops.rationale_problem(repo, values["rationale"])
    if problem is not None:
        return refuse(problem)
    hits: int | None = None
    if values["hits"].strip():
        if not values["hits"].strip().isdigit():
            return refuse("The number of hits must be a whole number.")
        hits = int(values["hits"].strip())

    staged: uploads.StagedBatch | None = None
    uploaded = _uploaded_files(form)
    try:
        if uploaded:
            staged = _stage_literature(state, uploaded, {})
        recorded = ops.record_search(
            repo,
            database=values["database"].strip(),
            platform=values["platform"].strip(),
            executed=values["executed"].strip(),
            executed_by=values["executed_by"].strip(),
            query=values["query"],
            hits=hits,
            export_files=[f.name for f in staged.files] if staged else None,
            peer_reviewed_by=values["peer_reviewed_by"].strip() or None,
            notes=values["notes"].strip() or None,
            supersedes=values["supersedes"].strip() or None,
            rationale=values["rationale"].strip() or None,
        )
    except uploads.UploadRefused as exc:
        return refuse(
            f"{exc.message} Nothing was recorded; choose the files again.", exc.status_code
        )
    except (searches_mod.SearchError, SchemaValidationError, RationaleRejectedError) as exc:
        if staged is not None:
            state.staging.discard(staged.id)
        return refuse(str(exc))
    except LockTimeoutError as exc:
        if staged is not None:
            state.staging.discard(staged.id)
        return _error(str(exc), status_code=503)

    search_id = str(recorded.record["id"])
    if staged is not None:
        state.staging.set_context(staged.id, {"search": search_id})
        return _go(f"/import/review/{staged.id}")
    return _go(f"/searches/{quote(search_id, safe='')}")


@router.post("/searches/{search_id}/files", response_model=None)
def search_add_files(
    request: Request, search_id: str
) -> HTMLResponse | RedirectResponse | PlainTextResponse:
    state = _state(request)
    repo = state.open_repo()
    if searches_mod.get_search(repo, search_id) is None:
        return _error(f"no search {search_id!r}", status_code=404)
    uploaded = _uploaded_files(request.state.form)
    if not uploaded:
        return _search_page(
            request, repo, search_id, error="Choose at least one file.", status_code=422
        )
    try:
        staged = _stage_literature(state, uploaded, {"search": search_id})
    except uploads.UploadRefused as exc:
        return _search_page(
            request, repo, search_id, error=exc.message, status_code=exc.status_code
        )
    return _go(f"/import/review/{staged.id}")


# ------------------------------------------------------------------ other methods of finding


def _import_new_page(
    request: Request, *, via: str = "", error: str | None = None, status_code: int = 200
) -> HTMLResponse:
    return _render(
        request,
        "import_new.html",
        _context(request, {"methods": _METHODS, "via": via, "error": error}),
        status_code=status_code,
    )


@router.get("/import", response_class=HTMLResponse)
def import_new(request: Request) -> HTMLResponse:
    return _import_new_page(request)


@router.post("/import", response_model=None)
def import_create(request: Request) -> HTMLResponse | RedirectResponse:
    state = _state(request)
    repo = state.open_repo()
    form = request.state.form
    via = str(form.get("via") or "").strip()
    try:
        # The same check, in the same words, that `strata import` makes before it reads a file.
        pipeline.validate_source(repo, state.actor, None, via or None)
    except pipeline.ImportPipelineError as exc:
        return _import_new_page(request, via=via, error=str(exc), status_code=422)
    uploaded = _uploaded_files(form)
    if not uploaded:
        return _import_new_page(
            request, via=via, error="Choose at least one file.", status_code=422
        )
    try:
        staged = _stage_literature(state, uploaded, {"via": via})
    except uploads.UploadRefused as exc:
        return _import_new_page(request, via=via, error=exc.message, status_code=exc.status_code)
    return _go(f"/import/review/{staged.id}")


# ------------------------------------------------------------------------------------ review


def _selection(source: Mapping[str, Any], index: int) -> tuple[str | None, dict[str, str] | None]:
    """The sheet and column mapping chosen for file `index` (`sheet_<i>`, `map_<i>_<field>`)."""
    sheet = str(source.get(f"sheet_{index}") or "").strip() or None
    chosen = {
        field: str(source[f"map_{index}_{field}"])
        for field in _FIELD_ORDER
        if str(source.get(f"map_{index}_{field}") or "").strip()
    }
    return sheet, chosen or None


def _source_of(repo: Repo, batch: uploads.StagedBatch) -> tuple[dict[str, Any] | None, str | None]:
    """The search (if any) and the method (if any) a batch belongs to."""
    search_id = batch.context.get("search")
    search = searches_mod.get_search(repo, search_id) if search_id else None
    return search, batch.context.get("via")


def _review_items(
    repo: Repo, state: AppState, batch: uploads.StagedBatch, source: Mapping[str, Any]
) -> list[dict[str, Any]]:
    search, via = _source_of(repo, batch)
    items: list[dict[str, Any]] = []
    for index, staged in enumerate(batch.files):
        sheet, mapping = _selection(source, index)
        item: dict[str, Any] = {
            "index": index,
            "label": staged.label,
            "size_text": _size_text(staged.size),
            "layout": None,
            "outcome": None,
            "error": None,
            "needs_mapping": False,
            "mapping": mapping or {},
            "sheet": sheet,
            "shown_rejected": [],
            "hidden_rejected": 0,
            "importable": False,
        }
        items.append(item)
        try:
            layout = pipeline.describe_table(staged.path, sheet=sheet)
        except pipeline.ImportPipelineError as exc:
            item["error"] = str(exc)
            continue
        item["layout"] = layout
        item["needs_mapping"] = layout is not None and layout.platform is None
        try:
            outcome = pipeline.import_file(
                repo,
                staged.path,
                imported_by=state.actor,
                search_id=search["id"] if search else None,
                via=via,
                mapping=mapping,
                sheet=sheet,
                dry_run=True,
            )
        except pipeline.ImportPipelineError as exc:
            item["error"] = str(exc)
            continue
        item["outcome"] = outcome
        item["shown_rejected"] = outcome.rejected[:_REJECTED_SHOWN]
        item["hidden_rejected"] = max(len(outcome.rejected) - _REJECTED_SHOWN, 0)
        item["importable"] = not outcome.already_imported
    return items


def _review_page(
    request: Request,
    repo: Repo,
    batch: uploads.StagedBatch,
    source: Mapping[str, Any],
    *,
    rationale: str = "",
    error: str | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    state = _state(request)
    search, via = _source_of(repo, batch)
    items = _review_items(repo, state, batch, source)
    carried: list[tuple[str, str]] = []
    for item in items:
        if item["sheet"]:
            carried.append((f"sheet_{item['index']}", item["sheet"]))
        carried.extend((f"map_{item['index']}_{f}", c) for f, c in item["mapping"].items())
    importable = sum(1 for item in items if item["importable"])
    return _render(
        request,
        "import_review.html",
        _context(
            request,
            {
                "batch": batch,
                "search": search,
                "via_label": _METHOD_LABELS.get(via or "", via or ""),
                "items": items,
                "has_choices": any(
                    i["layout"] and (len(i["layout"].sheets or []) > 1 or i["needs_mapping"])
                    for i in items
                ),
                "mappable_fields": _FIELD_ORDER,
                "field_labels": _FIELD_LABELS,
                "carried": carried,
                "can_import": importable > 0,
                "importable_count": importable,
                "rationale": rationale,
                "error": error,
            },
        ),
        status_code=status_code,
    )


@router.get("/import/review/{batch_id}", response_model=None)
def import_review(request: Request, batch_id: str) -> HTMLResponse | PlainTextResponse:
    state = _state(request)
    batch, refusal = _open_batch(state, batch_id)
    if batch is None:
        assert refusal is not None
        return refusal
    return _review_page(request, state.open_repo(), batch, request.query_params)


# ----------------------------------------------------------------------------------- confirm


def _result(
    label: str, *, error: str | None = None, result: ops.ImportResult | None = None
) -> dict[str, Any]:
    row: dict[str, Any] = {"label": label, "error": error}
    if result is not None:
        outcome = result.outcome
        row.update(
            already_imported=outcome.already_imported,
            import_id=outcome.import_id,
            records_created=outcome.records_created,
            existing_ids_appended=outcome.existing_ids_appended,
            rows_rejected=outcome.rows_rejected,
        )
    return row


@router.post("/import/review/{batch_id}", response_model=None)
def import_confirm(request: Request, batch_id: str) -> HTMLResponse | PlainTextResponse:
    state = _state(request)
    repo = state.open_repo()
    batch, refusal = _open_batch(state, batch_id)
    if batch is None:
        assert refusal is not None
        return refusal
    form = request.state.form
    raw_rationale = str(form.get("rationale") or "")
    selections = {key: value for key, value in form.items() if isinstance(value, str)}

    problem = ops.rationale_problem(repo, raw_rationale)
    if problem is not None:
        return _review_page(
            request,
            repo,
            batch,
            selections,
            rationale=raw_rationale,
            error=problem,
            status_code=422,
        )

    search, via = _source_of(repo, batch)
    results: list[dict[str, Any]] = []
    for index, staged in enumerate(batch.files):
        sheet, mapping = _selection(selections, index)
        try:
            imported = ops.import_file(
                repo,
                staged.path,
                imported_by=state.actor,
                search_id=search["id"] if search else None,
                via=via,
                mapping=mapping,
                sheet=sheet,
                rationale=raw_rationale.strip() or None,
            )
        except pipeline.ImportPipelineError as exc:
            results.append(_result(staged.label, error=str(exc)))
        except LockTimeoutError as exc:
            # Nothing of this file was written; the batch is kept so the person can try again.
            return _review_page(
                request,
                repo,
                batch,
                selections,
                rationale=raw_rationale,
                error=str(exc),
                status_code=503,
            )
        else:
            results.append(_result(staged.label, result=imported))

    state.staging.discard(batch.id)
    return _render(
        request,
        "import_results.html",
        _context(
            request,
            {
                "search": search,
                "via_label": _METHOD_LABELS.get(via or "", via or ""),
                "results": results,
                "error": None,
            },
        ),
    )


@router.post("/import/review/{batch_id}/discard", response_model=None)
def import_discard(request: Request, batch_id: str) -> RedirectResponse:
    state = _state(request)
    batch, _refusal = _open_batch(state, batch_id)
    state.staging.discard(batch_id)
    search_id = batch.context.get("search") if batch is not None else None
    if search_id:
        return _go(f"/searches/{quote(str(search_id), safe='')}")
    return _go("/import")
