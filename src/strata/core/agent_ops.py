"""Operations an agent can propose, and what happens to a proposal: openspec:ai-suggestions.

`strata.protocol.suggestions` knows what can be suggested and how to record it. This module is where
a suggestion becomes part of the review: **adopting** runs the operation *as the person who adopts
it*, after validating it again against the review as it now stands, with that person's own
rationale, and links the suggestion to the events it produced; **rejecting** records a reason and
offers it no more. An adopted suggestion's events are the person's and carry no `agent` key: a
person deciding is a person deciding, and the record says whose idea it was by the link.

It also decides who may *see* a suggestion. A suggestion about a record is information a reviewer
might be influenced by, so while the review blinds its reviewers it is hidden from one assigned to
that record until they have recorded their own opinion
(openspec:ai-suggestions#suggestions-respect-blinding).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from strata import gitio
from strata.analysis import run as analysis_run
from strata.core import agents as agents_mod
from strata.core import operations as ops_mod
from strata.core import records as records_mod
from strata.core.commit import validate_rationale
from strata.core.events import append_new_event, collect_event_ids
from strata.core.repo import DEFAULT_LOCK_TIMEOUT, Repo, repo_lock
from strata.dedup import engine as dedup_engine
from strata.dedup import scoring as dedup_scoring
from strata.extract import records as extraction_records_mod
from strata.extract import rob as rob_mod
from strata.ingest import pipeline as pipeline_mod
from strata.protocol import adjudication as adjudication_mod
from strata.protocol import criteria as criteria_mod
from strata.protocol import retrieval as retrieval_mod
from strata.protocol import screening as screening_mod
from strata.protocol import searches as searches_mod
from strata.protocol import studies as studies_mod
from strata.protocol import suggestions as sugg
from strata.protocol.suggestions import Suggestion
from strata.report import counts as counts_mod
from strata.report import flow as flow_mod

#: Kinds of work whose validity or meaning depends on the criteria, so a change of criteria since a
#: suggestion was made means the person should look again before adopting it.
CRITERIA_DEPENDENT_KINDS = frozenset({"screening", "adjudication", "criteria"})


class AdoptionError(ValueError):
    """A suggestion cannot be adopted or rejected now; the message says why."""


class StateMoved(AdoptionError):
    """The review changed since the suggestion was made; confirm to adopt it as things now stand."""


# ------------------------------------------------------------------------------- the operations


@dataclass(frozen=True)
class CommitShape:
    """How an operation is committed: the commit's `op`, scope and summary, and any extra paths."""

    op: str
    scope: str | None
    summary: str
    extra_paths: tuple[str, ...] = ()
    trailers: tuple[tuple[str, str], ...] = ()


#: `writer(repo, args, actor, rationale)` performs the operation's writes (events and files, no
#: regeneration and no commit) and returns the commit's shape.
Writer = Callable[[Repo, Mapping[str, Any], str, str], CommitShape]


def _write_screen(repo: Repo, args: Mapping[str, Any], actor: str, rationale: str) -> CommitShape:
    del rationale  # a screening decision's reason is the commit body, not part of the event
    screening_mod.record_screen_decision(
        repo,
        stage=args["stage"],
        record_id=args["record"],
        decision=args["decision"],
        actor=actor,
        cited=list(args.get("criteria") or []),
        note=args.get("note"),
        confidence=args.get("confidence"),
    )
    stage = args["stage"]
    return CommitShape("screen", stage, f"screened 1 {stage} record(s)")


def _write_adjudicate(
    repo: Repo, args: Mapping[str, Any], actor: str, rationale: str
) -> CommitShape:
    adjudication_mod.record_adjudication(
        repo,
        stage=args["stage"],
        record_id=args["record"],
        decision=args["decision"],
        actor=actor,
        rationale=rationale,
        cited=list(args.get("criteria") or []),
    )
    return CommitShape("adjudicate", args["stage"], "adjudicated 1 conflict(s)")


def _write_retrieval(
    repo: Repo, args: Mapping[str, Any], actor: str, rationale: str
) -> CommitShape:
    del rationale
    retrieval_mod.record_retrieval(
        repo,
        report=args["report"],
        status=args["outcome"],
        actor=actor,
        source=args.get("source"),
        version=args.get("version"),
        locator=args.get("locator"),
        reason=args.get("reason"),
        reason_text=args.get("reason_text"),
    )
    return CommitShape("retrieve", None, f"{args['outcome']}: {args['report']}")


def _write_study_group(
    repo: Repo, args: Mapping[str, Any], actor: str, rationale: str
) -> CommitShape:
    event = studies_mod.group_reports(
        repo,
        reports=list(args["reports"]),
        actor=actor,
        rationale=rationale,
        study=args.get("study"),
    )
    count = len(set(args["reports"]))
    return CommitShape("studies", None, f"grouped {count} report(s) into {event['body']['study']}")


def _write_study_split(
    repo: Repo, args: Mapping[str, Any], actor: str, rationale: str
) -> CommitShape:
    studies_mod.split_report(
        repo, report=args["report"], parts=int(args["parts"]), actor=actor, rationale=rationale
    )
    return CommitShape("studies", None, f"split {args['report']} into {args['parts']} studies")


def _write_record_amend(
    repo: Repo, args: Mapping[str, Any], actor: str, rationale: str
) -> CommitShape:
    del rationale
    records_mod.amend_field(
        repo, record_id=args["record"], field=args["field"], value=str(args["value"]), actor=actor
    )
    return CommitShape("fix", args["record"], f"corrected {args['field']}")


def _criteria_shape(op: str, criterion_id: str, summary: str) -> CommitShape:
    return CommitShape(
        op,
        criterion_id,
        summary,
        extra_paths=("protocol/criteria.yaml",),
        trailers=(("Criterion", criterion_id),),
    )


def _write_criteria_add(
    repo: Repo, args: Mapping[str, Any], actor: str, rationale: str
) -> CommitShape:
    criterion = criteria_mod.add_criterion(
        repo,
        kind=args["kind"],
        label=args["label"],
        definition=args["definition"],
        applies_at=list(args["applies_at"]),
        actor=actor,
        rationale=rationale,
        criterion_id=args.get("criterion_id"),
        examples=args.get("examples"),
    )
    return _criteria_shape("criteria-add", criterion["id"], f"add criterion {criterion['id']}")


def _write_criteria_edit(
    repo: Repo, args: Mapping[str, Any], actor: str, rationale: str
) -> CommitShape:
    criteria_mod.edit_criterion(
        repo,
        args["criterion"],
        direction=args["direction"],
        actor=actor,
        rationale=rationale,
        label=args.get("label"),
        definition=args.get("definition"),
        applies_at=list(args["applies_at"]) if args.get("applies_at") is not None else None,
        examples=args.get("examples"),
    )
    return _criteria_shape(
        "criteria-edit",
        args["criterion"],
        f"edit criterion {args['criterion']} ({args['direction']})",
    )


def _write_criteria_retire(
    repo: Repo, args: Mapping[str, Any], actor: str, rationale: str
) -> CommitShape:
    criteria_mod.retire_criterion(repo, args["criterion"], actor=actor, rationale=rationale)
    return _criteria_shape(
        "criteria-retire", args["criterion"], f"retire criterion {args['criterion']}"
    )


def _write_note(repo: Repo, args: Mapping[str, Any], actor: str, rationale: str) -> CommitShape:
    del rationale
    append_new_event(
        repo.path("events", "note", f"{actor}.ndjson"),
        ev="note",
        actor=actor,
        body={"subject": args["record"], "text": str(args["text"]).strip()},
    )
    return CommitShape("note", args["record"], f"noted {args['record']}")


def _write_extract_field(
    repo: Repo, args: Mapping[str, Any], actor: str, rationale: str
) -> CommitShape:
    del rationale
    extraction_records_mod.set_field(
        repo,
        study=args["study"],
        handle=actor,
        name=args["field"],
        raw=str(args["value"]),
        source=args.get("source"),
    )
    return CommitShape("extract", None, f"set {args['field']} of {args['study']}")


def _write_rob_judgement(
    repo: Repo, args: Mapping[str, Any], actor: str, rationale: str
) -> CommitShape:
    del rationale
    rob_mod.record_judgement(
        repo,
        study=args["study"],
        handle=actor,
        domain=args["domain"],
        judgement=args["judgement"],
        support=args.get("support") or "",
        source=args.get("source"),
        override_justification=args.get("override_justification"),
    )
    return CommitShape("rob", None, f"judged {args['domain']} of {args['study']}")


def _write_dedup_decide(
    repo: Repo, args: Mapping[str, Any], actor: str, rationale: str
) -> CommitShape:
    del rationale
    first = records_mod.get_record(repo, args["a"])
    second = records_mod.get_record(repo, args["b"])
    assert first is not None and second is not None  # checked by the operation's validation
    dedup_engine.apply_review_decision(
        repo,
        record_a_id=args["a"],
        record_b_id=args["b"],
        result=dedup_scoring.score_pair(first, second),
        decision=args["decision"],
        actor=actor,
    )
    return CommitShape("dedup", None, f"{args['decision']} {args['a']} and {args['b']}")


def _write_search_add(
    repo: Repo, args: Mapping[str, Any], actor: str, rationale: str
) -> CommitShape:
    del rationale
    record = searches_mod.add_search(
        repo,
        database=args["database"],
        platform=args["platform"],
        executed=args["executed"],
        executed_by=actor,
        search_id=args.get("search_id"),
        query=args.get("query"),
        hits=args.get("hits"),
        notes=args.get("notes"),
    )
    return CommitShape(
        "search-add",
        record["id"],
        f"record search {record['id']}",
        extra_paths=("protocol/searches",),
        trailers=(("Search", record["id"]),),
    )


def _write_import(repo: Repo, args: Mapping[str, Any], actor: str, rationale: str) -> CommitShape:
    del rationale
    pipeline_mod.import_file(
        repo,
        args["path"],
        imported_by=actor,
        search_id=args.get("search"),
        via=args.get("via"),
        fmt=args.get("format"),
    )
    return CommitShape(
        "import",
        None,
        f"import {Path(args['path']).name}",
        extra_paths=("imports", "protocol/searches"),
    )


WRITERS: dict[str, Writer] = {
    "screen": _write_screen,
    "adjudicate": _write_adjudicate,
    "retrieval": _write_retrieval,
    "study-group": _write_study_group,
    "study-split": _write_study_split,
    "record-amend": _write_record_amend,
    "criteria-add": _write_criteria_add,
    "criteria-edit": _write_criteria_edit,
    "criteria-retire": _write_criteria_retire,
    "note": _write_note,
    "extract-field": _write_extract_field,
    "rob-judgement": _write_rob_judgement,
    "dedup-decide": _write_dedup_decide,
    "search-add": _write_search_add,
    "import": _write_import,
}


def register_writer(op: str, writer: Writer) -> None:
    """Add the writer of an operation registered in `strata.protocol.suggestions`."""
    WRITERS[op] = writer


# ---------------------------------------------------------------------------- analysis (kind)
#
# These operations write generated files, so they register here rather than in
# `strata.protocol.suggestions`, which knows nothing of the report and analysis layers. An agent can
# run an analysis and draw the diagram; it cannot `--force` past a guardrail or acknowledge a
# warning, because deciding that a warning does not matter is a person's judgement.

_PRISMA_FORMATS = ("svg", "png", "pdf", "json")


def _check_analyze(repo: Repo, args: Mapping[str, Any], actor: str, rationale: str) -> None:
    del actor, rationale
    analysis_run.run_analysis(repo, args["analysis"], write=False)


def _check_prisma(repo: Repo, args: Mapping[str, Any], actor: str, rationale: str) -> None:
    del actor, rationale
    fmt = args.get("format", "svg")
    columns = args.get("columns", "one")
    if fmt not in _PRISMA_FORMATS:
        raise sugg.SuggestionError(f"format must be one of {', '.join(_PRISMA_FORMATS)}")
    if columns not in flow_mod.COLUMNS:
        raise sugg.SuggestionError(f"columns must be one of {', '.join(flow_mod.COLUMNS)}")
    counts = counts_mod.compute(repo)  # computes and checks; regenerates nothing
    counts_mod.require_reconciled(counts)
    flow_mod.require_final(counts, allow_stale=False)


def _write_analyze(repo: Repo, args: Mapping[str, Any], actor: str, rationale: str) -> CommitShape:
    del actor, rationale
    analysis_run.run_analysis(repo, args["analysis"], force=False, acknowledged=[])
    return CommitShape("analyze", None, f"ran {args['analysis']}")


def _write_prisma(repo: Repo, args: Mapping[str, Any], actor: str, rationale: str) -> CommitShape:
    del actor, rationale
    fmt = args.get("format", "svg")
    rendered = ops_mod.render_prisma(
        repo, fmt=fmt, columns=args.get("columns", "one"), allow_stale=False
    )
    ops_mod.write_prisma(repo, rendered, fmt=fmt, target=None)
    return CommitShape("prisma", None, f"drew the PRISMA flow diagram ({fmt})")


sugg.register(
    sugg.OpSpec(
        name="analyze",
        kind="analysis",
        required=("analysis",),
        optional=(),
        check=_check_analyze,
        target=lambda a: f"analyze:{a['analysis']}",
        summary=lambda a: f"run analysis {a['analysis']}",
    )
)
sugg.register(
    sugg.OpSpec(
        name="prisma",
        kind="analysis",
        required=(),
        optional=("format", "columns"),
        check=_check_prisma,
        target=lambda a: f"prisma:{a.get('format', 'svg')}:{a.get('columns', 'one')}",
        summary=lambda a: f"draw the PRISMA flow diagram ({a.get('format', 'svg')})",
    )
)
WRITERS["analyze"] = _write_analyze
WRITERS["prisma"] = _write_prisma


@dataclass(frozen=True)
class Applied:
    """An operation that was carried out: the events it wrote and whether it was committed."""

    event_ids: tuple[str, ...]
    committed: bool
    lock_reclaimed_from: int | None = None


def apply_operation(
    repo: Repo,
    op: str,
    args: Mapping[str, Any],
    *,
    actor: str,
    rationale: str,
    extra_trailers: Mapping[str, str] | None = None,
    also: Callable[[Sequence[str]], None] | None = None,
    lock_timeout: float = DEFAULT_LOCK_TIMEOUT,
) -> Applied:
    """Carry out `op` as `actor`: write it, regenerate what it moves, and commit once.

    `also` is called with the ids of the events the operation wrote, still under the lock and before
    the commit, so that whatever it records (the link from an adopted suggestion) is part of the
    same commit. The caller has validated everything it can; this raises what the operation raises.
    """
    sugg.spec_for(op)
    text = validate_rationale(rationale)
    with repo_lock(repo, timeout=lock_timeout) as held:
        with collect_event_ids() as ids:
            shape = WRITERS[op](repo, args, actor, text)
        if also is not None:
            also(tuple(ids))
        committed = ops_mod.commit_domain_work(
            repo,
            op=shape.op,
            scope=shape.scope,
            summary=shape.summary,
            actor=actor,
            extra_trailers={**dict(shape.trailers), **(extra_trailers or {})},
            extra_paths=shape.extra_paths,
            rationale=text,
        )
    return Applied(tuple(ids), committed, held.reclaimed_from)


# ----------------------------------------------------------------------------- an agent's write


class PathNotAllowed(ValueError):
    """A file argument lies outside the repository and every directory the person allowed."""


def confine_path(repo: Repo, raw: str, allow_dirs: Sequence[Path] = ()) -> Path:
    """The real path of a file argument, or `PathNotAllowed`.

    Links are resolved first, so a link inside the repository that points outside it does not
    pass. A relative path is taken from the repository's root. The path is accepted only inside the
    repository or inside a directory the person allowed with `strata mcp --allow-dir`
    (openspec:mcp-server#file-arguments-are-confined).
    """
    base = repo.root.resolve()
    candidate = Path(raw).expanduser()
    resolved = (candidate if candidate.is_absolute() else base / candidate).resolve()
    roots = [base, *(d.expanduser().resolve() for d in allow_dirs)]
    if not any(resolved.is_relative_to(root) for root in roots):
        raise PathNotAllowed(
            f"{raw!r} is outside this review and the directories the person running the server "
            "allowed (`strata mcp --allow-dir DIR`), so it was not read"
        )
    return resolved


@dataclass(frozen=True)
class Acted:
    """What an agent's write did, for the tool result: a suggestion or an event, and its id.

    Deliberately says nothing about the record's state, whether anyone else has decided it, or
    whether they agree: a write must not reveal what blinding hides.
    """

    mode: str
    #: "suggestion" (nothing changed; a person decides), "event" (it took effect, as the agent's) or
    #: "work" (it took effect and wrote files rather than events: an analysis, a diagram).
    recorded: str
    id: str
    event_ids: tuple[str, ...]
    committed: bool
    preview: dict[str, Any] | None
    message: str


def act(
    repo: Repo,
    *,
    op: str,
    args: Mapping[str, Any],
    model: str | None,
    rationale: str | None,
    invoked_by: str | None,
    client_name: str | None = None,
    client_version: str | None = None,
    allow_dirs: Sequence[Path] = (),
) -> Acted:
    """An agent asks to do `op`: refuse it, record it as a suggestion, or carry it out as the agent.

    The policy for the operation's kind of work decides, checked now and not at some earlier time
    (`agents.authorise` raises `AgentRefused`, recording nothing, when the kind is off, the model is
    not one the review accepts or no person is named). `suggest` records a suggestion that changes
    no review state; `count` carries the operation out as the agent: its events carry the `agent`
    key and its commit is authored by the agent and committed by the person who started the
    server. Raises the operation's own error for anything it would refuse.
    """
    spec = sugg.spec_for(op)
    authorised = agents_mod.authorise(
        repo,
        kind=spec.kind,
        model=model,
        invoked_by=invoked_by,
        client_name=client_name,
        client_version=client_version,
    )
    context = authorised.context
    text = validate_rationale(rationale)
    clean = {k: v for k, v in dict(args).items() if v is not None}
    sugg.check_arguments(spec, clean)
    if "path" in clean:
        clean["path"] = str(confine_path(repo, str(clean["path"]), allow_dirs))

    if authorised.mode == agents_mod.MODE_SUGGEST:
        event = sugg.make_suggestion(repo, context=context, op=op, args=clean, rationale=text)
        return Acted(
            mode=authorised.mode,
            recorded="suggestion",
            id=event["id"],
            event_ids=(event["id"],),
            committed=False,
            preview=event["body"].get("preview"),
            message=(
                "Recorded as a suggestion; nothing in the review changed. A person decides "
                "whether to adopt it."
            ),
        )

    preview = sugg.validate_operation(repo, op, clean, actor=context.actor, rationale=text)
    trailers = {}
    if preview is not None:
        trailers["Impact"] = f"{preview['stale_decisions']} decision(s) made stale"
    with agents_mod.acting_as(context):
        applied = apply_operation(
            repo, op, clean, actor=context.actor, rationale=text, extra_trailers=trailers
        )
    wrote_events = bool(applied.event_ids)
    return Acted(
        mode=authorised.mode,
        recorded="event" if wrote_events else "work",
        id=applied.event_ids[0] if wrote_events else gitio.current_commit(repo.root),
        event_ids=applied.event_ids,
        committed=applied.committed,
        preview=preview,
        message=(
            "Recorded as the agent's own work, with the model and the person who started it."
            if wrote_events
            else "Carried out as the agent's work; the commit is authored by the agent, with the "
            "model and the person who started it in its trailers, and committed by that person."
        ),
    )


# --------------------------------------------------------------------------------- visibility


def _opinion_keys(repo: Repo, stage: str, cache: dict[str, set[tuple[str, str]]]) -> set[Any]:
    if stage not in cache:
        cache[stage] = {
            (e["actor"], e["body"]["record"]) for e in screening_mod.all_screen_events(repo, stage)
        }
    return cache[stage]


def _visible(
    repo: Repo,
    suggestion: Suggestion,
    person: str,
    *,
    blinded: bool,
    opinions: dict[str, set[tuple[str, str]]],
    assignments: list[dict[str, Any]],
) -> bool:
    if not blinded or suggestion.record is None or suggestion.stage is None:
        return True
    assigned = screening_mod.assigned_actors(
        repo, suggestion.stage, suggestion.record, assign_events=assignments
    )
    if person not in assigned:
        return True
    return (person, suggestion.record) in _opinion_keys(repo, suggestion.stage, opinions)


def is_blinded(repo: Repo) -> bool:
    """Whether suggestions about a record are hidden from a reviewer who has not yet decided it:
    reviewers are blinded and the review has not chosen to show suggestions `always`."""
    return (
        bool(repo.config.get("screening", {}).get("blind_reviewers", True))
        and agents_mod.show_suggestions(repo) != agents_mod.SHOW_ALWAYS
    )


def visible_pending(repo: Repo, person: str | None = None) -> list[Suggestion]:
    """The pending suggestions `person` may see.

    With no `person`, the most blinded view: a suggestion is listed only if it is visible to every
    person who could be asked, so that nothing is revealed to someone who has not decided yet.
    """
    blinded = is_blinded(repo)
    found = sugg.pending(repo)
    if not blinded:
        return found
    if person is not None:
        viewers = [person]
    else:
        viewers = [
            str(a["handle"]) for a in agents_mod.human_actors(repo) if a["role"] != "inactive"
        ]
    opinions: dict[str, set[tuple[str, str]]] = {}
    assignments = screening_mod.all_assign_events(repo)
    return [
        s
        for s in found
        if all(
            _visible(repo, s, v, blinded=blinded, opinions=opinions, assignments=assignments)
            for v in viewers
        )
    ]


# ----------------------------------------------------------------------- adopting and rejecting


def _person(repo: Repo, handle: str | None) -> str:
    invoker = agents_mod.resolve_invoker(repo, handle)
    if invoker.handle is None:
        raise AdoptionError(
            (invoker.problem or "no person is acting")
            .replace("--as", "--by")
            .replace("invoke agents", "adopt or reject a suggestion")
            .replace("invoking agents", "adopting suggestions")
            .replace("`strata mcp --by HANDLE`", "--by HANDLE")
        )
    return invoker.handle


def what_moved(repo: Repo, suggestion: Suggestion) -> str | None:
    """What changed in the review since `suggestion` was made that it depended on, or `None`."""
    if suggestion.kind not in CRITERIA_DEPENDENT_KINDS:
        return None
    current = int(criteria_mod.read_criteria_doc(repo)["version"])
    if current == suggestion.criteria_version:
        return None
    changed = sorted(
        {
            str(d["id"])
            for d in criteria_mod.diff_versions(repo, suggestion.criteria_version, current)
        }
    )
    named = f" ({', '.join(changed)})" if changed else ""
    return (
        f"the criteria changed from v{suggestion.criteria_version} to v{current}{named} after "
        "this was suggested"
    )


@dataclass(frozen=True)
class Adopted:
    suggestion: str
    person: str
    event_ids: tuple[str, ...]
    committed: bool


def adopt(
    repo: Repo,
    suggestion_id: str,
    *,
    by: str | None,
    rationale: str,
    confirm_moved: bool = False,
    lock_timeout: float = DEFAULT_LOCK_TIMEOUT,
) -> Adopted:
    """Adopt a suggestion: run its operation as the person `by`, with their rationale.

    Raises `AdoptionError` (nothing is written) when the suggestion is not pending, `by` is not an
    active person who may act, the operation would now be refused (the message is the real
    operation's), or `StateMoved` when the review has changed since the suggestion was made and
    `confirm_moved` is not set. The events written are `by`'s, without an `agent` key, and one
    `suggestion-resolve` event links the suggestion to them, in the same commit.
    """
    try:
        suggestion = sugg.get_suggestion(repo, suggestion_id)
    except sugg.SuggestionError as exc:
        raise AdoptionError(str(exc)) from exc
    if suggestion.status != sugg.PENDING:
        raise AdoptionError(f"suggestion {suggestion.id} is already {suggestion.status}")
    person = _person(repo, by)
    text = validate_rationale(rationale)
    if not confirm_moved and (moved := what_moved(repo, suggestion)):
        raise StateMoved(
            f"{moved}. Look again, then confirm to adopt it against the review as it is now."
        )
    try:
        sugg.validate_operation(repo, suggestion.op, suggestion.args, actor=person, rationale=text)
    except (ValueError, LookupError) as exc:
        raise AdoptionError(f"this can no longer be done: {exc}") from exc

    def link(event_ids: Sequence[str]) -> None:
        sugg.resolve(
            repo,
            suggestion_id=suggestion.id,
            outcome=sugg.ADOPTED,
            actor=person,
            reason=text,
            result=event_ids,
        )

    applied = apply_operation(
        repo,
        suggestion.op,
        suggestion.args,
        actor=person,
        rationale=text,
        extra_trailers={"Suggestion": suggestion.id, "Suggested-By": suggestion.actor},
        also=link,
        lock_timeout=lock_timeout,
    )
    return Adopted(suggestion.id, person, applied.event_ids, applied.committed)


def reject(
    repo: Repo,
    suggestion_id: str,
    *,
    by: str | None,
    reason: str,
    lock_timeout: float = DEFAULT_LOCK_TIMEOUT,
) -> Suggestion:
    """Reject a suggestion with a reason; it stays in the record and is not offered again."""
    try:
        suggestion = sugg.get_suggestion(repo, suggestion_id)
    except sugg.SuggestionError as exc:
        raise AdoptionError(str(exc)) from exc
    if suggestion.status != sugg.PENDING:
        raise AdoptionError(f"suggestion {suggestion.id} is already {suggestion.status}")
    person = _person(repo, by)
    if not reason or not reason.strip():
        raise AdoptionError("rejecting a suggestion needs a reason")
    text = validate_rationale(reason)
    with repo_lock(repo, timeout=lock_timeout):
        sugg.resolve(
            repo, suggestion_id=suggestion.id, outcome=sugg.REJECTED, actor=person, reason=text
        )
        ops_mod.commit_domain_work(
            repo,
            op="suggestion-reject",
            scope=None,
            summary=f"reject suggestion: {suggestion.summary}",
            actor=person,
            extra_trailers={"Suggestion": suggestion.id, "Suggested-By": suggestion.actor},
            rationale=text,
        )
    return sugg.get_suggestion(repo, suggestion.id)
