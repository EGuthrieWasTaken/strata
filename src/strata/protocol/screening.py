"""Screening: docs/spec/06-workflow-screening.md §1-§2, §7; docs/spec/10-cli.md
§"Screening" (`strata screen`, `strata assign`).

Combines `strata.core.fold.resolve_screening` (the pure state-resolution
logic, built in M0 in anticipation of this milestone) with the repository
I/O and validation that turn it into `strata screen`/`strata assign`:
reading `events/screen/<stage>.<actor>.ndjson` and
`events/assign/<actor>.ndjson`, validating a decision against the active
criteria set, and appending the `screen`/`assign` events themselves.

Blinding (docs/spec/06 §2) is structural, not a runtime check: each
reviewer's `screen` events live in their own file
(docs/spec/02-repository-format.md §4.5), and nothing in this module ever
reads *another* actor's opinion to decide what to show the current one --
`stage_queue` only ever asks "does `actor` have an opinion on this record
yet", never what that opinion (or anyone else's) actually is.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from strata.core import manifest as manifest_mod
from strata.core import records as records_mod
from strata.core.events import append_new_event, append_new_events, read_events
from strata.core.fold import ScreeningState, fold_last_write_wins, resolve_screening, sort_events
from strata.core.repo import Repo
from strata.protocol import criteria as criteria_mod

Decision = Literal["include", "exclude", "maybe"]
_DECISIONS: tuple[Decision, ...] = ("include", "exclude", "maybe")

_DECISIONS_TSV_HEADER = ("record_id", "decision", "criteria", "note")


class ScreeningError(ValueError):
    pass


def configured_stages(repo: Repo) -> list[str]:
    stages = repo.config.get("screening", {}).get("stages")
    return list(stages) if stages else list(manifest_mod.DEFAULT_STAGES)


def _screen_events_path(repo: Repo, stage: str, actor: str) -> Path:
    return repo.path("events", "screen", f"{stage}.{actor}.ndjson")


def _assign_events_path(repo: Repo, actor: str) -> Path:
    return repo.path("events", "assign", f"{actor}.ndjson")


def all_screen_events(repo: Repo, stage: str) -> list[dict[str, Any]]:
    """Every `screen` event at `stage`, across all reviewers' files."""
    screen_dir = repo.path("events", "screen")
    if not screen_dir.exists():
        return []
    events: list[dict[str, Any]] = []
    for path in sorted(screen_dir.glob(f"{stage}.*.ndjson")):
        events.extend(e for e in read_events(path) if e.get("ev") == "screen")
    return events


def all_assign_events(repo: Repo) -> list[dict[str, Any]]:
    assign_dir = repo.path("events", "assign")
    if not assign_dir.exists():
        return []
    events: list[dict[str, Any]] = []
    for path in sorted(assign_dir.glob("*.ndjson")):
        events.extend(e for e in read_events(path) if e.get("ev") == "assign")
    return events


def _default_assignment(repo: Repo, stage: str) -> frozenset[str]:
    configured = repo.config.get("screening", {}).get("assignment", {}).get(stage)
    if configured:
        return frozenset(configured)
    actors = repo.config.get("actors", [])
    return frozenset(a["handle"] for a in actors if a.get("role") in ("screener", "lead"))


def assigned_actors(
    repo: Repo, stage: str, record_id: str, *, assign_events: list[dict[str, Any]] | None = None
) -> frozenset[str]:
    """Reviewers assigned to `(stage, record_id)`.

    The most recent `assign` event naming this record at this stage wins
    (last-write-wins, like every other fold in this codebase); with no such
    event, falls back to `[screening.assignment]` in `strata.toml`, or every
    configured `screener`/`lead` actor if that is unset too.
    """
    events = assign_events if assign_events is not None else all_assign_events(repo)
    matching = [
        e for e in events if e["body"]["stage"] == stage and record_id in e["body"]["records"]
    ]
    if matching:
        latest = sort_events(matching)[-1]
        return frozenset(latest["body"]["actors"])
    return _default_assignment(repo, stage)


def resolve_record_state(
    repo: Repo,
    stage: str,
    record_id: str,
    *,
    screen_events: list[dict[str, Any]] | None = None,
    assign_events: list[dict[str, Any]] | None = None,
) -> ScreeningState:
    """A single record's resolved screening state at `stage` (docs/spec 02 §4.3)."""
    events = screen_events if screen_events is not None else all_screen_events(repo, stage)
    record_events = [e for e in events if e["body"]["record"] == record_id]
    assigned = assigned_actors(repo, stage, record_id, assign_events=assign_events)
    return resolve_screening(assigned=assigned, screen_events=record_events)


def stage_queue(
    repo: Repo, stage: str, actor: str, *, only_ids: set[str] | None = None
) -> list[str]:
    """Record ids assigned to `actor` at `stage` this actor has not yet opined on.

    Sorted by id for a deterministic, resumable order (docs/spec/11-web-ui.md
    S14/S8): closing and reopening a session simply re-derives the same
    queue, minus whatever has since been decided.
    """
    if stage not in configured_stages(repo):
        raise ScreeningError(
            f"unknown stage {stage!r}; configured stages are {configured_stages(repo)!r}"
        )
    canonical_ids = sorted(
        r["id"]
        for r in records_mod.read_records(repo)
        if r.get("strata", {}).get("canonical", True)
    )
    all_events = all_screen_events(repo, stage)
    assign_events = all_assign_events(repo)
    events_by_record: dict[str, list[dict[str, Any]]] = {}
    for event in all_events:
        events_by_record.setdefault(event["body"]["record"], []).append(event)

    queue = []
    for record_id in canonical_ids:
        if only_ids is not None and record_id not in only_ids:
            continue
        assigned = assigned_actors(repo, stage, record_id, assign_events=assign_events)
        if actor not in assigned:
            continue
        opinions = fold_last_write_wins(
            events_by_record.get(record_id, []), key_fn=lambda e: e["actor"]
        )
        if actor in opinions:
            continue
        queue.append(record_id)
    return queue


def _active_criteria_for_stage(repo: Repo, stage: str) -> dict[str, dict[str, Any]]:
    return {
        c["id"]: c
        for c in criteria_mod.list_criteria(repo)
        if c["status"] == "active" and stage in c["applies_at"]
    }


def _validate_and_build_body(
    repo: Repo,
    *,
    stage: str,
    record_id: str,
    decision: str,
    cited: list[str] | None,
    note: str | None,
    confidence: str | None,
    imported: bool,
) -> dict[str, Any]:
    if stage not in configured_stages(repo):
        raise ScreeningError(
            f"unknown stage {stage!r}; configured stages are {configured_stages(repo)!r}"
        )
    if decision not in _DECISIONS:
        raise ScreeningError(f"decision must be one of {_DECISIONS}, got {decision!r}")
    if records_mod.get_record(repo, record_id) is None:
        raise ScreeningError(f"no record {record_id!r}")

    cited_ids = sorted(set(cited or []))
    applicable = _active_criteria_for_stage(repo, stage)
    for cid in cited_ids:
        if cid not in applicable:
            raise ScreeningError(
                f"{cid!r} is not an active criterion that applies at stage {stage!r}"
            )

    require_reason = bool(repo.config.get("screening", {}).get("require_exclusion_reason", True))
    if decision == "exclude" and not cited_ids:
        if stage == "full-text":
            raise ScreeningError(
                "an exclude decision at full-text always requires at least one cited "
                "criterion (docs/spec/06 §7)"
            )
        if require_reason:
            raise ScreeningError(
                "an exclude decision requires at least one cited criterion "
                "(screening.require_exclusion_reason is set)"
            )

    doc = criteria_mod.read_criteria_doc(repo)
    body: dict[str, Any] = {
        "stage": stage,
        "record": record_id,
        "decision": decision,
        "criteria": cited_ids,
        "criteria_version": doc["version"],
        "criteria_digest": doc["digest"],
    }
    if note:
        body["note"] = note
    if confidence:
        body["confidence"] = confidence
    if imported:
        body["imported"] = True
    return body


def record_screen_decision(
    repo: Repo,
    *,
    stage: str,
    record_id: str,
    decision: Decision,
    actor: str,
    cited: list[str] | None = None,
    note: str | None = None,
    confidence: str | None = None,
) -> dict[str, Any]:
    """Append one `screen` event: docs/spec/02-repository-format.md §4.4.

    A reviewer who changes their mind simply calls this again for the same
    `(stage, record_id, actor)` -- last-write-wins already handles the
    correction (`u`ndo in the CLI/web UI is exactly this, not a delete).
    """
    body = _validate_and_build_body(
        repo,
        stage=stage,
        record_id=record_id,
        decision=decision,
        cited=cited,
        note=note,
        confidence=confidence,
        imported=False,
    )
    return append_new_event(
        _screen_events_path(repo, stage, actor), ev="screen", actor=actor, body=body
    )


def _parse_decisions_tsv(text: str) -> list[dict[str, str]]:
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return []
    header = tuple(lines[0].split("\t"))
    if header != _DECISIONS_TSV_HEADER:
        raise ScreeningError(
            f"decisions file must have header {'/'.join(_DECISIONS_TSV_HEADER)!r}, got {header!r}"
        )
    rows = []
    for i, line in enumerate(lines[1:], start=2):
        cells = line.split("\t")
        if len(cells) != len(_DECISIONS_TSV_HEADER):
            raise ScreeningError(
                f"line {i}: expected {len(_DECISIONS_TSV_HEADER)} columns, got {len(cells)}"
            )
        rows.append(dict(zip(_DECISIONS_TSV_HEADER, cells, strict=True)))
    return rows


def import_decisions_tsv(repo: Repo, *, stage: str, text: str, actor: str) -> list[dict[str, Any]]:
    """`strata screen --decisions <file>` (docs/spec/10-cli.md §5).

    Every row is attributed to `actor` and marked `imported: true` in the
    event body, "because their independence cannot be verified." All rows
    are appended in one batch (`append_new_events`) rather than one
    `append_new_event` call per row.
    """
    rows = _parse_decisions_tsv(text)
    entries: list[tuple[str, str, dict[str, Any]]] = []
    for row in rows:
        criteria_cell = row["criteria"].strip()
        cited = [c.strip() for c in criteria_cell.split(";") if c.strip()] if criteria_cell else []
        body = _validate_and_build_body(
            repo,
            stage=stage,
            record_id=row["record_id"].strip(),
            decision=row["decision"].strip(),
            cited=cited,
            note=row["note"].strip() or None,
            confidence=None,
            imported=True,
        )
        entries.append(("screen", actor, body))
    if not entries:
        return []
    return append_new_events(_screen_events_path(repo, stage, actor), entries)


def assign_reviewers(
    repo: Repo,
    *,
    stage: str,
    actors: list[str],
    record_ids: list[str],
    actor: str,
    filter_expr: str | None = None,
) -> dict[str, Any]:
    """`strata assign`: docs/spec/02-repository-format.md §4.4's `assign` event."""
    if stage not in configured_stages(repo):
        raise ScreeningError(
            f"unknown stage {stage!r}; configured stages are {configured_stages(repo)!r}"
        )
    if not actors:
        raise ScreeningError("actors must be non-empty")
    if not record_ids:
        raise ScreeningError("no records matched to assign")

    body: dict[str, Any] = {
        "stage": stage,
        "records": sorted(set(record_ids)),
        "actors": sorted(set(actors)),
    }
    if filter_expr:
        body["filter"] = filter_expr
    return append_new_event(_assign_events_path(repo, actor), ev="assign", actor=actor, body=body)
