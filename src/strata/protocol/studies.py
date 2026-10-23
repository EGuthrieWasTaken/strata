"""Study grouping: reports -> studies (openspec:study-grouping).

A *study* is the unit of extraction and of clustering in analysis; a *report* is one paper
about it. Counting the same study twice is one of the commonest serious errors in published
meta-analyses, so every grouping and splitting decision carries a rationale and is an event
(`study-group` / `study-split`) a reader of the review can see.

Suggestions are heuristics that point at likely groupings and splits and always show their
evidence; nothing here ever applies one (openspec:study-grouping#suggestions-only).
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from itertools import combinations
from pathlib import Path
from typing import Any

from strata.core import records as records_mod
from strata.core.events import append_new_event, read_events
from strata.core.fold import StudyMap, fold_studies
from strata.core.ids import (
    new_study_id,
    record_id_for_report,
    report_id,
    singleton_study_id,
)
from strata.core.repo import Repo
from strata.core.validate import validate_event_body
from strata.protocol import screening as screening_mod

_SUGGESTION_SUBJECT = "study-suggestion"


class StudyError(ValueError):
    pass


# --- reading the current grouping ------------------------------------------------------------


def _events_path(repo: Repo, actor: str) -> Path:
    return repo.path("events", "study", f"{actor}.ndjson")


def all_study_events(repo: Repo) -> list[dict[str, Any]]:
    directory = repo.path("events", "study")
    if not directory.exists():
        return []
    events: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.ndjson")):
        events.extend(e for e in read_events(path) if e.get("ev") in ("study-group", "study-split"))
    return events


def included_reports(repo: Repo) -> list[str]:
    """Reports of included studies: records that resolved to `include` at the last stage and
    were not excluded at an earlier one.

    A title/abstract reversal to exclude must take the study out of the review even though its
    full-text `include` is retained in the log; anything already extracted for it becomes an
    orphan, kept (openspec:staleness#staleness-cascades-across-stages-without-deleting-work).
    """
    stages = screening_mod.configured_stages(repo)
    included = set(screening_mod.included_record_ids(repo, stages[-1]))
    for stage in stages[:-1]:
        included -= {
            record_id
            for record_id, state in screening_mod.stage_states(repo, stage).items()
            if state.status == "exclude"
        }
    return [report_id(r) for r in sorted(included)]


def study_map(repo: Repo, *, reports: list[str] | None = None) -> StudyMap:
    return fold_studies(
        reports if reports is not None else included_reports(repo),
        all_study_events(repo),
        singleton_study_id,
    )


# --- deciding --------------------------------------------------------------------------------


def _require_rationale(rationale: str) -> str:
    text = rationale.strip()
    if not text:
        raise StudyError("a rationale is required for every grouping and splitting decision")
    return text


def group_reports(
    repo: Repo,
    *,
    reports: list[str],
    actor: str,
    rationale: str,
    study: str | None = None,
) -> dict[str, Any]:
    """Make `reports` one study. With `study`, redefine that existing study instead of minting
    a new id (ids are permanent: openspec:record-identity#identifiers-for-other-entities)."""
    text = _require_rationale(rationale)
    unique = sorted(set(reports))
    if not unique:
        raise StudyError("name at least one report to group")
    included = included_reports(repo)
    unknown = [r for r in unique if r not in set(included)]
    if unknown:
        raise StudyError(f"not included reports: {', '.join(unknown)}")
    current = study_map(repo, reports=included)
    if study is not None and study not in current.members:
        raise StudyError(f"no study {study!r}")
    body = {"study": study or new_study_id(), "reports": unique, "rationale": text}
    validate_event_body("study-group", body)
    return append_new_event(_events_path(repo, actor), ev="study-group", actor=actor, body=body)


def split_report(
    repo: Repo, *, report: str, parts: int, actor: str, rationale: str
) -> dict[str, Any]:
    """Split one report into `parts` independent studies (a multi-experiment paper)."""
    text = _require_rationale(rationale)
    if parts < 2:
        raise StudyError("a report is split into at least 2 studies")
    if report not in set(included_reports(repo)):
        raise StudyError(f"not an included report: {report}")
    body = {"report": report, "studies": [new_study_id() for _ in range(parts)], "rationale": text}
    validate_event_body("study-split", body)
    return append_new_event(_events_path(repo, actor), ev="study-split", actor=actor, body=body)


def dismiss_suggestion(repo: Repo, *, reports: list[str], actor: str, kind: str) -> dict[str, Any]:
    """Remember "keep separate" / "keep as one" so the same suggestion is not raised again."""
    body = {
        "subject": _SUGGESTION_SUBJECT,
        "kind": kind,
        "reports": sorted(set(reports)),
        "text": f"{kind}: {', '.join(sorted(set(reports)))}",
    }
    return append_new_event(
        repo.path("events", "note", f"{actor}.ndjson"), ev="note", actor=actor, body=body
    )


def _dismissed(repo: Repo) -> set[tuple[str, tuple[str, ...]]]:
    directory = repo.path("events", "note")
    found: set[tuple[str, tuple[str, ...]]] = set()
    if not directory.exists():
        return found
    for path in sorted(directory.glob("*.ndjson")):
        for event in read_events(path):
            body = event.get("body", {})
            if event.get("ev") == "note" and body.get("subject") == _SUGGESTION_SUBJECT:
                found.add((body["kind"], tuple(body["reports"])))
    return found


# --- suggestions (pure) ----------------------------------------------------------------------

_REGISTRATION = re.compile(
    r"\b(NCT\d{8}|ISRCTN\d{8}|ACTRN\d{14}|DRKS\d{8}|UMIN\d{9}|NTR\d{3,5}|"
    r"CHICTR-?[A-Z]*-?\d{6,10}|EUDRACT\s*\d{4}-\d{6}-\d{2}|CTRI/\d{4}/\d{2,3}/\d{5,7})\b",
    re.IGNORECASE,
)
_SAMPLE = re.compile(
    r"\bn\s*=\s*(\d[\d,]*)|\b(\d[\d,]*)\s+(?:participants|patients|students|children|adults|"
    r"subjects|women|men|individuals|people|volunteers|infants|adolescents)\b",
    re.IGNORECASE,
)
_FOLLOW_UP = re.compile(
    r"\b(follow[- ]?up (?:study|of|analysis|results)|secondary analysis|post[- ]?hoc analysis|"
    r"long[- ]term follow[- ]?up|extension (?:study|phase)|ancillary study|sub[- ]?study)\b",
    re.IGNORECASE,
)
_NUMBER_WORDS = {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6}
_MULTI_STUDY = re.compile(
    r"\b(two|three|four|five|six|[2-6])\s+(?:independent\s+|separate\s+|randomi[sz]ed\s+)?"
    r"(experiments|studies|trials|samples|cohorts)\b",
    re.IGNORECASE,
)
_MIN_SAMPLE = 10  # smaller numbers ("n = 3 groups") are not a sample size worth matching on


@dataclass(frozen=True)
class GroupSuggestion:
    reports: tuple[str, ...]
    evidence: tuple[str, ...]


@dataclass(frozen=True)
class SplitSuggestion:
    report: str
    parts: int
    evidence: str


@dataclass
class Suggestions:
    groupings: list[GroupSuggestion] = field(default_factory=list)
    splits: list[SplitSuggestion] = field(default_factory=list)


def _text(record: dict[str, Any]) -> str:
    parts = [record.get("title"), record.get("abstract"), record.get("note")]
    keywords = record.get("keyword")
    if isinstance(keywords, list):
        parts.extend(str(k) for k in keywords)
    elif keywords:
        parts.append(str(keywords))
    return " ".join(str(p) for p in parts if p)


def _registrations(record: dict[str, Any]) -> set[str]:
    return {re.sub(r"[\s-]", "", m).upper() for m in _REGISTRATION.findall(_text(record))}


def _families(record: dict[str, Any]) -> list[str]:
    names = []
    for author in record.get("author") or []:
        name = author.get("family") or author.get("literal") if isinstance(author, dict) else author
        if name:
            names.append(str(name).strip().lower())
    return names


def _sample_sizes(record: dict[str, Any]) -> set[int]:
    sizes = set()
    for match in _SAMPLE.finditer(_text(record)):
        digits = (match.group(1) or match.group(2)).replace(",", "")
        if int(digits) >= _MIN_SAMPLE:
            sizes.add(int(digits))
    return sizes


def _cited_dois(record: dict[str, Any]) -> set[str]:
    raw = record.get("references") or record.get("strata", {}).get("references") or []
    dois = set()
    for item in raw:
        value = item.get("DOI") if isinstance(item, dict) else item
        if value:
            dois.add(str(value).strip().lower())
    return dois


def _own_doi(record: dict[str, Any]) -> str | None:
    value = record.get("DOI")
    return str(value).strip().lower() if value else None


def _pair_evidence(a: dict[str, Any], b: dict[str, Any]) -> tuple[bool, list[str]]:
    """(decisive, evidence) for one pair of included reports."""
    evidence: list[str] = []
    shared_registry = sorted(_registrations(a) & _registrations(b))
    if shared_registry:
        evidence.append(f"same trial registration: {', '.join(shared_registry)}")
        return True, evidence

    signals = 0
    fa, fb = _families(a), _families(b)
    overlap = set(fa) & set(fb)
    if fa and fb and fa[0] == fb[0] and len(overlap) / min(len(set(fa)), len(set(fb))) >= 0.5:
        evidence.append(f"shared author set ({', '.join(sorted(overlap))})")
        signals += 1
    shared_sizes = sorted(_sample_sizes(a) & _sample_sizes(b))
    if shared_sizes:
        evidence.append("overlapping sample size: " + ", ".join(f"n = {n}" for n in shared_sizes))
        signals += 1
    for record in (a, b):
        phrase = _FOLLOW_UP.search(_text(record))
        if phrase:
            evidence.append(f"follow-up language: {phrase.group(0)!r}")
            signals += 1
            break
    doi_a, doi_b = _own_doi(a), _own_doi(b)
    if (doi_b and doi_b in _cited_dois(a)) or (doi_a and doi_a in _cited_dois(b)):
        evidence.append("the reports cite each other")
        signals += 1
    return signals >= 2, evidence


def suggest_groupings(records_by_report: dict[str, dict[str, Any]]) -> list[GroupSuggestion]:
    """Connected components of reports that look like the same study, with their evidence."""
    parent = {r: r for r in records_by_report}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    evidence: dict[tuple[str, str], list[str]] = {}
    for a, b in combinations(sorted(records_by_report), 2):
        decisive, notes = _pair_evidence(records_by_report[a], records_by_report[b])
        if decisive:
            evidence[(a, b)] = notes
            parent[find(a)] = find(b)

    components: dict[str, list[str]] = defaultdict(list)
    for report in sorted(records_by_report):
        components[find(report)].append(report)
    suggestions = []
    for members in components.values():
        if len(members) < 2:
            continue
        merged: list[str] = []
        for (a, b), pair_notes in sorted(evidence.items()):
            if a in members and b in members:
                merged.extend(n for n in pair_notes if n not in merged)
        suggestions.append(GroupSuggestion(reports=tuple(members), evidence=tuple(merged)))
    return sorted(suggestions, key=lambda s: s.reports)


def suggest_splits(records_by_report: dict[str, dict[str, Any]]) -> list[SplitSuggestion]:
    """Reports whose own text says they describe several independent experiments or studies."""
    suggestions = []
    for report, record in sorted(records_by_report.items()):
        match = _MULTI_STUDY.search(_text(record))
        if not match:
            continue
        word = match.group(1).lower()
        parts = _NUMBER_WORDS.get(word) or int(word)
        suggestions.append(SplitSuggestion(report=report, parts=parts, evidence=match.group(0)))
    return suggestions


def suggestions(repo: Repo) -> Suggestions:
    """Open suggestions: not already acted on, not dismissed. Never applied automatically."""
    included = included_reports(repo)
    current = study_map(repo, reports=included)
    records = records_mod.index_by_id(records_mod.read_records(repo))
    by_report = {
        r: records[record_id_for_report(r)] for r in included if record_id_for_report(r) in records
    }
    dismissed = _dismissed(repo)

    result = Suggestions()
    for group in suggest_groupings(by_report):
        same_study = len({current.studies_of[r] for r in group.reports}) == 1
        if same_study or ("keep-separate", tuple(sorted(group.reports))) in dismissed:
            continue
        result.groupings.append(group)
    for split in suggest_splits(by_report):
        already_split = len(current.studies_of[split.report]) > 1
        if already_split or ("keep-as-one", (split.report,)) in dismissed:
            continue
        result.splits.append(split)
    return result
