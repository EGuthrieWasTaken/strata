"""A record's provenance as sentences: who did what, when, and why (openspec:web-ui#screens).

`strata.core.provenance.build_provenance` gives the chain as events: a kind and a body of stored
keys. That is right for `strata why --json` and wrong for a page a reviewer reads, where
`RECORD-AMEND`, `executed_by` and `new None` are noise. `describe` turns each entry into a
sentence, a reason where one was recorded, and a short list of labelled details. Reasons for
corrections are in the commits that recorded them (the event holds the old and new values), so
they are read from the history.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from strata.core.logcmd import DomainCommit
from strata.core.provenance import ProvenanceEntry

_FIELD_NAMES = {
    "issued": "date",
    "container-title": "journal",
    "DOI": "DOI",
    "PMID": "PMID",
    "ISSN": "ISSN",
    "author": "authors",
    "page": "pages",
}
_SEARCH_LABELS = (
    ("database", "Database"),
    ("platform", "Platform"),
    ("executed", "Run on"),
    ("executed_by", "Run by"),
    ("hits", "Hits"),
    ("query", "Query"),
    ("limits", "Limits"),
    ("notes", "Notes"),
    ("peer_reviewed_by", "Peer reviewed by"),
    ("export_files", "Export files"),
)
_STALE_QUERY = "PENDING"


@dataclass(frozen=True)
class Step:
    """One line of the timeline."""

    label: str
    text: str
    when: str = ""
    why: str = ""
    details: list[tuple[str, str]] = field(default_factory=list)
    agent: dict[str, Any] | None = None


def when(ts: str | None) -> str:
    """`6 Nov 2026, 13:04 UTC` for an ISO timestamp; the text itself if it is not one; nothing
    for nothing.

    Always in UTC, and saying so: events are stamped in UTC and commits in the zone of whoever
    made them, and a reviewer elsewhere reads both on one page."""
    if not ts:
        return ""
    try:
        moment = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return ts
    if moment.tzinfo is None:
        return f"{moment.day} {moment.strftime('%b %Y, %H:%M')}"
    moment = moment.astimezone(UTC)
    return f"{moment.day} {moment.strftime('%b %Y, %H:%M')} UTC"


def shown(value: Any) -> str:
    """A stored value as a person would write it: no `None`, no brackets, no quotes."""
    if value is None or value == "" or value == []:
        return "none"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, list | tuple):
        return ", ".join(shown(v) for v in value)
    if isinstance(value, dict):
        return "; ".join(f"{label_of(k)}: {shown(v)}" for k, v in value.items())
    return str(value)


def label_of(key: str) -> str:
    """`peer_reviewed_by` -> `Peer reviewed by`."""
    return key.replace("_", " ").replace("-", " ").strip().capitalize()


def field_name(name: Any) -> str:
    return _FIELD_NAMES.get(str(name), str(name))


def _quoted(value: Any) -> str:
    return f"“{shown(value)}”"


def correction_reasons(record_id: str, commits: list[DomainCommit]) -> dict[str, list[str]]:
    """The reasons given for corrections to `record_id`, oldest first, by the field corrected.

    A correction is committed as `fix(<record>): corrected <field>` with the reason as the
    message's body. `commits` is newest first, as `domain_log` returns it."""
    reasons: dict[str, list[str]] = {}
    prefix = f"fix({record_id}): corrected "
    for commit in reversed(commits):
        if commit.trailers.get("Op") == "fix" and commit.subject.startswith(prefix):
            reasons.setdefault(commit.subject[len(prefix) :].strip(), []).append(commit.reason)
    return reasons


def _who(entry: ProvenanceEntry) -> str:
    return entry.actor or "Someone"


def _correction(entry: ProvenanceEntry, reasons: dict[str, list[str]]) -> Step:
    body = entry.detail
    stored = str(body.get("field"))
    name = field_name(stored)
    old, new = body.get("old"), body.get("new")
    if new in (None, "", []):
        text = f"{_who(entry)} removed the {name} (it was {_quoted(old)})."
    elif old in (None, "", []):
        text = f"{_who(entry)} filled in the {name}: {_quoted(new)}."
    else:
        text = (
            f"{_who(entry)} corrected the {name}: it was {_quoted(old)} and is now {_quoted(new)}."
        )
    # `strata fix --field year` is recorded as a correction to `issued`.
    queue = reasons.get(stored) or (reasons.get("year") if stored == "issued" else None) or []
    why = queue.pop(0) if queue else ""
    details = []
    if body.get("source") and body.get("source") != "manual":
        details.append(("How", shown(body["source"])))
    return Step("Correction", text, when(entry.ts), why, details, entry.agent)


def _decision(entry: ProvenanceEntry) -> Step:
    body = entry.detail
    decision = str(body.get("decision", "")).upper()
    cited = body.get("criteria") or []
    citing = f", citing {shown(cited)}" if cited else ""
    if entry.kind == "adjudicate":
        text = f"{_who(entry)} settled the disagreement at {body.get('stage')}: {decision}{citing}."
        return Step(
            "Adjudication", text, when(entry.ts), str(body.get("rationale") or ""), [], entry.agent
        )
    text = f"{_who(entry)} decided {decision} at {body.get('stage')}{citing}."
    details = (
        [("Criteria version", f"v{body['criteria_version']}")]
        if body.get("criteria_version")
        else []
    )
    if body.get("confidence"):
        details.append(("Confidence", shown(body["confidence"])))
    return Step(
        "Screening", text, when(entry.ts), str(body.get("note") or ""), details, entry.agent
    )


def _dedup(entry: ProvenanceEntry, record_id: str) -> Step:
    body = entry.detail
    who = _who(entry)
    if entry.kind == "dedup-merge":
        if body.get("canonical") == record_id:
            text = f"{who} merged {body.get('absorbed')} into this record as a duplicate of it."
        else:
            text = f"{who} merged this record into {body.get('canonical')} as a duplicate of it."
    elif entry.kind == "dedup-unmerge":
        text = f"{who} undid a merge: {body.get('restored')} is a record of its own again."
    else:
        other = body.get("b") if body.get("a") == record_id else body.get("a")
        text = f"{who} kept this record and {other} apart: they are not duplicates."
    details = []
    if body.get("score") is not None:
        details.append(("Similarity", shown(body["score"])))
    if body.get("method"):
        details.append(("Method", shown(body["method"])))
    return Step("Duplicates", text, when(entry.ts), str(body.get("rationale") or ""), details)


def describe(
    entry: ProvenanceEntry, *, record_id: str, reasons: dict[str, list[str]] | None = None
) -> Step:
    """`entry` as a line of the timeline. `reasons` is `correction_reasons(...)`; it is consumed
    as corrections are described, so describe a record's entries in order."""
    body = entry.detail
    kind = entry.kind
    if kind == "search":
        text = (
            f"Found by the search {body.get('id')} of {body.get('database')}"
            + (f" on {body['platform']}" if body.get("platform") else "")
            + (f", run by {body['executed_by']}" if body.get("executed_by") else "")
            + (f" on {body['executed']}" if body.get("executed") else "")
            + "."
        )
        details = [
            (label, "not recorded yet" if value == _STALE_QUERY else shown(value))
            for key, label in _SEARCH_LABELS[4:]
            if (value := body.get(key)) not in (None, "", [])
        ]
        return Step("Search", text, "", "", details)
    if kind == "import":
        count = body.get("count")
        text = (
            f"{_who(entry)} imported {body.get('source') or 'a file'}"
            + (f" ({count} record{'s' if count != 1 else ''})" if count is not None else "")
            + "."
        )
        return Step("Import", text, when(entry.ts), "", [("Import", shown(body.get("import_id")))])
    if kind == "record-add":
        return Step("Record", "This record was created by that import.", when(entry.ts))
    if kind == "record-amend":
        return _correction(entry, reasons if reasons is not None else {})
    if kind in ("screen", "adjudicate"):
        return _decision(entry)
    if kind in ("dedup-merge", "dedup-distinct", "dedup-unmerge"):
        return _dedup(entry, record_id)
    if kind == "suggestion":
        args = body.get("args") or {}
        text = (
            f"{_who(entry)} suggested: {shown(body.get('op'))}"
            + (f" ({shown(args)})" if args else "")
            + f". It is {shown(body.get('status'))}."
        )
        return Step(
            "Suggestion", text, when(entry.ts), str(body.get("rationale") or ""), [], entry.agent
        )
    if kind == "suggestion-resolve":
        text = f"{_who(entry)} answered the suggestion: {shown(body.get('outcome'))}."
        return Step("Suggestion", text, when(entry.ts), str(body.get("reason") or ""))
    # Anything newer than this module: still no raw keys or Python values.
    details = [(label_of(str(k)), shown(v)) for k, v in body.items()]
    return Step(label_of(kind), f"{_who(entry)} recorded this.", when(entry.ts), "", details)


def timeline(
    entries: list[ProvenanceEntry], *, record_id: str, commits: list[DomainCommit]
) -> list[Step]:
    reasons = correction_reasons(record_id, commits)
    return [describe(entry, record_id=record_id, reasons=reasons) for entry in entries]
