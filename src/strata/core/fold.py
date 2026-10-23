"""The fold: event log -> current state.

Implements openspec:event-log#the-fold. This module is **pure**:
no I/O, no clock, no randomness, no git (openspec:architecture#module-boundaries,
invariant 1). Every function here takes events already in memory and returns
a value; nothing here reads a file or knows what a repository is.

This module is one of the five held to 100% branch coverage
(openspec:test-suite#test-levels-and-coverage-floors), because a bug here silently corrupts every
derived view built on top of it.
"""

from __future__ import annotations

from collections.abc import Callable, Hashable, Iterable
from dataclasses import dataclass, field
from typing import Any, TypeVar

Event = dict[str, Any]
K = TypeVar("K", bound=Hashable)

# openspec:domain-model#screening-states-per-stage — screening states.
UNSCREENED = "unscreened"
PARTIAL = "partial"
CONFLICT = "conflict"
INCLUDE = "include"
EXCLUDE = "exclude"
NOT_RETRIEVED = "not-retrieved"

_RESOLVED_DECISIONS = frozenset({INCLUDE, EXCLUDE})


def sort_events(events: Iterable[Event]) -> list[Event]:
    """Sort by `(ts, id)` — deterministic regardless of file, merge, or filesystem order."""
    return sorted(events, key=lambda e: (e["ts"], e["id"]))


def dedup_events(events: Iterable[Event]) -> list[Event]:
    """Drop repeats of the same event `id`, keeping the first occurrence. Order-preserving."""
    seen: set[str] = set()
    out: list[Event] = []
    for e in events:
        event_id = e["id"]
        if event_id in seen:
            continue
        seen.add(event_id)
        out.append(e)
    return out


def normalise_events(events: Iterable[Event]) -> list[Event]:
    """Dedup then sort — the canonical preparation step before any fold."""
    return sort_events(dedup_events(events))


def fold_last_write_wins(events: Iterable[Event], key_fn: Callable[[Event], K]) -> dict[K, Event]:
    """Generic last-write-wins reduction: the event log's core mechanic.

    Deterministic (P1): normalises before reducing, so input order never
    matters. Idempotent (P2): duplicate ids collapse in `dedup_events`.
    Convergent under disjoint-set union (P9): the result depends only on the
    normalised order, which is independent of how the input was assembled.
    """
    ordered = normalise_events(events)
    state: dict[K, Event] = {}
    for e in ordered:
        state[key_fn(e)] = e
    return state


def fold_first_write(events: Iterable[Event], key_fn: Callable[[Event], K]) -> dict[K, Event]:
    """Like `fold_last_write_wins`, but keeps the *first* event per key.

    Needed for IRR (openspec:derived-views#inter-rater-reliability-view): an opinion
    changed after seeing another reviewer's decision must be excluded from
    inter-rater reliability, which requires keeping each actor's first
    opinion on a record as well as their last.
    """
    ordered = normalise_events(events)
    state: dict[K, Event] = {}
    for e in ordered:
        key = key_fn(e)
        if key not in state:
            state[key] = e
    return state


@dataclass(frozen=True)
class ScreeningState:
    """The resolved state of one (stage, record), per openspec:event-log#the-fold."""

    status: str
    opinions: dict[str, Event] = field(default_factory=dict)
    first_opinions: dict[str, Event] = field(default_factory=dict)
    adjudication: Event | None = None


def resolve_screening(
    *,
    assigned: frozenset[str],
    screen_events: Iterable[Event],
    adjudicate_events: Iterable[Event] = (),
) -> ScreeningState:
    """Resolve a record's screening state at one stage from its raw events.

    `screen_events` and `adjudicate_events` MUST already be filtered to the
    one `(stage, record)` this call resolves; this function does not know
    what a stage or a record is, only how to reduce opinions about one.
    """
    opinions = fold_last_write_wins(screen_events, key_fn=lambda e: e["actor"])
    first_opinions = fold_first_write(screen_events, key_fn=lambda e: e["actor"])
    adjudications = fold_last_write_wins(adjudicate_events, key_fn=lambda _e: "adjudication")
    adjudication = next(iter(adjudications.values()), None)

    if adjudication is not None:
        status = adjudication["body"]["decision"]
    elif not opinions:
        status = UNSCREENED
    elif len(opinions) < len(assigned):
        status = PARTIAL
    else:
        decisions = {e["body"]["decision"] for e in opinions.values()}
        if "maybe" in decisions or len(decisions) > 1:
            status = CONFLICT
        else:
            (status,) = decisions

    return ScreeningState(
        status=status,
        opinions=opinions,
        first_opinions=first_opinions,
        adjudication=adjudication,
    )


def apply_undo(events: Iterable[Event], undone_event_id: str) -> list[Event]:
    """Drop one event by id, for `strata rescreen`/`--undo` flows (P13: undo inverts).

    Undo is implemented by removing the offending event from the fold input
    rather than appending a tombstone, because the fold is defined purely
    over the events that exist; the caller is responsible for recording the
    undo itself as an auditable event elsewhere in the log.
    """
    return [e for e in events if e["id"] != undone_event_id]


# openspec:full-text-retrieval — retrieval states. A report with no `retrieval` event is
# `sought`; `NOT_RETRIEVED` above is shared with the full-text screening state of the same name.
RETRIEVAL_SOUGHT = "sought"
RETRIEVAL_ILL_REQUESTED = "ill-requested"
RETRIEVAL_RETRIEVED = "retrieved"


@dataclass(frozen=True)
class RetrievalState:
    """The resolved retrieval state of one report: its latest `retrieval` event wins."""

    status: str
    event: Event


def fold_retrieval(events: Iterable[Event]) -> dict[str, RetrievalState]:
    """Resolve `retrieval` events to a state per report (last write wins across actors).

    A report absent from the result has no retrieval event and is therefore `sought`.
    Undoing an outcome is an appended `sought` event, like every other correction.
    """
    latest = fold_last_write_wins(events, key_fn=lambda e: e["body"]["report"])
    return {
        report: RetrievalState(status=e["body"]["status"], event=e) for report, e in latest.items()
    }


@dataclass(frozen=True)
class StudyMap:
    """Reports grouped into studies, as folded from `study-group` / `study-split` events."""

    members: dict[str, tuple[str, ...]]
    studies_of: dict[str, tuple[str, ...]]
    defined_by: dict[str, Event]


def fold_studies(
    report_ids: Iterable[str],
    study_events: Iterable[Event],
    singleton_study: Callable[[str], str],
) -> StudyMap:
    """Fold grouping and splitting decisions over `report_ids` (openspec:study-grouping).

    Every report starts as a study of one (`singleton_study(report)`). In `(ts, id)` order:

    - `study-group {study, reports}` makes `study` consist of exactly `reports`: each listed
      report leaves its other studies (except the sibling studies of a split it is part of,
      when `study` is one of them), and a report dropped from `study` falls back to its
      remaining studies, or to its own singleton.
    - `study-split {report, studies}` makes the one report belong to exactly those studies.

    Events naming a report outside `report_ids` (not an included report) are ignored here;
    `strata verify` is what flags a reference to a report that does not exist at all.
    """
    reports = sorted(set(report_ids))
    edges: dict[str, set[str]] = {r: {singleton_study(r)} for r in reports}
    split_into: dict[str, set[str]] = {}
    defined_by: dict[str, Event] = {}

    for event in normalise_events(study_events):
        body = event["body"]
        if event["ev"] == "study-group":
            study = body["study"]
            members = {r for r in body["reports"] if r in edges}
            for report, studies in edges.items():
                if study in studies and report not in members:
                    studies.discard(study)
                    if report in split_into:
                        split_into[report].discard(study)
                    if not studies:
                        studies.add(singleton_study(report))
            for report in members:
                kept = (
                    split_into.get(report, set()) if study in split_into.get(report, ()) else set()
                )
                if kept:
                    split_into[report] = kept
                else:
                    split_into.pop(report, None)
                edges[report] = set(kept) | {study}
            defined_by[study] = event
        else:
            report = body["report"]
            if report not in edges:
                continue
            studies = set(body["studies"])
            edges[report] = set(studies)
            split_into[report] = set(studies)
            for study in studies:
                defined_by[study] = event

    members_of: dict[str, list[str]] = {}
    for report in reports:
        for study in edges[report]:
            members_of.setdefault(study, []).append(report)
    return StudyMap(
        members={study: tuple(rs) for study, rs in sorted(members_of.items())},
        studies_of={report: tuple(sorted(edges[report])) for report in reports},
        defined_by={s: e for s, e in defined_by.items() if s in members_of},
    )
