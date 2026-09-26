"""Wiring the pure staleness engine to real repository state.

Implements openspec:staleness#staleness-cascades-across-stages-without-deleting-work (cascading
staleness) and
openspec:staleness#re-screening-shows-the-prior-decision (the re-screening workflow), plus
openspec:derived-views#stale-decisions-view
(`derived/stale.tsv`). `strata.protocol.staleness` is deliberately pure and
knows nothing about a repository, an actor, or a fold; this module is the
impure half that reads criteria-change events, screen/adjudicate events, and
`core.fold`'s resolution to decide which *resolved* records are stale, and
drives `strata rescreen`.

**Multi-reviewer staleness, a documented simplification.**
openspec:staleness#decisions-bind-to-the-criteria-they-were-made-under defines
staleness per decision, and every `screen` event is its own decision with
its own `criteria_version`. A resolved record in dual mode, though, is the
*agreement* of two independent opinions that may have been recorded at two
different criteria versions with two different citations. Rather than
invent an unspecified per-opinion reconciliation, this module treats the
resolved record as one decision for staleness purposes: `decision_version`
is the **earliest** version among the contributing opinions (the most
conservative choice -- a criteria change after the *first* contributing
opinion could have changed the outcome) and `cited` is the **union** of
every contributing opinion's citations (so a change loosening/retiring
*either* reviewer's cited criterion is caught). In single-reviewer mode
there is exactly one opinion, so this collapses to the literal per-decision
rule with no approximation at all. An adjudicated record uses the
adjudication event's own `criteria_version`/`criteria` directly, once
`strata adjudicate` (docs/m2-plan.md sub-objective 5) starts writing them.

**`maybe` is out of scope for the resolved-decision model.** `core.fold`'s
own resolution rule folds any `maybe` opinion (dual or single reviewer) into
`conflict`, never into a resolved `maybe` -- so `D.decision == "maybe"` in
openspec:staleness#the-staleness-rules's rule only ever applies to an individual, unresolved
opinion. This
module only computes staleness for *resolved* (`include`/`exclude`)
decisions, matching every reason `derived/stale.tsv`'s own reason table
lists staleness against (openspec:staleness#staleness-causes's table has no "conflict" reason).
Per-opinion staleness for a still-open conflict is a real, deliberately
deferred refinement -- `protocol.staleness.evaluate_staleness` already
supports it directly if a future session wants it.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from strata.core import records as records_mod
from strata.core.canon import canonical_json
from strata.core.events import append_new_event, read_events
from strata.core.fold import ScreeningState, sort_events
from strata.core.repo import Repo
from strata.protocol import criteria as criteria_mod
from strata.protocol import screening as screening_mod
from strata.protocol.staleness import CriterionChange, evaluate_staleness

_STAGE_ORDER = ("title-abstract", "full-text")
_MANUAL_STALE_SUBJECT = "manual-stale"

_STALE_TSV_HEADER = (
    "record_id",
    "stage",
    "prior_decision",
    "prior_criteria",
    "reason",
    "since_version",
    "title",
)


class RescreenError(ValueError):
    pass


@dataclass(frozen=True)
class StaleRecord:
    record_id: str
    stage: str
    prior_decision: str
    prior_criteria: tuple[str, ...]
    reason: str
    since_version: int


def _criterion_changes(repo: Repo) -> list[CriterionChange]:
    changes: list[CriterionChange] = []
    for event in criteria_mod.all_criteria_change_events(repo):
        to_version = int(event["body"]["to_version"])
        for delta in event["body"]["deltas"]:
            changes.append(
                CriterionChange(
                    criterion_id=delta["id"],
                    origin=delta["origin"],
                    direction=delta["direction"],
                    to_version=to_version,
                    applies_at=frozenset(delta["applies_at"]),
                )
            )
    return changes


@dataclass(frozen=True)
class _Opinion:
    """One `(decision, version, cited)` triple to test for staleness, plus the
    order key of whatever event produced it (for manual-mark consumption)."""

    decision: str
    version: int
    cited: frozenset[str]
    order_key: tuple[str, str]


def _effective_opinion(state: ScreeningState, *, actor: str | None) -> _Opinion | None:
    """The decision to test for staleness at one `(stage, record)`.

    `actor=None` is the aggregate, resolved-record view: the module
    docstring's min-version/union-of-citations heuristic, only defined once
    the record is actually *resolved* (`include`/`exclude`).

    `actor=<handle>` is that reviewer's own most recent opinion, evaluated
    directly per openspec:staleness#the-staleness-rules's literal per-decision rule -- independent
    of the
    record's aggregate status. This is what makes dual-mode re-screening
    actually work: the instant one reviewer's fresh opinion disagrees with
    the other's still-stale one, the record's aggregate status flips to
    `conflict`, which would otherwise erase it from `compute_stale_records`
    entirely and leave the second reviewer with nothing in their queue even
    though *their own* opinion is still exactly as stale as it was before
    the first reviewer acted (docs/m2-plan.md sub-objective 9's E2E-01 test
    caught this: dual re-screening silently lost half its queue).

    Either way, an adjudicated record uses the adjudication's own stamped
    version/citations, since adjudication is the one shared, authoritative
    decision that supersedes every individual opinion.
    """
    if state.adjudication is not None:
        body = state.adjudication["body"]
        version = body.get("criteria_version")
        if version is None:
            return None
        return _Opinion(
            decision=state.adjudication["body"]["decision"],
            version=int(version),
            cited=frozenset(body.get("criteria") or []),
            order_key=_order_key(state.adjudication),
        )
    if actor is not None:
        opinion_event = state.opinions.get(actor)
        if opinion_event is None:
            return None
        body = opinion_event["body"]
        return _Opinion(
            decision=body["decision"],
            version=int(body["criteria_version"]),
            cited=frozenset(body.get("criteria") or []),
            order_key=_order_key(opinion_event),
        )
    if state.status not in ("include", "exclude"):
        return None
    opinions = list(state.opinions.values())
    if not opinions:
        return None
    versions = [int(o["body"]["criteria_version"]) for o in opinions]
    cited: set[str] = set()
    for opinion in opinions:
        cited.update(opinion["body"].get("criteria") or [])
    return _Opinion(
        decision=state.status,
        version=min(versions),
        cited=frozenset(cited),
        order_key=max(_order_key(o) for o in opinions),
    )


def _manual_stale_events(repo: Repo) -> list[dict[str, Any]]:
    """`note` events recorded by `mark_manual_stale` -- see that function."""
    note_dir = repo.path("events", "note")
    if not note_dir.exists():
        return []
    events: list[dict[str, Any]] = []
    for path in sorted(note_dir.glob("*.ndjson")):
        events.extend(
            e
            for e in read_events(path)
            if e.get("ev") == "note" and e["body"].get("subject") == _MANUAL_STALE_SUBJECT
        )
    return sort_events(events)


def _order_key(event: dict[str, Any]) -> tuple[str, str]:
    """`(ts, id)`, matching `core.fold.sort_events`'s own tie-break: `ts` has
    only second precision, but `id` is a ULID (millisecond-precision
    timestamp plus randomness) and so still orders two events created in
    the same second correctly, which matters here since a mark and its
    consuming decision can easily land in the same wall-clock second."""
    return event["ts"], event["id"]


def _manual_stale_marks(repo: Repo) -> dict[tuple[str, str], tuple[str, str]]:
    """Latest manual-stale marker order-key per `(stage, record_id)`."""
    marks: dict[tuple[str, str], tuple[str, str]] = {}
    for event in _manual_stale_events(repo):
        payload = json.loads(event["body"]["text"])
        key = (payload["stage"], payload["record"])
        marks[key] = _order_key(event)
    return marks


def mark_manual_stale(
    repo: Repo, *, stage: str, record_id: str, actor: str, rationale: str
) -> dict[str, Any]:
    """`strata rescreen --mark`: force a record stale outside the criteria-change
    mechanism (openspec:staleness#staleness-causes's `manual` reason).

    Implemented as a `note` event (openspec:event-log#event-types:
    "free-form, attaches to any entity") rather than a new event type. A
    mark is "consumed" the moment a fresh `screen` decision is recorded
    after it -- there is no separate un-marking mechanism, matching this
    codebase's append-only, no-delete event log.
    """
    body = {
        "subject": _MANUAL_STALE_SUBJECT,
        "text": canonical_json({"stage": stage, "record": record_id}),
    }
    return append_new_event(
        repo.path("events", "note", f"{actor}.ndjson"), ev="note", actor=actor, body=body
    )


def _compute_stale(
    repo: Repo,
    *,
    actor: str | None,
    extra_changes: Sequence[CriterionChange] = (),
    version_override: int | None = None,
) -> list[StaleRecord]:
    """Shared implementation behind `compute_stale_records` (`actor=None`,
    the aggregate resolved-record view), `rescreen_queue` (`actor=
    <handle>`, that reviewer's own opinion -- see `_effective_opinion`),
    and `preview_criterion_change_impact` (`extra_changes`/
    `version_override`, a hypothetical change layered on top of the real
    ones, for a non-mutating "what would this do" preview)."""
    current_version = (
        version_override
        if version_override is not None
        else int(criteria_mod.read_criteria_doc(repo)["version"])
    )
    changes = [*_criterion_changes(repo), *extra_changes]
    canonical_ids = sorted(
        r["id"]
        for r in records_mod.read_records(repo)
        if r.get("strata", {}).get("canonical", True)
    )
    assign_events = screening_mod.all_assign_events(repo)
    manual_marks = _manual_stale_marks(repo)

    stale_stage_records: dict[str, set[str]] = {stage: set() for stage in _STAGE_ORDER}
    results: list[StaleRecord] = []

    configured = set(screening_mod.configured_stages(repo))
    for stage in _STAGE_ORDER:
        if stage not in configured:
            continue
        all_events = screening_mod.all_screen_events(repo, stage)
        events_by_record: dict[str, list[dict[str, Any]]] = {}
        for event in all_events:
            events_by_record.setdefault(event["body"]["record"], []).append(event)
        adjudicate_events = screening_mod.all_adjudicate_events(repo, stage)
        adjudicate_by_record: dict[str, list[dict[str, Any]]] = {}
        for event in adjudicate_events:
            adjudicate_by_record.setdefault(event["body"]["record"], []).append(event)

        for record_id in canonical_ids:
            state = screening_mod.resolve_record_state(
                repo,
                stage,
                record_id,
                screen_events=events_by_record.get(record_id, []),
                assign_events=assign_events,
                adjudicate_events=adjudicate_by_record.get(record_id, []),
            )
            opinion = _effective_opinion(state, actor=actor)
            if opinion is None:
                continue

            info = evaluate_staleness(
                decision=opinion.decision,  # type: ignore[arg-type]
                cited=opinion.cited,
                decision_version=opinion.version,
                current_version=current_version,
                stage=stage,
                changes=changes,
            )
            reason: str | None = info.reason
            if (
                reason is None
                and stage == "full-text"
                and record_id in stale_stage_records["title-abstract"]
            ):
                reason = "upstream-stale"
            if reason is None:
                mark_key = manual_marks.get((stage, record_id))
                if mark_key is not None and mark_key > opinion.order_key:
                    reason = "manual"
            if reason is None:
                continue

            stale_stage_records[stage].add(record_id)
            results.append(
                StaleRecord(
                    record_id=record_id,
                    stage=stage,
                    prior_decision=opinion.decision,
                    prior_criteria=tuple(sorted(opinion.cited)),
                    reason=reason,
                    since_version=current_version,
                )
            )

    return sorted(results, key=lambda r: (r.stage, r.record_id))


def compute_stale_records(repo: Repo) -> list[StaleRecord]:
    """Every stale resolved decision, across all configured stages.

    Cascading (openspec:staleness#staleness-cascades-across-stages-without-deleting-work): a stale
    `title-abstract` decision marks
    the same record's `full-text` decision stale too (`upstream-stale`),
    layered *after* full-text's own criterion-change staleness so a more
    specific native reason always wins when both would apply.
    """
    return _compute_stale(repo, actor=None)


def stale_records_for_stage(repo: Repo, stage: str) -> list[StaleRecord]:
    return [r for r in compute_stale_records(repo) if r.stage == stage]


def rescreen_queue(repo: Repo, stage: str, actor: str) -> list[StaleRecord]:
    """Stale records at `stage` this actor is assigned to (and so owes a fresh opinion on).

    Uses this actor's *own* opinion for staleness, not the aggregate
    resolved decision -- see `_effective_opinion`'s docstring for why: the
    aggregate view flips to `conflict` (and drops out of consideration
    entirely) the moment one reviewer's fresh opinion disagrees with the
    other's still-stale one, which would otherwise make the second
    reviewer's own, equally-stale opinion vanish from their queue.
    """
    if stage not in screening_mod.configured_stages(repo):
        raise RescreenError(
            f"unknown stage {stage!r}; configured stages are "
            f"{screening_mod.configured_stages(repo)!r}"
        )
    assign_events = screening_mod.all_assign_events(repo)
    stale = [r for r in _compute_stale(repo, actor=actor) if r.stage == stage]
    queue = []
    for record in stale:
        assigned = screening_mod.assigned_actors(
            repo, stage, record.record_id, assign_events=assign_events
        )
        if actor in assigned:
            queue.append(record)
    return queue


def preview_criterion_change_impact(
    repo: Repo,
    *,
    criterion_id: str,
    direction: str,
    origin: str = "edited",
) -> list[StaleRecord]:
    """Non-mutating preview: what `compute_stale_records` would return if
    `criterion_id` were changed this way right now, without writing
    anything (openspec:web-ui#criteria-editor-impact-preview: "The preview MUST be computed
    without mutating anything, MUST update as the direction radio
    changes"). Drives the web criteria editor's live impact panel.

    Layers one hypothetical `CriterionChange`, at a version one past the
    current one (the version this change *would* create), on top of the
    real change history -- exactly the same evaluation
    `compute_stale_records` runs for a change that has actually happened,
    just with `_compute_stale`'s `extra_changes`/`version_override` hooks
    instead of reading the change from a committed `criteria.yaml`.

    `origin="retired"` previews a retirement (direction is irrelevant
    there -- `CriterionChange.effective_direction` always treats a retired
    origin as `loosened`, matching `retire_criterion`'s own behavior); any
    other origin previews an edit with the given `direction`.
    """
    criterion = criteria_mod.get_criterion(repo, criterion_id)
    if criterion is None:
        raise RescreenError(f"no criterion {criterion_id!r}")
    current_version = int(criteria_mod.read_criteria_doc(repo)["version"])
    hypothetical_version = current_version + 1
    hypothetical = CriterionChange(
        criterion_id=criterion_id,
        origin=origin,  # type: ignore[arg-type]
        direction=direction,  # type: ignore[arg-type]
        to_version=hypothetical_version,
        applies_at=frozenset(criterion.get("applies_at") or []),
    )
    return _compute_stale(
        repo,
        actor=None,
        extra_changes=[hypothetical],
        version_override=hypothetical_version,
    )


def regenerate_stale_tsv(repo: Repo) -> str:
    """Regenerate `derived/stale.tsv` (openspec:derived-views#stale-decisions-view)."""
    records = records_mod.index_by_id(records_mod.read_records(repo))
    rows = []
    for stale in compute_stale_records(repo):
        record = records.get(stale.record_id, {})
        title = (record.get("title") or "")[:120]
        rows.append(
            (
                stale.record_id,
                stale.stage,
                stale.prior_decision,
                ";".join(stale.prior_criteria),
                stale.reason,
                str(stale.since_version),
                title,
            )
        )
    rows.sort(key=lambda r: (r[1], r[0]))

    lines = ["\t".join(_STALE_TSV_HEADER)]
    for row in rows:
        lines.append("\t".join(_tsv_escape(cell) for cell in row))
    text = "\n".join(lines) + "\n"

    path = repo.path("derived", "stale.tsv")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return text


def _tsv_escape(cell: str) -> str:
    """openspec:canonical-serialisation#tsv-rules: tabs/CR/LF become a single space."""
    return cell.replace("\t", " ").replace("\r", " ").replace("\n", " ")
