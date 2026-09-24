"""Full provenance chain for one record: `strata why <id>` (docs/spec/10-cli.md §2).

Read-only: walks every event file for events that reference a record id
(`record-add`, `import`, `dedup-merge`/`dedup-distinct`/`dedup-unmerge`,
`record-amend`), resolves the `search` a record's import points at, and
assembles the result into the chain docs/spec/15-roadmap.md's M1 acceptance
bar names explicitly: "`strata why` shows the full import and dedup
provenance chain."

`strata why` also covers reports, studies, and effects per
docs/spec/10-cli.md §2, but those don't exist until later milestones --
this module only builds a record's chain.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from strata.core.events import iter_event_files, read_events
from strata.core.repo import Repo
from strata.protocol import searches as searches_mod

_DEDUP_EVENT_TYPES = frozenset({"dedup-merge", "dedup-distinct", "dedup-unmerge"})


@dataclass(frozen=True)
class ProvenanceEntry:
    """One step in a record's provenance chain, in the order it should be shown."""

    kind: str
    ts: str | None
    actor: str | None
    detail: dict[str, Any]


def _involves_record(event: dict[str, Any], record_id: str) -> bool:
    body = event.get("body", {})
    return record_id in (
        body.get("canonical"),
        body.get("absorbed"),
        body.get("a"),
        body.get("b"),
        body.get("restored"),
    )


def build_provenance(repo: Repo, record_id: str) -> list[ProvenanceEntry]:
    """A record's provenance chain: search, import, record-add, amendments, dedup.

    Dedup events are chronological (a record can be merged, undone, and
    re-merged over time); the rest lead with search since that's the start
    of a record's life, even though a search document has no event
    timestamp of its own to sort by.
    """
    events = [e for path in iter_event_files(repo.root) for e in read_events(path)]

    record_add = next(
        (e for e in events if e.get("ev") == "record-add" and e["body"].get("record") == record_id),
        None,
    )
    import_event = None
    if record_add is not None:
        import_id = record_add["body"].get("import_id")
        import_event = next(
            (
                e
                for e in events
                if e.get("ev") == "import" and e["body"].get("import_id") == import_id
            ),
            None,
        )
    search_doc = None
    if import_event is not None:
        search_id = import_event["body"].get("search_id")
        search_doc = searches_mod.get_search(repo, search_id) if search_id else None

    entries: list[ProvenanceEntry] = []
    if search_doc is not None:
        entries.append(
            ProvenanceEntry(
                kind="search", ts=None, actor=search_doc.get("executed_by"), detail=search_doc
            )
        )
    if import_event is not None:
        entries.append(
            ProvenanceEntry(
                kind="import",
                ts=import_event.get("ts"),
                actor=import_event.get("actor"),
                detail=import_event["body"],
            )
        )
    if record_add is not None:
        entries.append(
            ProvenanceEntry(
                kind="record-add",
                ts=record_add.get("ts"),
                actor=record_add.get("actor"),
                detail=record_add["body"],
            )
        )

    amendments = [
        ProvenanceEntry(kind="record-amend", ts=e.get("ts"), actor=e.get("actor"), detail=e["body"])
        for e in events
        if e.get("ev") == "record-amend" and e["body"].get("record") == record_id
    ]
    dedup_entries = [
        ProvenanceEntry(kind=e["ev"], ts=e.get("ts"), actor=e.get("actor"), detail=e["body"])
        for e in events
        if e.get("ev") in _DEDUP_EVENT_TYPES and _involves_record(e, record_id)
    ]
    entries.extend(sorted(amendments + dedup_entries, key=lambda entry: entry.ts or ""))
    return entries
