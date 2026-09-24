"""Wiring the pure staleness engine to real repository state.

Implements docs/spec/06-workflow-screening.md §4.4 (cascading staleness) and
§6 (the re-screening workflow), plus docs/spec/02-repository-format.md §6.4
(`derived/stale.tsv`). `strata.protocol.staleness` is deliberately pure and
knows nothing about a repository, an actor, or a fold; this module is the
impure half that reads criteria-change events, screen/adjudicate events, and
`core.fold`'s resolution to decide which *resolved* records are stale, and
drives `strata rescreen`.

**Multi-reviewer staleness, a documented simplification.** §4.1 defines
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
§4.2's rule only ever applies to an individual, unresolved opinion. This
module only computes staleness for *resolved* (`include`/`exclude`)
decisions, matching every reason `derived/stale.tsv`'s own reason table
lists staleness against (docs/spec/06 §5's table has no "conflict" reason).
Per-opinion staleness for a still-open conflict is a real, deliberately
deferred refinement -- `protocol.staleness.evaluate_staleness` already
supports it directly if a future session wants it.
"""

from __future__ import annotations

import json
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


def _resolved_decision(
    state: ScreeningState,
) -> tuple[str, int, frozenset[str]] | None:
    """`(decision, decision_version, cited)` for a resolved record, or `None`.

    See the module docstring for the min-version/union-citation heuristic
    this uses to collapse a multi-opinion agreement into one decision.
    """
    if state.status not in ("include", "exclude"):
        return None
    if state.adjudication is not None:
        body = state.adjudication["body"]
        version = body.get("criteria_version")
        if version is None:
            return None
        return state.status, int(version), frozenset(body.get("criteria") or [])
    opinions = list(state.opinions.values())
    if not opinions:
        return None
    versions = [int(o["body"]["criteria_version"]) for o in opinions]
    cited: set[str] = set()
    for opinion in opinions:
        cited.update(opinion["body"].get("criteria") or [])
    return state.status, min(versions), frozenset(cited)


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
    mechanism (docs/spec/06 §5's `manual` reason).

    Implemented as a `note` event (docs/spec/02-repository-format.md §4.4:
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


def _latest_decision_order_key(state: ScreeningState) -> tuple[str, str] | None:
    keys = [_order_key(o) for o in state.opinions.values()]
    if state.adjudication is not None:
        keys.append(_order_key(state.adjudication))
    return max(keys) if keys else None


def compute_stale_records(repo: Repo) -> list[StaleRecord]:
    """Every stale resolved decision, across all configured stages.

    Cascading (docs/spec/06 §4.4): a stale `title-abstract` decision marks
    the same record's `full-text` decision stale too (`upstream-stale`),
    layered *after* full-text's own criterion-change staleness so a more
    specific native reason always wins when both would apply.
    """
    current_version = int(criteria_mod.read_criteria_doc(repo)["version"])
    changes = _criterion_changes(repo)
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
            resolved = _resolved_decision(state)
            if resolved is None:
                continue
            decision, decision_version, cited = resolved

            info = evaluate_staleness(
                decision=decision,  # type: ignore[arg-type]
                cited=cited,
                decision_version=decision_version,
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
                decided_key = _latest_decision_order_key(state)
                if mark_key is not None and decided_key is not None and mark_key > decided_key:
                    reason = "manual"
            if reason is None:
                continue

            stale_stage_records[stage].add(record_id)
            results.append(
                StaleRecord(
                    record_id=record_id,
                    stage=stage,
                    prior_decision=decision,
                    prior_criteria=tuple(sorted(cited)),
                    reason=reason,
                    since_version=current_version,
                )
            )

    return sorted(results, key=lambda r: (r.stage, r.record_id))


def stale_records_for_stage(repo: Repo, stage: str) -> list[StaleRecord]:
    return [r for r in compute_stale_records(repo) if r.stage == stage]


def rescreen_queue(repo: Repo, stage: str, actor: str) -> list[StaleRecord]:
    """Stale records at `stage` this actor is assigned to (and so owes a fresh opinion on)."""
    if stage not in screening_mod.configured_stages(repo):
        raise RescreenError(
            f"unknown stage {stage!r}; configured stages are "
            f"{screening_mod.configured_stages(repo)!r}"
        )
    assign_events = screening_mod.all_assign_events(repo)
    queue = []
    for record in stale_records_for_stage(repo, stage):
        assigned = screening_mod.assigned_actors(
            repo, stage, record.record_id, assign_events=assign_events
        )
        if actor in assigned:
            queue.append(record)
    return queue


def regenerate_stale_tsv(repo: Repo) -> str:
    """Regenerate `derived/stale.tsv` (docs/spec/02-repository-format.md §6.4)."""
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
    """docs/spec/02-repository-format.md §5.4: tabs/CR/LF become a single space."""
    return cell.replace("\t", " ").replace("\r", " ").replace("\n", " ")
