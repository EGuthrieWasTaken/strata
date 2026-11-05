"""Full provenance chain for one record: `strata why <id>` (openspec:cli).

Read-only: walks every event file for events that reference a record id
(`record-add`, `import`, `dedup-merge`/`dedup-distinct`/`dedup-unmerge`,
`record-amend`), resolves the `search` a record's import points at, and
assembles the result into the chain docs/roadmap.md's M1 acceptance
bar names explicitly: "`strata why` shows the full import and dedup
provenance chain."

`strata why` also covers reports, studies, and effects per
openspec:cli, but those don't exist until later milestones --
this module only builds a record's chain.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from strata.core import agents as agents_mod
from strata.core import fieldedit as fieldedit_mod
from strata.core.events import iter_event_files, read_events
from strata.core.repo import Repo
from strata.protocol import screening as screening_mod
from strata.protocol import searches as searches_mod
from strata.protocol import suggestions as suggestions_mod

_DEDUP_EVENT_TYPES = frozenset({"dedup-merge", "dedup-distinct", "dedup-unmerge"})


@dataclass(frozen=True)
class ProvenanceEntry:
    """One step in a record's provenance chain, in the order it should be shown."""

    kind: str
    ts: str | None
    actor: str | None
    detail: dict[str, Any]
    #: The `agent` envelope key, when an AI agent caused the event: the model as it reported
    #: itself (a claim `strata` cannot verify), the client and the person who started the session.
    agent: dict[str, Any] | None = None


def ai_label(agent: dict[str, Any]) -> str:
    """How an agent's work is labelled wherever it is shown: it is AI, which model (as reported)
    and whose session. Never conveyed by colour alone (openspec:web-ui#agent-work-is-labelled)."""
    client = agent.get("client") or {}
    via = f" via {client['name']}" + (f" {client['version']}" if client.get("version") else "")
    return (
        f"AI: model {agent.get('model', '?')} (self-reported){via if client.get('name') else ''}, "
        f"invoked by {agent.get('invoked_by', '?')}"
    )


def _involves_record(event: dict[str, Any], record_id: str) -> bool:
    body = event.get("body", {})
    return record_id in (
        body.get("canonical"),
        body.get("absorbed"),
        body.get("a"),
        body.get("b"),
        body.get("restored"),
    )


def _readable(body: dict[str, Any]) -> dict[str, Any]:
    """A `record-amend` body with authors and dates written as a person would read them."""
    field = body.get("field")
    if field not in ("author", "issued"):
        return body
    return {
        **body,
        "old": fieldedit_mod.format_field_value(field, body.get("old")),
        "new": fieldedit_mod.format_field_value(field, body.get("new")),
    }


def _judgement_entries(repo: Repo, record_id: str) -> list[ProvenanceEntry]:
    """Who decided a record at each stage, and the suggestions made about it.

    Reviewers are blinded to each other
    (openspec:screening#dual-independent-screening-with-blinding), and a provenance query has no
    particular reader, so a stage's decisions are shown only once the
    record is resolved there or conflicted, when every assigned reviewer has decided, or when the
    review does not blind its reviewers. Suggestions follow the same rule unless the review has
    chosen to show them always.
    """
    blind = bool(repo.config.get("screening", {}).get("blind_reviewers", True))
    show_always = agents_mod.show_suggestions(repo) == agents_mod.SHOW_ALWAYS
    shown_stages: set[str] = set()
    entries: list[ProvenanceEntry] = []
    for stage in screening_mod.configured_stages(repo):
        state = screening_mod.resolve_record_state(repo, stage, record_id)
        if blind and state.status in ("unscreened", "partial"):
            continue
        shown_stages.add(stage)
        events = [
            e
            for e in screening_mod.all_screen_events(repo, stage)
            + screening_mod.all_adjudicate_events(repo, stage)
            if e["body"].get("record") == record_id
        ]
        entries.extend(
            ProvenanceEntry(
                kind=e["ev"],
                ts=e.get("ts"),
                actor=e.get("actor"),
                detail=e["body"],
                agent=e.get("agent"),
            )
            for e in events
        )
    for suggestion in suggestions_mod.suggestions(repo):
        concerns_record = suggestion.record == record_id
        if not concerns_record:
            continue
        hidden = suggestion.stage is not None and blind and not show_always
        if hidden and suggestion.stage not in shown_stages:
            continue
        entries.append(
            ProvenanceEntry(
                kind="suggestion",
                ts=suggestion.ts,
                actor=suggestion.actor,
                detail={
                    "id": suggestion.id,
                    "op": suggestion.op,
                    "args": suggestion.args,
                    "rationale": suggestion.rationale,
                    "status": suggestion.status,
                },
                agent=suggestion.agent or None,
            )
        )
        if suggestion.resolution is not None:
            resolution = suggestion.resolution
            entries.append(
                ProvenanceEntry(
                    kind="suggestion-resolve",
                    ts=resolution.get("ts"),
                    actor=resolution.get("by"),
                    detail={
                        "suggestion": suggestion.id,
                        "outcome": resolution["outcome"],
                        "reason": resolution["reason"],
                        **({"result": resolution["result"]} if resolution.get("result") else {}),
                    },
                )
            )
    return entries


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
        ProvenanceEntry(
            kind="record-amend", ts=e.get("ts"), actor=e.get("actor"), detail=_readable(e["body"])
        )
        for e in events
        if e.get("ev") == "record-amend" and e["body"].get("record") == record_id
    ]
    dedup_entries = [
        ProvenanceEntry(kind=e["ev"], ts=e.get("ts"), actor=e.get("actor"), detail=e["body"])
        for e in events
        if e.get("ev") in _DEDUP_EVENT_TYPES and _involves_record(e, record_id)
    ]
    entries.extend(
        sorted(
            amendments + dedup_entries + _judgement_entries(repo, record_id),
            key=lambda entry: entry.ts or "",
        )
    )
    return entries
