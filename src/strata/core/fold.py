"""The fold: event log -> current state.

Implements docs/spec/02-repository-format.md §4.3. This module is **pure**:
no I/O, no clock, no randomness, no git (docs/spec/12-architecture.md §2,
invariant 1). Every function here takes events already in memory and returns
a value; nothing here reads a file or knows what a repository is.

This module is one of the five held to 100% branch coverage
(docs/spec/14-testing.md §1), because a bug here silently corrupts every
derived view built on top of it.
"""

from __future__ import annotations

from collections.abc import Callable, Hashable, Iterable
from dataclasses import dataclass, field
from typing import Any, TypeVar

Event = dict[str, Any]
K = TypeVar("K", bound=Hashable)

# docs/spec/01-domain-model.md §4 — screening states.
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

    Needed for IRR (docs/spec/02-repository-format.md §6.5): an opinion
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
    """The resolved state of one (stage, record), per docs/spec 02 §4.3."""

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
