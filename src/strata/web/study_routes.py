"""Grouping reports into studies in the browser: openspec:web-ui#study-grouping-screen.

A thin adapter, like every route module: it reads a form, refuses what cannot be recorded before
anything is written, calls the operations `strata studies --group` and `--split` call
(`strata.core.operations`) and renders the result.

Viewing the page records nothing. The suggestions it shows (a shared trial registration, a
follow-up report, a paper that says it ran several experiments) are evidence for a person to weigh;
only a form that person submits, with a rationale, records a decision
(openspec:study-grouping).
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse

from strata.core import ids as ids_mod
from strata.core import operations as ops
from strata.core import records as records_mod
from strata.core.commit import RationaleRejectedError
from strata.core.repo import LockTimeoutError, Repo
from strata.core.validate import SchemaValidationError
from strata.protocol import studies as studies_mod
from strata.web.common import go
from strata.web.common import state_of as _state
from strata.web.routes import _error, _render

router = APIRouter()

#: A sanity limit on the form; a paper reporting more experiments than this is unusual.
_MAX_SPLIT = 20


def _studies_page(
    request: Request, repo: Repo, *, error: str | None = None, status_code: int = 200
) -> HTMLResponse:
    included = studies_mod.included_reports(repo)
    current = studies_mod.study_map(repo, reports=included)
    found = studies_mod.suggestions(repo)
    records = records_mod.index_by_id(records_mod.read_records(repo))

    def describe(report: str) -> dict[str, str]:
        record = records.get(ids_mod.record_id_for_report(report), {})
        return {
            "report": report,
            "citation": records_mod.short_citation(record),
            "title": str(record.get("title") or ""),
        }

    return _render(
        request,
        "studies.html",
        {
            "report_count": len(included),
            "study_count": len(current.members),
            "reports": [describe(r) for r in included],
            "groupings": [
                {"reports": [describe(r) for r in g.reports], "evidence": list(g.evidence)}
                for g in found.groupings
            ],
            "splits": [
                {**describe(s.report), "parts": s.parts, "evidence": s.evidence}
                for s in found.splits
            ],
            "studies": [
                {"id": study, "reports": [describe(r) for r in members]}
                for study, members in sorted(current.members.items())
            ],
            "error": error,
            "done": request.query_params.get("done") == "1",
            "max_split": _MAX_SPLIT,
            "session_token": _state(request).session_token,
        },
        status_code=status_code,
    )


@router.get("/studies", response_class=HTMLResponse)
def studies_view(request: Request) -> HTMLResponse:
    return _studies_page(request, _state(request).open_repo())


@router.post("/studies/group", response_model=None)
def studies_group(request: Request) -> HTMLResponse | RedirectResponse | PlainTextResponse:
    state = _state(request)
    repo = state.open_repo()
    form = request.state.form
    reports = [str(v) for v in form.getlist("reports")]
    rationale = str(form.get("rationale") or "")

    def refuse(message: str) -> HTMLResponse:
        return _studies_page(request, repo, error=message, status_code=422)

    # A grouping needs a rationale whatever `git.require_rationale` says.
    problem = ops.rationale_problem(repo, rationale, always=True)
    if problem is not None:
        return refuse(problem)
    if len(set(reports)) < 2:
        return refuse("Choose at least two reports to group into one study.")
    try:
        ops.group_reports(repo, reports=reports, actor=state.actor, rationale=rationale)
    except (studies_mod.StudyError, SchemaValidationError, RationaleRejectedError) as exc:
        return refuse(str(exc))
    except LockTimeoutError as exc:
        return _error(str(exc), status_code=503)
    return go("/studies?done=1")


@router.post("/studies/split", response_model=None)
def studies_split(request: Request) -> HTMLResponse | RedirectResponse | PlainTextResponse:
    state = _state(request)
    repo = state.open_repo()
    form = request.state.form
    report = str(form.get("report") or "")
    raw_parts = str(form.get("parts") or "").strip()
    rationale = str(form.get("rationale") or "")

    def refuse(message: str) -> HTMLResponse:
        return _studies_page(request, repo, error=message, status_code=422)

    problem = ops.rationale_problem(repo, rationale, always=True)
    if problem is not None:
        return refuse(problem)
    if not raw_parts.isdigit() or not 2 <= int(raw_parts) <= _MAX_SPLIT:
        return refuse(f"Say how many studies the report should be split into (2 to {_MAX_SPLIT}).")
    parts = int(raw_parts)
    try:
        ops.split_report(repo, report=report, parts=parts, actor=state.actor, rationale=rationale)
    except (studies_mod.StudyError, SchemaValidationError, RationaleRejectedError) as exc:
        return refuse(str(exc))
    except LockTimeoutError as exc:
        return _error(str(exc), status_code=503)
    return go("/studies?done=1")
