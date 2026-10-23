"""The merge drivers and the normalisation of merged event files.

Implements openspec:git-integration#merge-drivers and
openspec:event-log#merged-event-files-are-normalised-and-re-linked.

* `merge-regenerate` is the driver for derived files: they are discarded and regenerated after the
  merge, so it ignores all three sides and writes nothing.
* `merge-records` is the three-way, field-wise merge of `records/records.ndjson` keyed by record id.
  Anything it had to decide on its own (both sides changed a field) is appended to
  `.strata/cache/merge-notes.ndjson`, which `strata sync` turns into `record-amend` events and
  reports; an automatic resolution is never silent.
* `normalise_event_file` rewrites an event file into `(ts, id)` order, drops exact duplicate ids
  and re-links the hash chain, so the union merge of a same-actor divergence reads as one linear
  history.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from strata.core.canon import canonical_json, serialise_envelope
from strata.core.events import compute_digest, read_events

NOTES_PATH = (".strata", "cache", "merge-notes.ndjson")
_ABSENT = object()


def merge_regenerate() -> None:
    """Derived files are regenerated after the merge; nothing to decide here."""


# --- records --------------------------------------------------------------------------------


@dataclass
class Resolution:
    record: str
    field: str
    old: Any
    new: Any
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "record": self.record,
            "field": self.field,
            "old": self.old,
            "new": self.new,
            "reason": self.reason,
        }


def _parse(text: str) -> dict[str, dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    for line in text.splitlines():
        if line.strip():
            record = json.loads(line)
            found[str(record["id"])] = record
    return found


def _same(a: Any, b: Any) -> bool:
    return canonical_json(a) == canonical_json(b)


def _trust_rank(record: dict[str, Any], trust: list[str]) -> int:
    """Lower is more trusted: the best-ranked source of the record, by database or platform."""
    ranks = []
    for source in record.get("strata", {}).get("sources", []):
        for key in ("database", "platform"):
            name = str(source.get(key, "")).lower()
            if name in trust:
                ranks.append(trust.index(name))
    return min(ranks) if ranks else len(trust)


def _both_changed(
    field: str,
    ours: Any,
    theirs: Any,
    o_rec: dict[str, Any],
    t_rec: dict[str, Any],
    trust: list[str],
) -> tuple[Any, str]:
    """Decide a scalar both sides changed, and say how."""
    o_rank, t_rank = _trust_rank(o_rec, trust), _trust_rank(t_rec, trust)
    if o_rank != t_rank:
        winner = ours if o_rank < t_rank else theirs
        return winner, "the more trusted source (dedup.source_trust) wins"
    if field == "abstract" and isinstance(ours, str) and isinstance(theirs, str):
        return (ours if len(ours) >= len(theirs) else theirs), "the longer abstract wins"
    pick = min((ours, theirs), key=canonical_json)
    return pick, "the lexicographically smaller value wins"


def _merge_sources(ours: list[Any], theirs: list[Any]) -> list[Any]:
    merged = list(ours)
    seen = {canonical_json(s) for s in ours}
    for source in theirs:
        if canonical_json(source) not in seen:
            merged.append(source)
            seen.add(canonical_json(source))
    return merged


def _merge_one(
    base: dict[str, Any] | None,
    ours: dict[str, Any],
    theirs: dict[str, Any],
    trust: list[str],
) -> tuple[dict[str, Any], list[Resolution]]:
    record_id = str(ours["id"])
    resolutions: list[Resolution] = []
    merged: dict[str, Any] = {}
    base = base or {}
    for key in sorted({*ours, *theirs}):
        o, t, b = ours.get(key, _ABSENT), theirs.get(key, _ABSENT), base.get(key, _ABSENT)
        if key == "strata":
            continue
        if (o is _ABSENT) != (t is _ABSENT) and b is _ABSENT:
            value = t if o is _ABSENT else o  # added on one side only
        elif _same(o, t):
            value = o
        elif _same(o, b):
            value = t
        elif _same(t, b):
            value = o
        else:
            value, reason = _both_changed(key, o, t, ours, theirs, trust)
            resolutions.append(Resolution(record_id, key, o if value is t else t, value, reason))
        if value is not _ABSENT:
            merged[key] = value
    # strata's own block: sources as a set union, a merged-away record stays merged away, and
    # anything else follows the same rules as a field.
    o_s, t_s, b_s = ours.get("strata", {}), theirs.get("strata", {}), base.get("strata", {})
    block: dict[str, Any] = {}
    for key in sorted({*o_s, *t_s}):
        o, t, b = o_s.get(key, _ABSENT), t_s.get(key, _ABSENT), b_s.get(key, _ABSENT)
        if key == "sources":
            block[key] = _merge_sources(list(o_s.get(key, [])), list(t_s.get(key, [])))
        elif key == "canonical":
            block[key] = bool(o is not False and t is not False)
        elif o is _ABSENT or t is _ABSENT:
            block[key] = t if o is _ABSENT else o
        elif _same(o, t):
            block[key] = o
        elif _same(o, b):
            block[key] = t
        elif _same(t, b):
            block[key] = o
        else:
            block[key], reason = _both_changed(f"strata.{key}", o, t, ours, theirs, trust)
            resolutions.append(Resolution(record_id, f"strata.{key}", o, block[key], reason))
    if block:
        merged["strata"] = block
    return merged, resolutions


def merge_records_text(
    base: str, ours: str, theirs: str, *, trust: list[str] | None = None
) -> tuple[str, list[Resolution]]:
    """The merged `records.ndjson` (sorted by id, canonical serialisation) and what had to be
    decided automatically."""
    ranked = [t.lower() for t in (trust or [])]
    b, o, t = _parse(base), _parse(ours), _parse(theirs)
    merged: dict[str, dict[str, Any]] = {}
    resolutions: list[Resolution] = []
    for record_id in sorted({*o, *t}):
        if record_id not in t:
            merged[record_id] = o[record_id]
        elif record_id not in o:
            merged[record_id] = t[record_id]
        elif _same(o[record_id], t[record_id]):
            merged[record_id] = o[record_id]
        else:
            merged[record_id], found = _merge_one(
                b.get(record_id), o[record_id], t[record_id], ranked
            )
            resolutions.extend(found)
    text = "".join(canonical_json(r) + "\n" for r in merged.values())
    return text, resolutions


def merge_records_files(
    base: Path, ours: Path, theirs: Path, *, trust: list[str], notes: Path | None = None
) -> list[Resolution]:
    """git's driver contract: write the result over `ours`; exit status 0 means merged."""

    def read(path: Path) -> str:
        return path.read_text(encoding="utf-8") if path.exists() else ""

    text, resolutions = merge_records_text(read(base), read(ours), read(theirs), trust=trust)
    ours.write_text(text, encoding="utf-8", newline="\n")
    if resolutions and notes is not None:
        notes.parent.mkdir(parents=True, exist_ok=True)
        with notes.open("a", encoding="utf-8", newline="\n") as handle:
            for r in resolutions:
                handle.write(canonical_json(r.to_dict()) + "\n")
    return resolutions


def read_notes(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


# --- event files ----------------------------------------------------------------------------


@dataclass
class Relink:
    file: str
    lines_reordered: int
    duplicates_dropped: int
    reason: str


def _order(event: dict[str, Any]) -> tuple[str, str]:
    return str(event["ts"]), str(event["id"])


def normalise_event_file(path: Path, *, relative: str) -> Relink | None:
    """Put `path` in canonical `(ts, id)` order with a linear, valid chain; `None` if it already is.

    Returns what was changed so the rewrite can be recorded as a `relink` event.
    """
    events = read_events(path)
    if any("ts" not in e or "id" not in e for e in events):
        return None  # not an event file this module can order; `strata verify` will say so
    ordered = sorted(events, key=_order)
    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    for event in ordered:
        if str(event["id"]) not in seen:
            seen.add(str(event["id"]))
            unique.append(event)
    dropped = len(events) - len(unique)
    reordered = sum(
        1 for before, after in zip(events, ordered, strict=True) if before["id"] != after["id"]
    )
    linked: list[dict[str, Any]] = []
    previous: str | None = None
    for index, event in enumerate(unique, start=1):
        envelope = {k: v for k, v in event.items() if k not in ("prev", "digest")}
        envelope["seq"] = index
        if previous is not None:
            envelope["prev"] = previous
        envelope["digest"] = compute_digest(envelope)
        previous = envelope["digest"]
        linked.append(envelope)
    if linked == events:
        return None
    text = "".join(serialise_envelope(e) + "\n" for e in linked)
    path.write_text(text, encoding="utf-8", newline="\n")
    return Relink(relative, reordered, dropped, "merge of divergent appends")
