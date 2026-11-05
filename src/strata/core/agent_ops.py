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
from typing import Any

from strata.core import agents as agents_mod
from strata.core import operations as ops_mod
from strata.core import records as records_mod
from strata.core.commit import validate_rationale
from strata.core.events import collect_event_ids
from strata.core.repo import DEFAULT_LOCK_TIMEOUT, Repo, repo_lock
from strata.protocol import adjudication as adjudication_mod
from strata.protocol import criteria as criteria_mod
from strata.protocol import retrieval as retrieval_mod
from strata.protocol import screening as screening_mod
from strata.protocol import studies as studies_mod
from strata.protocol import suggestions as sugg
from strata.protocol.suggestions import Suggestion

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
}


def register_writer(op: str, writer: Writer) -> None:
    """Add the writer of an operation registered in `strata.protocol.suggestions`."""
    WRITERS[op] = writer


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
