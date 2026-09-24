"""The event log: envelope construction, append, and hash-chain validation.

Implements docs/spec/02-repository-format.md §4. This module performs I/O
(appending to and reading NDJSON files); the *pure* reduction of events to
state lives in `strata.core.fold`.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from strata.core.canon import serialise_envelope
from strata.core.ids import new_event_id

TOOL_VERSION = "strata/0.1.0"


class ChainError(ValueError):
    """The hash chain of an event file is broken (`E_CHAIN`)."""


def utc_now_iso() -> str:
    """RFC 3339, UTC, second precision, always `Z` — per docs/spec 02 §4.2."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def compute_digest(envelope: dict[str, Any]) -> str:
    """sha256 over the canonical serialisation of every field except `digest`."""
    payload = {k: v for k, v in envelope.items() if k != "digest"}
    return "sha256:" + hashlib.sha256(serialise_envelope(payload).encode("utf-8")).hexdigest()


def build_envelope(
    *,
    ev: str,
    actor: str,
    seq: int,
    body: dict[str, Any],
    prev: str | None = None,
    ts: str | None = None,
    event_id: str | None = None,
    tool: str = TOOL_VERSION,
) -> dict[str, Any]:
    """Construct a fully-formed, digested event envelope ready to append."""
    envelope: dict[str, Any] = {
        "ev": ev,
        "id": event_id or new_event_id(),
        "ts": ts or utc_now_iso(),
        "actor": actor,
        "seq": seq,
    }
    envelope["body"] = body
    envelope["tool"] = tool
    if prev is not None:
        envelope["prev"] = prev
    envelope["digest"] = compute_digest(envelope)
    return envelope


def read_events(path: Path) -> list[dict[str, Any]]:
    """Read every valid event line from an NDJSON file.

    A partially-written trailing line (no closing brace, e.g. a crashed
    writer) has no valid JSON and MUST be skipped rather than fail — the
    write will complete momentarily (docs/spec 02-repository-format.md §4.2,
    12-architecture.md §4).
    """
    if not path.exists():
        return []
    raw = path.read_bytes()
    lines = raw.split(b"\n")
    if lines and lines[-1] == b"":
        lines = lines[:-1]
    events: list[dict[str, Any]] = []
    last_index = len(lines) - 1
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            if i == last_index:
                continue
            raise ChainError(
                f"{path}: line {i + 1} is not valid JSON and is not the last line"
            ) from None
    return events


@dataclass(frozen=True)
class ChainViolation:
    line: int
    event_id: str | None
    reason: str


def verify_chain(path: Path) -> list[ChainViolation]:
    """Validate the per-file hash chain, per docs/spec 02-repository-format.md §4.2.

    Because `git`'s `union` merge driver can interleave independently-grown
    chains, a chain restart is valid iff the restarting line's `prev` matches
    the digest of *some* earlier line in the same file, not necessarily the
    immediately preceding one.
    """
    events = read_events(path)
    violations: list[ChainViolation] = []
    seen_digests: set[str] = set()
    for i, envelope in enumerate(events):
        expected = compute_digest(envelope)
        actual = envelope.get("digest")
        if actual != expected:
            violations.append(
                ChainViolation(line=i + 1, event_id=envelope.get("id"), reason="digest mismatch")
            )
        prev = envelope.get("prev")
        if prev is not None and prev not in seen_digests:
            violations.append(
                ChainViolation(
                    line=i + 1,
                    event_id=envelope.get("id"),
                    reason=f"prev {prev!r} does not match any earlier digest in this file",
                )
            )
        if isinstance(actual, str):
            seen_digests.add(actual)
    return violations


def last_digest(path: Path) -> str | None:
    events = read_events(path)
    return events[-1].get("digest") if events else None


def next_seq(path: Path) -> int:
    """Monotonic per (actor, file) sequence number, per docs/spec 02-repository-format.md §4.2."""
    events = read_events(path)
    if not events:
        return 1
    return max(int(e["seq"]) for e in events) + 1


def append_event(path: Path, envelope: dict[str, Any]) -> None:
    """Append one complete, digested event line atomically.

    A single `os.write` of a line under `PIPE_BUF` is atomic on POSIX, per
    docs/spec/12-architecture.md §4.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    line = (serialise_envelope(envelope) + "\n").encode("utf-8")
    fd = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o644)
    try:
        os.write(fd, line)
    finally:
        os.close(fd)


def append_new_event(
    path: Path,
    *,
    ev: str,
    actor: str,
    body: dict[str, Any],
    tool: str = TOOL_VERSION,
) -> dict[str, Any]:
    """Build the next envelope for `path` (correct seq and prev) and append it."""
    envelope = build_envelope(
        ev=ev,
        actor=actor,
        seq=next_seq(path),
        body=body,
        prev=last_digest(path),
        tool=tool,
    )
    append_event(path, envelope)
    return envelope


def append_new_events(
    path: Path,
    entries: Sequence[tuple[str, str, dict[str, Any]]],
    *,
    tool: str = TOOL_VERSION,
) -> list[dict[str, Any]]:
    """Append many new events to `path` in one pass: `(ev, actor, body)` triples.

    Semantically identical to calling `append_new_event` once per entry, in
    order, but reads `path` once instead of once per entry.
    `append_new_event` computes `seq`/`prev` by re-reading and re-parsing the
    *whole* file on every call (`next_seq`/`last_digest`, both via
    `read_events`) -- fine for a one-off append, but O(n) per call and
    therefore O(n^2) over a loop of n appends. That is exactly the pattern a
    bulk operation hits: `strata import` emits one `record-add` event per
    imported row, and a 1,500-row import was measured spending 24 of its 26
    seconds inside `append_new_event` before this function existed. This
    tracks the running `seq`/`prev` in memory across `entries` instead of
    re-deriving them from disk each time.

    Each event line is still written with its own `append_event` call rather
    than one write for the whole batch: `append_event`'s docstring notes that
    a single write under `PIPE_BUF` is atomic on POSIX, a property a single
    call spanning many events could exceed and lose. A crash mid-batch loses
    at most the not-yet-written remainder -- the same failure mode as if the
    caller invoked `append_new_event` in a loop, just far fewer reads to get
    there.
    """
    if not entries:
        return []
    seq = next_seq(path)
    prev = last_digest(path)
    envelopes = []
    for ev, actor, body in entries:
        envelope = build_envelope(ev=ev, actor=actor, seq=seq, body=body, prev=prev, tool=tool)
        append_event(path, envelope)
        envelopes.append(envelope)
        seq += 1
        prev = envelope["digest"]
    return envelopes


def iter_event_files(root: Path) -> Sequence[Path]:
    """All event NDJSON files under `events/`, including numbered shards."""
    events_dir = root / "events"
    if not events_dir.exists():
        return []
    return sorted(events_dir.rglob("*.ndjson"))
