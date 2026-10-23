"""Extraction, reconciliation and risk-of-bias screens: openspec:web-ui (M3 additions).

`/extract/<study>` is the coding form, `/extract/<study>/reconcile` the field-by-field
reconciliation, and `/rob/<study>` the risk-of-bias instrument. Each screen is a thin layer over
the same functions the CLI calls (`extract.records`, `extract.reconcile`, `extract.rob`), so a
reconciliation made here writes exactly the `reconcile` event the CLI would. Like every other
screen they are server-rendered and work with JavaScript off; the optional `keyboard.js` only adds
the one-keystroke jump from a value to its source locator.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse

from strata import gitio
from strata.core import records as records_mod
from strata.core.commit import StructuredCommit
from strata.extract import reconcile as reconcile_mod
from strata.extract import records as extraction_records_mod
from strata.extract import rob as rob_mod
from strata.extract import schema as extraction_schema_mod
from strata.protocol import studies as studies_mod
from strata.web.app import AppState
from strata.web.routes import _dedup_rationale, _error, _redirect, _render

router = APIRouter()

_STUDY_NOT_FOUND = "no included study {study!r}"


def _citation(repo: Any, study: str) -> tuple[str, str]:
    """`(short citation, title)` of the study's first report."""
    from strata.core.ids import record_id_for_report

    reports = studies_mod.study_map(repo).members.get(study, ())
    record = records_mod.get_record(repo, record_id_for_report(reports[0])) if reports else None
    record = record or {}
    return records_mod.short_citation(record), record.get("title") or "(no title)"


def _rationale_required(repo: Any) -> bool:
    return bool(repo.config.get("git", {}).get("require_rationale", True))


def _included(repo: Any, study: str) -> bool:
    return study in studies_mod.study_map(repo).members


def _commit(
    repo: Any, *, op: str, scope: str, summary: str, actor: str, rationale: str | None
) -> None:
    paths = [
        p for p in ("records", "events", "derived", "extraction", "rob") if repo.path(p).exists()
    ]
    if not gitio.has_changes(repo.root, paths):
        return
    commit_obj = StructuredCommit(
        op=op,
        scope=scope,
        summary=summary,
        body=rationale,
        trailers={"Op": op, "Study": scope, "Actor": actor},
    )
    gitio.add(repo.root, paths)
    gitio.commit(repo.root, commit_obj.message())


def _field_rows(schema: Any, record: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    stored = record.get("fields") or {}
    for spec in schema.fields:
        entry = stored.get(spec["name"])
        rows.append(
            {
                "name": spec["name"],
                "label": spec.get("label") or spec["name"],
                "type": spec["type"],
                "required": bool(spec.get("required")),
                "help": spec.get("help"),
                "unit": spec.get("unit"),
                "levels": spec.get("levels") or [],
                "current": _entry_text(entry),
                "source": (entry or {}).get("source") or "",
                "missing": spec["name"] not in stored,
            }
        )
    return rows


def _entry_text(entry: dict[str, Any] | None) -> str:
    if entry is None:
        return ""
    if entry.get("not_reported"):
        return "NR"
    value = entry.get("value")
    text = ", ".join(map(str, value)) if isinstance(value, list) else str(value)
    if entry.get("unit"):
        text += f" {entry['unit']}"
    return text


def _effect_rows(repo: Any, study: str, record: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for effect in record.get("effects") or []:
        key = extraction_records_mod.effect_key(effect)
        result = extraction_records_mod.preview_effect(
            repo,
            study=study,
            design=effect["design"],
            inputs={k: v for k, v in effect.items() if k not in ("design", "outcome")},
            outcome=effect.get("outcome"),
            skip_key=key,
        )
        rows.append(
            {
                "key": key,
                "id": effect.get("id"),
                "outcome": effect.get("outcome"),
                "design": effect["design"],
                "timepoint": effect.get("timepoint") or "",
                "measure": result.computed.measure if result.computed else None,
                "yi": f"{result.computed.yi:.3f}" if result.computed else None,
                "se": f"{result.computed.vi**0.5:.3f}" if result.computed else None,
            }
        )
    return rows


# ---------------------------------------------------------------- extraction


@router.get("/extract", response_class=HTMLResponse, response_model=None)
async def extract_index(request: Request) -> HTMLResponse | PlainTextResponse:
    state: AppState = request.app.state.strata
    repo = state.open_repo()
    try:
        missing = extraction_records_mod.studies_missing(repo, state.actor)
    except extraction_schema_mod.ExtractionSchemaError as exc:
        return _error(str(exc), status_code=404)
    studies = []
    for study in sorted(studies_mod.study_map(repo).members):
        citation, title = _citation(repo, study)
        studies.append(
            {"id": study, "citation": citation, "title": title, "missing": missing.get(study, [])}
        )
    return _render(
        request,
        "extract_index.html",
        {"actor": state.actor, "kind": "extract", "studies": studies},
    )


@router.get("/extract/{study}", response_class=HTMLResponse, response_model=None)
async def extract_study(request: Request, study: str) -> HTMLResponse | PlainTextResponse:
    state: AppState = request.app.state.strata
    repo = state.open_repo()
    if not _included(repo, study):
        return _error(_STUDY_NOT_FOUND.format(study=study), status_code=404)
    try:
        schema = extraction_schema_mod.load_schema(repo)
    except extraction_schema_mod.ExtractionSchemaError as exc:
        return _error(str(exc), status_code=404)

    record = (
        extraction_records_mod.read_record(
            extraction_records_mod.working_path(repo, state.actor, study)
        )
        or {}
    )
    query = request.query_params
    design = query.get("design") or ""
    designs = schema.designs
    preview = None
    inputs: dict[str, str] = {}
    if design in designs:
        inputs = {n: query.get(f"in:{n}", "") for n in designs[design]}
        result = extraction_records_mod.preview_effect(
            repo,
            study=study,
            design=design,
            inputs={k: v for k, v in inputs.items() if v},
            outcome=query.get("outcome") or None,
        )
        preview = {
            "computed": (
                f"{result.computed.measure} = {result.computed.yi:.3f} "
                f"(SE {result.computed.vi**0.5:.3f})"
                if result.computed
                else None
            ),
            "warnings": [{"code": w.code, "message": w.message} for w in result.warnings],
        }
    open_warnings = [
        {"key": key, "code": code, "message": message}
        for key, code, message in extraction_records_mod.open_warnings(repo, study, record)
    ]
    citation, title = _citation(repo, study)
    return _render(
        request,
        "extract.html",
        {
            "actor": state.actor,
            "session_token": state.session_token,
            "study": study,
            "citation": citation,
            "title": title,
            "dual": extraction_records_mod.extraction_mode(repo) == "dual",
            "fields": _field_rows(schema, record),
            "effects": _effect_rows(repo, study, record),
            "designs": {name: list(names) for name, names in designs.items()},
            "outcomes": schema.outcomes,
            "design": design if design in designs else "",
            "outcome": query.get("outcome") or "",
            "timepoint": query.get("timepoint") or "",
            "inputs": inputs,
            "preview": preview,
            "open_warnings": open_warnings,
            "rationale_required": _rationale_required(repo),
        },
    )


@router.post("/extract/{study}", response_model=None)
async def extract_study_submit(
    request: Request, study: str
) -> RedirectResponse | PlainTextResponse:
    state: AppState = request.app.state.strata
    repo = state.open_repo()
    form = request.state.form
    if not _included(repo, study):
        return _error(_STUDY_NOT_FOUND.format(study=study), status_code=404)
    rationale, problem = _dedup_rationale(repo, str(form.get("rationale") or ""))
    if problem:
        return _error(problem, status_code=422)

    saved = 0
    try:
        schema = extraction_schema_mod.load_schema(repo)
        action = str(form.get("action") or "save")
        if action == "ack":
            extraction_records_mod.acknowledge_warning(
                repo,
                study=study,
                effect=str(form.get("effect") or ""),
                code=str(form.get("code") or ""),
                note=str(form.get("note") or ""),
                actor=state.actor,
            )
            saved = 1
        else:
            for spec in schema.fields:
                raw = str(form.get(f"field:{spec['name']}") or "").strip()
                if raw:
                    extraction_records_mod.set_field(
                        repo,
                        study=study,
                        handle=state.actor,
                        name=spec["name"],
                        raw=raw,
                        source=str(form.get(f"source:{spec['name']}") or "").strip() or None,
                    )
                    saved += 1
            design = str(form.get("effect_design") or "")
            if design:
                if design not in schema.designs:
                    return _error(f"design {design!r} is not declared", status_code=422)
                extraction_records_mod.add_effect(
                    repo,
                    study=study,
                    handle=state.actor,
                    outcome=str(form.get("effect_outcome") or ""),
                    design=design,
                    inputs={
                        n: str(form.get(f"in:{n}") or "")
                        for n in schema.designs[design]
                        if str(form.get(f"in:{n}") or "").strip()
                    },
                    timepoint=str(form.get("effect_timepoint") or "").strip() or None,
                    label=str(form.get("effect_label") or "").strip() or None,
                    source=str(form.get("effect_source") or "").strip() or None,
                )
                saved += 1
    except ValueError as exc:
        return _error(str(exc), status_code=422)

    if saved:
        _commit(
            repo,
            op="extract",
            scope=study,
            summary=f"extract {study}"[:60],
            actor=state.actor,
            rationale=rationale,
        )
    return _redirect(f"/extract/{quote(study, safe='')}")


@router.get("/extract/{study}/reconcile", response_class=HTMLResponse, response_model=None)
async def extract_reconcile(request: Request, study: str) -> HTMLResponse | PlainTextResponse:
    state: AppState = request.app.state.strata
    repo = state.open_repo()
    if not _included(repo, study):
        return _error(_STUDY_NOT_FOUND.format(study=study), status_code=404)
    try:
        comparison = reconcile_mod.compare(repo, study)
    except reconcile_mod.ReconcileError as exc:
        return _error(str(exc), status_code=404)
    citation, title = _citation(repo, study)
    return _render(
        request,
        "extract_reconcile.html",
        {
            "actor": state.actor,
            "session_token": state.session_token,
            "study": study,
            "citation": citation,
            "title": title,
            "handles": comparison.handles,
            "items": comparison.items,
            "agreed": [i for i in comparison.items if i.agree and not i.resolved],
        },
    )


@router.post("/extract/{study}/reconcile", response_model=None)
async def extract_reconcile_submit(
    request: Request, study: str
) -> RedirectResponse | PlainTextResponse:
    state: AppState = request.app.state.strata
    repo = state.open_repo()
    form = request.state.form
    if not _included(repo, study):
        return _error(_STUDY_NOT_FOUND.format(study=study), status_code=404)
    rationale, problem = _dedup_rationale(repo, str(form.get("commit_rationale") or ""))
    if problem:
        return _error(problem, status_code=422)
    try:
        if str(form.get("action") or "") == "accept-agreements":
            count = reconcile_mod.accept_agreements(repo, study=study, reconciler=state.actor)
            summary = f"accept {count} agreement(s)"
        else:
            item_id = str(form.get("item") or "")
            reconcile_mod.resolve(
                repo,
                study=study,
                reconciler=state.actor,
                item_id=item_id,
                choice=str(form.get("choice") or ""),
                rationale=str(form.get("rationale") or ""),
                other_value=str(form.get("value") or "").strip() or None,
                source=str(form.get("source") or "").strip() or None,
            )
            summary = f"reconcile {item_id}"
    except reconcile_mod.ReconcileError as exc:
        return _error(str(exc), status_code=422)
    except ValueError as exc:
        return _error(str(exc), status_code=422)
    _commit(
        repo,
        op="reconcile",
        scope=study,
        summary=summary[:60],
        actor=state.actor,
        rationale=rationale,
    )
    return _redirect(f"/extract/{quote(study, safe='')}/reconcile")


# ---------------------------------------------------------------- risk of bias


@router.get("/rob", response_class=HTMLResponse, response_model=None)
async def rob_index(request: Request) -> HTMLResponse | PlainTextResponse:
    state: AppState = request.app.state.strata
    repo = state.open_repo()
    try:
        instrument = rob_mod.load_instrument(repo)
    except rob_mod.RobError as exc:
        return _error(str(exc), status_code=404)
    studies = []
    for study in sorted(studies_mod.study_map(repo).members):
        citation, title = _citation(repo, study)
        assessment = rob_mod.read_assessment(rob_mod.working_path(repo, state.actor, study)) or {}
        judged = sum(
            1
            for d in instrument.domains
            if ((assessment.get("domains") or {}).get(d["id"]) or {}).get("judgement")
        )
        studies.append(
            {
                "id": study,
                "citation": citation,
                "title": title,
                "missing": [] if judged == len(instrument.domains) else ["domains"],
            }
        )
    return _render(
        request,
        "extract_index.html",
        {"actor": state.actor, "kind": "rob", "studies": studies},
    )


def _rob_context(repo: Any, state: AppState, study: str) -> dict[str, Any]:
    instrument = rob_mod.load_instrument(repo)
    assessment = rob_mod.read_assessment(rob_mod.working_path(repo, state.actor, study)) or {}
    domains = []
    for spec in instrument.domains:
        block = (assessment.get("domains") or {}).get(spec["id"]) or {}
        domain_state = rob_mod.domain_state(instrument, assessment, spec["id"])
        domains.append(
            {
                "id": spec["id"],
                "label": spec["label"],
                "questions": spec.get("signalling_questions", []),
                "answers": domain_state.answers,
                "algorithm": bool(spec.get("algorithm")),
                "suggested": domain_state.suggested,
                "needed": domain_state.needed,
                "judgements": spec["judgements"],
                "judgement": block.get("judgement") or "",
                "support": block.get("support") or "",
                "source": block.get("source") or "",
                "override": block.get("override_justification") or "",
            }
        )
    overall = assessment.get("overall") or {}
    citation, title = _citation(repo, study)
    return {
        "actor": state.actor,
        "session_token": state.session_token,
        "study": study,
        "citation": citation,
        "title": title,
        "instrument": instrument.name,
        "domains": domains,
        "overall_choices": instrument.overall_judgements,
        "overall": overall.get("judgement") or "",
        "overall_suggested": rob_mod.overall_suggestion(instrument, assessment),
        "overall_support": overall.get("support") or "",
        "overall_override": overall.get("override_justification") or "",
    }


@router.get("/rob/{study}", response_class=HTMLResponse, response_model=None)
async def rob_study(request: Request, study: str) -> HTMLResponse | PlainTextResponse:
    state: AppState = request.app.state.strata
    repo = state.open_repo()
    if not _included(repo, study):
        return _error(_STUDY_NOT_FOUND.format(study=study), status_code=404)
    try:
        context = _rob_context(repo, state, study)
    except rob_mod.RobError as exc:
        return _error(str(exc), status_code=404)
    return _render(request, "rob.html", context)


@router.post("/rob/{study}", response_model=None)
async def rob_study_submit(request: Request, study: str) -> RedirectResponse | PlainTextResponse:
    state: AppState = request.app.state.strata
    repo = state.open_repo()
    form = request.state.form
    if not _included(repo, study):
        return _error(_STUDY_NOT_FOUND.format(study=study), status_code=404)
    rationale, problem = _dedup_rationale(repo, str(form.get("commit_rationale") or ""))
    if problem:
        return _error(problem, status_code=422)
    domain = str(form.get("domain") or "")
    try:
        if str(form.get("action") or "") == "answers":
            for key in form:
                if str(key).startswith("answer:") and str(form.get(key) or ""):
                    rob_mod.answer_question(
                        repo,
                        study=study,
                        handle=state.actor,
                        domain=domain,
                        question=str(key)[len("answer:") :],
                        answer=str(form.get(key)),
                    )
        else:
            rob_mod.record_judgement(
                repo,
                study=study,
                handle=state.actor,
                domain=domain,
                judgement=str(form.get("judgement") or ""),
                support=str(form.get("support") or "").strip(),
                source=str(form.get("source") or "").strip() or None,
                override_justification=str(form.get("override_justification") or "").strip()
                or None,
            )
    except rob_mod.RobError as exc:
        return _error(str(exc), status_code=422)
    _commit(
        repo,
        op="rob",
        scope=study,
        summary=f"assess {domain}"[:60],
        actor=state.actor,
        rationale=rationale,
    )
    return _redirect(f"/rob/{quote(study, safe='')}")
