"""Full-text retrieval: the queue of reports sought and what became of each.

Implements openspec:full-text-retrieval. A *report* is a canonical record promoted out of
title/abstract screening (`rpt_` + the record's 16 characters). Every outcome of working the
queue is a `retrieval` event in `events/retrieval/<actor>.ndjson`; an obtained document is also
recorded by identifier and version in `fulltext/manifest.ndjson` (never by file hash, and never
as a committed file: openspec:domain-model#full-text-files-are-never-committed).

`open the DOI in a browser` and `skip` are navigation, not outcomes: they change nothing about a
report, so they are not events. A report skipped in one session is simply offered again in the
next, exactly like an unscreened record.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from strata.core import fulltext as fulltext_mod
from strata.core import records as records_mod
from strata.core.events import append_new_event, read_events
from strata.core.fold import (
    NOT_RETRIEVED,
    RETRIEVAL_ILL_REQUESTED,
    RETRIEVAL_RETRIEVED,
    RETRIEVAL_SOUGHT,
    RetrievalState,
    fold_retrieval,
)
from strata.core.ids import record_id_for_report, report_id
from strata.core.repo import Repo
from strata.core.validate import validate, validate_event_body
from strata.protocol import screening as screening_mod

# openspec:full-text-retrieval#not-retrieved-reasons — the fixed vocabulary.
NOT_RETRIEVED_REASONS = (
    "no-access",
    "not-found",
    "retracted",
    "language",
    "no-response-from-author",
    "other",
)
STATUSES = (RETRIEVAL_SOUGHT, RETRIEVAL_ILL_REQUESTED, RETRIEVAL_RETRIEVED, NOT_RETRIEVED)
_OPEN_STATUSES = frozenset({RETRIEVAL_SOUGHT, RETRIEVAL_ILL_REQUESTED})


class RetrievalError(ValueError):
    pass


@dataclass
class RetrievalCounts:
    """How the reports sought stand. `outstanding` is sought + interlibrary-loan requested."""

    sought: int = 0
    retrieved: int = 0
    ill_requested: int = 0
    not_retrieved: int = 0
    outstanding: int = 0
    reasons: dict[str, int] = field(default_factory=dict)


def _events_path(repo: Repo, actor: str) -> Path:
    return repo.path("events", "retrieval", f"{actor}.ndjson")


def all_retrieval_events(repo: Repo) -> list[dict[str, Any]]:
    directory = repo.path("events", "retrieval")
    if not directory.exists():
        return []
    events: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.ndjson")):
        events.extend(e for e in read_events(path) if e.get("ev") == "retrieval")
    return events


def sought_reports(repo: Repo) -> list[str]:
    """Report ids sought: canonical records whose title/abstract state resolved to `include`."""
    stage = screening_mod.configured_stages(repo)[0]
    return [report_id(r) for r in screening_mod.included_record_ids(repo, stage)]


def retrieval_states(repo: Repo) -> dict[str, RetrievalState]:
    return fold_retrieval(all_retrieval_events(repo))


def status_of(states: dict[str, RetrievalState], report: str) -> str:
    state = states.get(report)
    return state.status if state else RETRIEVAL_SOUGHT


def outstanding_reports(repo: Repo) -> list[str]:
    """Reports still to retrieve, in id order: nothing recorded yet, or an ILL request pending."""
    states = retrieval_states(repo)
    return [r for r in sought_reports(repo) if status_of(states, r) in _OPEN_STATUSES]


def not_retrieved_record_ids(repo: Repo) -> set[str]:
    """Record ids of sought reports marked not retrievable (feeds the full-text screening state)."""
    states = retrieval_states(repo)
    return {
        record_id_for_report(r)
        for r in sought_reports(repo)
        if status_of(states, r) == NOT_RETRIEVED
    }


def retrieval_counts(repo: Repo, *, sought: list[str] | None = None) -> RetrievalCounts:
    """The numbers the flow diagram's "Reports sought / not retrieved" boxes are built from.

    `sought` lets a caller that has already resolved title/abstract screening (`strata status`)
    pass the report ids in rather than resolving every record's state a second time.
    """
    states = retrieval_states(repo)
    counts = RetrievalCounts()
    for report in sought if sought is not None else sought_reports(repo):
        counts.sought += 1
        status = status_of(states, report)
        if status == RETRIEVAL_RETRIEVED:
            counts.retrieved += 1
        elif status == NOT_RETRIEVED:
            counts.not_retrieved += 1
            reason = states[report].event["body"].get("reason", "other")
            counts.reasons[reason] = counts.reasons.get(reason, 0) + 1
        else:
            counts.outstanding += 1
            if status == RETRIEVAL_ILL_REQUESTED:
                counts.ill_requested += 1
    counts.reasons = dict(sorted(counts.reasons.items()))
    return counts


def record_retrieval(
    repo: Repo,
    *,
    report: str,
    status: str,
    actor: str,
    source: str | None = None,
    locator: dict[str, str] | None = None,
    version: str | None = None,
    reason: str | None = None,
    reason_text: str | None = None,
    path: str | None = None,
    related: list[dict[str, str]] | None = None,
    sha256: str | None = None,
    retrieved_on: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    """Record one outcome for a report: a `retrieval` event, plus a manifest entry if retrieved.

    `sought` reopens a report (the appended correction that undoes an earlier outcome).
    Everything is validated before anything is written, so a rejected manifest entry never
    leaves a stray event behind.
    """
    if status not in STATUSES:
        raise RetrievalError(f"status must be one of {STATUSES}, got {status!r}")
    if report not in set(sought_reports(repo)):
        raise RetrievalError(
            f"{report!r} is not a report sought (its record must be included at "
            "title/abstract screening)"
        )

    body: dict[str, Any] = {"report": report, "status": status}
    manifest_entry: dict[str, Any] | None = None

    if status == RETRIEVAL_RETRIEVED:
        record = records_mod.get_record(repo, record_id_for_report(report)) or {}
        resolved = dict(locator) if locator else fulltext_mod.locator_from_record(record)
        if not resolved:
            raise RetrievalError(
                f"{report!r} has no DOI or other identifier on its record; pass a locator"
            )
        if not source:
            raise RetrievalError("a retrieved document needs a source (e.g. institutional-access)")
        resolved_version = version or "unknown"
        manifest_entry = {
            "report": report,
            "locator": resolved,
            "version": resolved_version,
            "retrieved": retrieved_on or datetime.now(UTC).date().isoformat(),
            "source": source,
            "actor": actor,
        }
        if path:
            manifest_entry["path"] = path
        if related:
            manifest_entry["related"] = related
        if sha256:
            manifest_entry["sha256"] = sha256
        validate("fulltext-entry", manifest_entry)
        body.update(source=source, locator=resolved, version=resolved_version)
    elif status == NOT_RETRIEVED:
        if reason not in NOT_RETRIEVED_REASONS:
            raise RetrievalError(
                f"a report marked not retrievable needs a reason from {NOT_RETRIEVED_REASONS}"
            )
        if reason == "other" and not (reason_text or "").strip():
            raise RetrievalError("reason 'other' needs free text saying what happened")
        body["reason"] = reason
        if reason_text:
            body["reason_text"] = reason_text.strip()
    elif status == RETRIEVAL_ILL_REQUESTED:
        body["source"] = source or "interlibrary-loan"

    if note:
        body["note"] = note
    validate_event_body("retrieval", body)
    if manifest_entry is not None:
        fulltext_mod.append_manifest_entry(repo, manifest_entry)
    return append_new_event(_events_path(repo, actor), ev="retrieval", actor=actor, body=body)
