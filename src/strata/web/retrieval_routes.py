"""Full-text retrieval in the browser: openspec:web-ui#full-text-retrieval-screen.

A thin adapter, like every route module: it reads a form, refuses what cannot be recorded before
anything is written, calls the operation `strata retrieve --report --outcome` calls
(`strata.core.operations`) and renders the result.

The screen records *outcomes* only. It has no file control and no path field: strata does not
store full texts, and a path typed into a web form would name a file on the server, which is
the one machine the person at the browser may not be sitting at.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse

from strata.core import fulltext as fulltext_mod
from strata.core import ids as ids_mod
from strata.core import operations as ops
from strata.core import records as records_mod
from strata.core.commit import RationaleRejectedError
from strata.core.repo import LockTimeoutError, Repo
from strata.core.validate import SchemaValidationError
from strata.protocol import retrieval as retrieval_mod
from strata.web.common import go
from strata.web.common import state_of as _state
from strata.web.routes import _error, _render

router = APIRouter()

#: What a person can record for a sought report, with the words the page uses.
_OUTCOMES = (
    ("retrieved", "I have the document"),
    ("ill-requested", "Requested through interlibrary loan"),
    ("not-retrieved", "It cannot be retrieved"),
    ("sought", "Not yet: put it back in the queue"),
)
_STATUS_WORDS = {
    "sought": "waiting",
    "ill-requested": "interlibrary loan requested",
    "retrieved": "retrieved",
    "not-retrieved": "not retrievable",
}
_REASON_WORDS = {
    "no-access": "No access",
    "not-found": "Cannot be found",
    "retracted": "Retracted",
    "language": "Language barrier",
    "no-response-from-author": "No response from the author",
    "other": "Other (say what happened)",
}


def _report_row(report: str, record: dict[str, Any], status: str) -> dict[str, Any]:
    return {
        "report": report,
        "citation": records_mod.short_citation(record),
        "title": record.get("title") or "",
        "status": status,
        "status_words": _STATUS_WORDS.get(status, status),
    }


@router.get("/retrieve", response_class=HTMLResponse)
def retrieve_index(request: Request) -> HTMLResponse:
    repo = _state(request).open_repo()
    records = records_mod.index_by_id(records_mod.read_records(repo))
    states = retrieval_mod.retrieval_states(repo)
    rows = [
        _report_row(
            report,
            records.get(ids_mod.record_id_for_report(report), {}),
            retrieval_mod.status_of(states, report),
        )
        for report in retrieval_mod.sought_reports(repo)
    ]
    counts = retrieval_mod.retrieval_counts(repo)
    outstanding = [r for r in rows if r["status"] in ("sought", "ill-requested")]
    settled = [r for r in rows if r not in outstanding]
    return _render(
        request,
        "retrieve.html",
        {"counts": counts, "outstanding": outstanding, "settled": settled},
    )


def _report_page(
    request: Request,
    repo: Repo,
    report: str,
    *,
    values: dict[str, str],
    error: str | None = None,
    status_code: int = 200,
) -> HTMLResponse | PlainTextResponse:
    if report not in set(retrieval_mod.sought_reports(repo)):
        return _error(f"{report!r} is not a report sought", status_code=404)
    record = records_mod.get_record(repo, ids_mod.record_id_for_report(report)) or {}
    status = retrieval_mod.status_of(retrieval_mod.retrieval_states(repo), report)
    return _render(
        request,
        "retrieve_report.html",
        {
            "report": report,
            "record": record,
            "citation": records_mod.short_citation(record),
            "status_words": _STATUS_WORDS.get(status, status),
            "outcomes": _OUTCOMES,
            "versions": fulltext_mod.VERSIONS,
            "reasons": [(r, _REASON_WORDS.get(r, r)) for r in retrieval_mod.NOT_RETRIEVED_REASONS],
            "values": values,
            "error": error,
            "session_token": _state(request).session_token,
        },
        status_code=status_code,
    )


@router.get("/retrieve/{report}", response_class=HTMLResponse, response_model=None)
def retrieve_report(request: Request, report: str) -> HTMLResponse | PlainTextResponse:
    values = {
        "outcome": "",
        "source": "institutional-access",
        "version": "version-of-record",
        "reason": "",
        "reason_text": "",
        "rationale": "",
    }
    return _report_page(request, _state(request).open_repo(), report, values=values)


@router.post("/retrieve/{report}", response_model=None)
def retrieve_record(
    request: Request, report: str
) -> HTMLResponse | RedirectResponse | PlainTextResponse:
    state = _state(request)
    repo = state.open_repo()
    form = request.state.form
    values = {
        name: str(form.get(name) or "")
        for name in ("outcome", "source", "version", "reason", "reason_text", "rationale")
    }

    def refuse(message: str, status_code: int = 422) -> HTMLResponse | PlainTextResponse:
        return _report_page(
            request, repo, report, values=values, error=message, status_code=status_code
        )

    problem = ops.rationale_problem(repo, values["rationale"])
    if problem is not None:
        return refuse(problem)
    outcome = values["outcome"]
    if not outcome:
        return refuse("Say what happened to this document.")

    def given(name: str, *applies_to: str) -> str | None:
        """A field, if it belongs to this outcome (a reason has no place on a document in hand)."""
        return values[name].strip() or None if outcome in applies_to else None

    try:
        ops.record_retrieval(
            repo,
            report=report,
            outcome=outcome,
            actor=state.actor,
            source=given("source", "retrieved", "ill-requested"),
            version=given("version", "retrieved"),
            reason=given("reason", "not-retrieved"),
            reason_text=given("reason_text", "not-retrieved"),
            rationale=values["rationale"].strip() or None,
        )
    except (
        retrieval_mod.RetrievalError,
        SchemaValidationError,
        RationaleRejectedError,
    ) as exc:
        return refuse(str(exc))
    except LockTimeoutError as exc:
        return _error(str(exc), status_code=503)
    return go("/retrieve")
