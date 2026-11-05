"""Suggestions: openspec:ai-suggestions.

An agent whose kind of work is in `suggest` mode does not change the review: it proposes. A
suggestion is a `suggestion` event holding the operation and its exact arguments, validated by
running the real operation's own checks (`dry_run`) so that one the real operation would refuse is
refused here for the same reason, and recorded in `events/suggestion/<agent>.ndjson`. It takes part
in no fold, count or view: nothing in `strata.core.fold`, the pool, the PRISMA counts or staleness
reads this directory.

A person adopts or rejects a suggestion with a `suggestion-resolve` event. A later suggestion from
the same agent for the same operation and target supersedes an earlier unresolved one.

This module is the data layer and the registry of what can be suggested. Adopting, which runs the
operation as a person and commits, is `strata.core.agent_ops`.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from strata.core import agents as agents_mod
from strata.core import records as records_mod
from strata.core.events import agent_scope, append_new_event, read_events
from strata.core.fold import sort_events
from strata.core.repo import Repo
from strata.core.validate import validate_event_body
from strata.protocol import adjudication as adjudication_mod
from strata.protocol import criteria as criteria_mod
from strata.protocol import rescreen as rescreen_mod
from strata.protocol import retrieval as retrieval_mod
from strata.protocol import screening as screening_mod
from strata.protocol import studies as studies_mod

SUGGESTION = "suggestion"
RESOLVE = "suggestion-resolve"

PENDING = "pending"
ADOPTED = "adopted"
REJECTED = "rejected"
SUPERSEDED = "superseded"


class SuggestionError(ValueError):
    """A suggestion cannot be made, adopted or rejected; the message says why."""


# ------------------------------------------------------------------------- what can be suggested


@dataclass(frozen=True)
class OpSpec:
    """One operation an agent can propose (and, in `count` mode, perform).

    `check` runs the real operation's validation without writing and returns the impact preview a
    criteria change carries (else `None`); it is given the actor the operation would run as, because
    some checks depend on who acts (only an adjudicator adjudicates).
    """

    name: str
    kind: str
    required: tuple[str, ...]
    optional: tuple[str, ...]
    check: Callable[[Repo, Mapping[str, Any], str, str], dict[str, Any] | None]
    target: Callable[[Mapping[str, Any]], str]
    summary: Callable[[Mapping[str, Any]], str]
    record: Callable[[Mapping[str, Any]], str | None] = lambda _args: None
    stage: Callable[[Mapping[str, Any]], str | None] = lambda _args: None


def _impact(stale: Sequence[rescreen_mod.StaleRecord]) -> dict[str, Any]:
    """What a criteria change would make stale, as a suggestion records it."""
    by_stage: dict[str, int] = {}
    for item in stale:
        by_stage[item.stage] = by_stage.get(item.stage, 0) + 1
    return {"stale_decisions": len(stale), "by_stage": dict(sorted(by_stage.items()))}


def _check_screen(repo: Repo, args: Mapping[str, Any], actor: str, rationale: str) -> None:
    del rationale
    screening_mod.record_screen_decision(
        repo,
        stage=args["stage"],
        record_id=args["record"],
        decision=args["decision"],
        actor=actor,
        cited=list(args.get("criteria") or []),
        note=args.get("note"),
        confidence=args.get("confidence"),
        dry_run=True,
    )


def _check_criteria_add(
    repo: Repo, args: Mapping[str, Any], actor: str, rationale: str
) -> dict[str, Any]:
    criteria_mod.add_criterion(
        repo,
        kind=args["kind"],
        label=args["label"],
        definition=args["definition"],
        applies_at=list(args["applies_at"]),
        actor=actor,
        rationale=rationale,
        criterion_id=args.get("criterion_id"),
        examples=args.get("examples"),
        dry_run=True,
    )
    return _impact(
        rescreen_mod.preview_criterion_change_impact(
            repo,
            criterion_id=str(args.get("criterion_id") or "new"),
            direction="tightened",
            origin="added",
            applies_at=list(args["applies_at"]),
        )
    )


def _check_criteria_edit(
    repo: Repo, args: Mapping[str, Any], actor: str, rationale: str
) -> dict[str, Any]:
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
        dry_run=True,
    )
    return _impact(
        rescreen_mod.preview_criterion_change_impact(
            repo, criterion_id=args["criterion"], direction=args["direction"]
        )
    )


def _check_criteria_retire(
    repo: Repo, args: Mapping[str, Any], actor: str, rationale: str
) -> dict[str, Any]:
    criteria_mod.retire_criterion(
        repo, args["criterion"], actor=actor, rationale=rationale, dry_run=True
    )
    return _impact(
        rescreen_mod.preview_criterion_change_impact(
            repo, criterion_id=args["criterion"], direction="loosened", origin="retired"
        )
    )


def _check_retrieval(repo: Repo, args: Mapping[str, Any], actor: str, rationale: str) -> None:
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
        dry_run=True,
    )


def _check_study_group(repo: Repo, args: Mapping[str, Any], actor: str, rationale: str) -> None:
    studies_mod.group_reports(
        repo,
        reports=list(args["reports"]),
        actor=actor,
        rationale=rationale,
        study=args.get("study"),
        dry_run=True,
    )


def _check_study_split(repo: Repo, args: Mapping[str, Any], actor: str, rationale: str) -> None:
    studies_mod.split_report(
        repo,
        report=args["report"],
        parts=int(args["parts"]),
        actor=actor,
        rationale=rationale,
        dry_run=True,
    )


def _check_record_amend(repo: Repo, args: Mapping[str, Any], actor: str, rationale: str) -> None:
    del actor, rationale
    records_mod.preview_amendment(
        repo, record_id=args["record"], field=args["field"], value=str(args["value"])
    )


def _check_adjudicate(repo: Repo, args: Mapping[str, Any], actor: str, rationale: str) -> None:
    adjudication_mod.record_adjudication(
        repo,
        stage=args["stage"],
        record_id=args["record"],
        decision=args["decision"],
        actor=actor,
        rationale=rationale,
        cited=list(args.get("criteria") or []),
        dry_run=True,
    )


OPS: dict[str, OpSpec] = {
    spec.name: spec
    for spec in (
        OpSpec(
            name="screen",
            kind="screening",
            required=("stage", "record", "decision"),
            optional=("criteria", "note", "confidence"),
            check=_check_screen,
            target=lambda a: f"screen:{a['stage']}:{a['record']}",
            summary=lambda a: f"{a['decision']} {a['record']} at {a['stage']}",
            record=lambda a: str(a["record"]),
            stage=lambda a: str(a["stage"]),
        ),
        OpSpec(
            name="adjudicate",
            kind="adjudication",
            required=("stage", "record", "decision"),
            optional=("criteria",),
            check=_check_adjudicate,
            target=lambda a: f"adjudicate:{a['stage']}:{a['record']}",
            summary=lambda a: f"adjudicate {a['record']} as {a['decision']} at {a['stage']}",
            record=lambda a: str(a["record"]),
            stage=lambda a: str(a["stage"]),
        ),
        OpSpec(
            name="retrieval",
            kind="retrieval",
            required=("report", "outcome"),
            optional=("source", "version", "locator", "reason", "reason_text"),
            check=_check_retrieval,
            target=lambda a: f"retrieval:{a['report']}",
            summary=lambda a: f"{a['outcome']}: {a['report']}",
        ),
        OpSpec(
            name="study-group",
            kind="studies",
            required=("reports",),
            optional=("study",),
            check=_check_study_group,
            target=lambda a: f"study-group:{a.get('study') or ','.join(sorted(set(a['reports'])))}",
            summary=lambda a: f"group {len(set(a['reports']))} report(s) into one study",
        ),
        OpSpec(
            name="study-split",
            kind="studies",
            required=("report", "parts"),
            optional=(),
            check=_check_study_split,
            target=lambda a: f"study-split:{a['report']}",
            summary=lambda a: f"split {a['report']} into {a['parts']} studies",
        ),
        OpSpec(
            name="record-amend",
            kind="records",
            required=("record", "field", "value"),
            optional=(),
            check=_check_record_amend,
            target=lambda a: f"record-amend:{a['record']}:{a['field']}",
            summary=lambda a: f"correct {a['field']} of {a['record']}",
            record=lambda a: str(a["record"]),
        ),
        OpSpec(
            name="criteria-add",
            kind="criteria",
            required=("kind", "label", "definition", "applies_at"),
            optional=("criterion_id", "examples"),
            check=_check_criteria_add,
            target=lambda a: f"criteria-add:{a['kind']}:{a['label']}",
            summary=lambda a: f"add {a['kind']} criterion {a['label']!r}",
        ),
        OpSpec(
            name="criteria-edit",
            kind="criteria",
            required=("criterion", "direction"),
            optional=("label", "definition", "applies_at", "examples"),
            check=_check_criteria_edit,
            target=lambda a: f"criteria-edit:{a['criterion']}",
            summary=lambda a: f"edit {a['criterion']} ({a['direction']})",
        ),
        OpSpec(
            name="criteria-retire",
            kind="criteria",
            required=("criterion",),
            optional=(),
            check=_check_criteria_retire,
            target=lambda a: f"criteria-retire:{a['criterion']}",
            summary=lambda a: f"retire {a['criterion']}",
        ),
    )
}


def register(spec: OpSpec) -> None:
    """Add an operation to the registry (the operations of later stages register themselves)."""
    OPS[spec.name] = spec


def spec_for(op: str) -> OpSpec:
    try:
        return OPS[op]
    except KeyError:
        raise SuggestionError(
            f"unknown operation {op!r}; an agent can suggest: {', '.join(sorted(OPS))}"
        ) from None


def check_arguments(spec: OpSpec, args: Mapping[str, Any]) -> None:
    """Refuse missing or unexpected arguments, naming what the operation takes."""
    missing = [name for name in spec.required if args.get(name) in (None, "")]
    if missing:
        raise SuggestionError(f"{spec.name} needs {', '.join(missing)}")
    unexpected = sorted(set(args) - set(spec.required) - set(spec.optional))
    if unexpected:
        takes = ", ".join((*spec.required, *spec.optional))
        raise SuggestionError(
            f"{spec.name} does not take {', '.join(unexpected)} (it takes {takes})"
        )


def validate_operation(
    repo: Repo, op: str, args: Mapping[str, Any], *, actor: str, rationale: str
) -> dict[str, Any] | None:
    """Run the real operation's checks without writing; the impact preview of a criteria change.

    Raises the operation's own error (a `ScreeningError`, `CriteriaError`, and so on) for what it
    would refuse, so a suggestion is refused for the same reason a real decision would be.
    """
    spec = spec_for(op)
    check_arguments(spec, args)
    return spec.check(repo, args, actor, rationale)


# ----------------------------------------------------------------------------------- the record


def _suggestion_path(repo: Repo, actor: str) -> Path:
    return repo.path("events", SUGGESTION, f"{actor}.ndjson")


@dataclass(frozen=True)
class Suggestion:
    """A suggestion and where it stands."""

    id: str
    ts: str
    #: The agent actor that made it, the agent key it was made under, and its operation.
    actor: str
    agent: dict[str, Any]
    op: str
    args: dict[str, Any]
    rationale: str
    criteria_version: int
    preview: dict[str, Any] | None
    target: str
    status: str = PENDING
    resolution: dict[str, Any] | None = None
    kind: str = ""
    summary: str = ""
    record: str | None = None
    stage: str | None = None
    #: The ids of the events an adoption produced.
    result: tuple[str, ...] = field(default_factory=tuple)


def all_events(repo: Repo) -> list[dict[str, Any]]:
    """Every suggestion and suggestion-resolve event, in `(ts, id)` order."""
    directory = repo.path("events", SUGGESTION)
    if not directory.exists():
        return []
    events: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.ndjson")):
        events.extend(e for e in read_events(path) if e.get("ev") in (SUGGESTION, RESOLVE))
    return sort_events(events)


def _build(event: dict[str, Any]) -> Suggestion:
    body = event["body"]
    spec = OPS.get(body["op"])
    args = dict(body["args"])
    # A suggestion for an operation this build does not know is still listed, never dropped.
    return Suggestion(
        id=event["id"],
        ts=event["ts"],
        actor=event["actor"],
        agent=dict(event.get("agent") or {}),
        op=body["op"],
        args=args,
        rationale=body["rationale"],
        criteria_version=int(body["criteria_version"]),
        preview=body.get("preview"),
        target=spec.target(args) if spec else body["op"],
        kind=spec.kind if spec else "",
        summary=spec.summary(args) if spec else body["op"],
        record=spec.record(args) if spec else None,
        stage=spec.stage(args) if spec else None,
    )


def suggestions(repo: Repo) -> list[Suggestion]:
    """Every suggestion, oldest first, with its outcome.

    The first outcome recorded for a suggestion stands: two people resolving one concurrently on
    different machines is settled by `(ts, id)` order, like every other fold.
    """
    built: dict[str, Suggestion] = {}
    resolutions: dict[str, dict[str, Any]] = {}
    for event in all_events(repo):
        if event["ev"] == SUGGESTION:
            built[event["id"]] = _build(event)
        else:
            resolutions.setdefault(event["body"]["suggestion"], event)
    out = []
    for suggestion in built.values():
        resolution = resolutions.get(suggestion.id)
        if resolution is None:
            out.append(suggestion)
            continue
        body = resolution["body"]
        resolved = dict(body)
        resolved["by"] = resolution["actor"]
        resolved["ts"] = resolution["ts"]
        out.append(
            Suggestion(
                **{
                    **suggestion.__dict__,
                    "status": body["outcome"],
                    "resolution": resolved,
                    "result": tuple(body.get("result") or ()),
                }
            )
        )
    return out


def get_suggestion(repo: Repo, suggestion_id: str) -> Suggestion:
    """The suggestion with this id or an unambiguous prefix of it."""
    found = [s for s in suggestions(repo) if s.id == suggestion_id]
    if not found:
        found = [s for s in suggestions(repo) if s.id.startswith(suggestion_id)]
    if not found:
        raise SuggestionError(f"no suggestion {suggestion_id!r}")
    if len(found) > 1:
        raise SuggestionError(f"{suggestion_id!r} matches more than one suggestion")
    return found[0]


def pending(repo: Repo) -> list[Suggestion]:
    """Unresolved, unsuperseded suggestions: the only ones a person is asked about."""
    return [s for s in suggestions(repo) if s.status == PENDING]


def make_suggestion(
    repo: Repo,
    *,
    context: agents_mod.AgentContext,
    op: str,
    args: Mapping[str, Any],
    rationale: str,
) -> dict[str, Any]:
    """Record a suggestion by an agent; the new `suggestion` event.

    The operation is validated first, exactly as the real one would be (`validate_operation`), so
    nothing is recorded for a suggestion the real operation would refuse. Writes one line to the
    agent's own file and, for each earlier unresolved suggestion by this agent for the same
    operation and target, a `superseded` resolution. Changes no review state.
    """
    text = rationale.strip()
    if not text:
        raise SuggestionError("a rationale is required: say why the agent suggests this")
    clean = {k: v for k, v in dict(args).items() if v is not None}
    preview = validate_operation(repo, op, clean, actor=context.actor, rationale=text)
    spec = spec_for(op)
    target = spec.target(clean)
    body: dict[str, Any] = {
        "op": op,
        "args": clean,
        "rationale": text,
        "criteria_version": int(criteria_mod.read_criteria_doc(repo)["version"]),
    }
    if preview is not None:
        body["preview"] = preview
    validate_event_body(SUGGESTION, body)
    earlier = [s for s in pending(repo) if s.actor == context.actor and s.target == target]
    with agent_scope(context.actor, context.envelope_value()):
        path = _suggestion_path(repo, context.actor)
        event = append_new_event(path, ev=SUGGESTION, actor=context.actor, body=body)
        for old in earlier:
            append_new_event(
                path,
                ev=RESOLVE,
                actor=context.actor,
                body={
                    "suggestion": old.id,
                    "outcome": SUPERSEDED,
                    "reason": f"superseded by a later suggestion, {event['id']}",
                },
            )
    return event


def resolve(
    repo: Repo,
    *,
    suggestion_id: str,
    outcome: str,
    actor: str,
    reason: str,
    result: Sequence[str] = (),
) -> dict[str, Any]:
    """Record that a person adopted or rejected a suggestion (never an agent: a person's act)."""
    body: dict[str, Any] = {"suggestion": suggestion_id, "outcome": outcome, "reason": reason}
    if result:
        body["result"] = list(result)
    validate_event_body(RESOLVE, body)
    return append_new_event(_suggestion_path(repo, actor), ev=RESOLVE, actor=actor, body=body)


# ---------------------------------------------------------------- opinions a suggestion informed


def informed_opinions(repo: Repo, stage: str) -> frozenset[str]:
    """Ids of the `screen` events at `stage` that a suggestion may have informed.

    An opinion is informed if it is one an adoption produced, or if it was recorded when the
    reviewer could already see a suggestion about that record: when the review does not blind its
    reviewers, or has chosen to show suggestions `always`. Under the default
    (`after-own-decision`) a reviewer's first opinion is made before they can see anything, so it
    stays independent, and a change made afterwards is excluded from agreement anyway, like any
    change made after seeing another opinion (openspec:ai-suggestions#suggestions-respect-blinding).

    Agreement between independent reviewers leaves these out. The answer is read from the log, so it
    is the same on every machine and needs nothing stored on the opinion.
    """
    everything = suggestions(repo)
    if not everything:
        return frozenset()
    adopted = {event_id for s in everything for event_id in s.result}
    screening = repo.config.get("screening", {})
    visible_early = (not screening.get("blind_reviewers", True)) or (
        agents_mod.show_suggestions(repo) == agents_mod.SHOW_ALWAYS
    )
    earliest: dict[str, tuple[str, str]] = {}
    if visible_early:
        for s in everything:
            if s.stage == stage and s.record is not None:
                earliest[s.record] = min(earliest.get(s.record, (s.ts, s.id)), (s.ts, s.id))
    informed: set[str] = set()
    for event in screening_mod.all_screen_events(repo, stage):
        if event["id"] in adopted:
            informed.add(event["id"])
            continue
        first = earliest.get(event["body"]["record"])
        if first is not None and first[0] <= event["ts"]:
            informed.add(event["id"])
    return frozenset(informed)
