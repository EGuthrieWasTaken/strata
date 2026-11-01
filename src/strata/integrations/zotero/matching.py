"""Matching Zotero items to records by the canonical-key ladder; never by a guess.

Implements openspec:zotero-integration#identity-mapping. A record is identified by the first rung of
a ladder it can stand on: DOI, then PMID, then the other identifiers, then the signature of its
title, year and first author (openspec:record-identity). An item is matched to a record on the first
rung the item has *and* some record shares, and only if exactly one record does. Two records on the
same rung is a result of its own, ambiguous, left to a person.

An item that matches nothing is not forced onto the closest record. Items that score at or above
the review's dedup review threshold against a record are reported as *candidates*, for a person to
decide; everything else is reported as unmatched.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from strata.core.ids import (
    canonical_key,
    normalise_doi,
    normalise_isbn,
    normalise_pmcid,
    normalise_pmid,
)
from strata.dedup.blocking import find_candidate_pairs
from strata.dedup.scoring import score_pair
from strata.integrations.reference_manager import RemoteItem
from strata.integrations.zotero.mapping import absorbed_into

#: The rungs in ladder order, as the mapping's `via` names them.
RUNGS = ("doi", "pmid", "pmcid", "arxiv", "isbn", "signature")

_ARXIV_PREFIX_RE = re.compile(r"^arxiv:")


def ladder(record: Mapping[str, Any]) -> list[tuple[str, str]]:
    """`(rung, value)` for each rung of the ladder the record has, in ladder order."""
    rungs: list[tuple[str, str]] = []
    doi = normalise_doi(record.get("DOI"))
    if doi:
        rungs.append(("doi", doi))
    pmid = normalise_pmid(record.get("PMID"))
    if pmid:
        rungs.append(("pmid", pmid))
    pmcid = normalise_pmcid(record.get("PMCID"))
    if pmcid:
        rungs.append(("pmcid", pmcid))
    arxiv = str(record.get("arXiv") or record.get("arxiv") or "").strip().lower()
    arxiv = _ARXIV_PREFIX_RE.sub("", arxiv)
    if arxiv:
        rungs.append(("arxiv", arxiv))
    isbn = normalise_isbn(record.get("ISBN"))
    if isbn:
        rungs.append(("isbn", isbn))
    key, _deterministic = canonical_key(
        {name: record[name] for name in ("title", "issued", "author") if name in record}
    )
    if key.startswith("sig:"):
        rungs.append(("signature", key))
    return rungs


@dataclass(frozen=True)
class Candidate:
    """A record close enough to an unmatched item to be worth a person's look."""

    record_id: str
    score: float


@dataclass(frozen=True)
class ItemMatch:
    item: RemoteItem
    record_id: str
    via: str


@dataclass(frozen=True)
class AmbiguousItem:
    item: RemoteItem
    via: str
    record_ids: tuple[str, ...]


@dataclass(frozen=True)
class CandidateItem:
    item: RemoteItem
    candidates: tuple[Candidate, ...]


@dataclass
class MatchReport:
    """What matching a set of items against the records found. Every item is in exactly one list."""

    matched: list[ItemMatch] = field(default_factory=list)
    ambiguous: list[AmbiguousItem] = field(default_factory=list)
    candidates: list[CandidateItem] = field(default_factory=list)
    unmatched: list[RemoteItem] = field(default_factory=list)


class RecordIndex:
    """The records of a review, findable by any rung of the ladder.

    A record that was merged into another is found as the record that took it in.
    """

    def __init__(self, records: Sequence[Mapping[str, Any]]) -> None:
        self.records = {str(r["id"]): r for r in records}
        self._canonical = {
            rid: r for rid, r in self.records.items() if r.get("strata", {}).get("canonical", True)
        }
        self._absorbed = absorbed_into(records)
        self._by_rung: dict[tuple[str, str], set[str]] = {}
        for rid, record in self.records.items():
            target = self._absorbed.get(rid, rid)
            if target not in self._canonical:
                continue
            for rung in ladder(record):
                self._by_rung.setdefault(rung, set()).add(target)

    @property
    def canonical(self) -> Mapping[str, Mapping[str, Any]]:
        return self._canonical

    def find(self, item_csl: Mapping[str, Any]) -> tuple[str, set[str]] | None:
        """The first rung of the item that some record shares, with the records that share it."""
        for rung in ladder(item_csl):
            hits = self._by_rung.get(rung)
            if not hits:
                continue
            if rung[0] == "signature":
                hits = {rid for rid in hits if not _dois_differ(item_csl, self._canonical[rid])}
                if not hits:
                    continue
            return rung[0], hits
        return None


def _dois_differ(a: Mapping[str, Any], b: Mapping[str, Any]) -> bool:
    """Two different DOIs are two different papers, however alike their titles
    (openspec:deduplication#scoring: the DOI veto)."""
    doi_a, doi_b = normalise_doi(a.get("DOI")), normalise_doi(b.get("DOI"))
    return bool(doi_a and doi_b and doi_a != doi_b)


def match_items(
    items: Iterable[RemoteItem],
    index: RecordIndex,
    *,
    review_threshold: float | None,
    exclude_records: frozenset[str] = frozenset(),
) -> MatchReport:
    """Sort items into matched, ambiguous, candidate and unmatched.

    `review_threshold` is the dedup review threshold above which a near miss is offered as a
    candidate; `None` looks for exact matches only. `exclude_records` are records not to offer as
    candidates (those already linked).
    """
    report = MatchReport()
    unmatched: list[RemoteItem] = []
    for item in items:
        found = index.find(item.csl)
        if found is None:
            unmatched.append(item)
            continue
        via, record_ids = found
        if len(record_ids) == 1:
            report.matched.append(ItemMatch(item, next(iter(record_ids)), via))
        else:
            report.ambiguous.append(AmbiguousItem(item, via, tuple(sorted(record_ids))))

    suggestions = (
        {}
        if review_threshold is None
        else _candidates(unmatched, index, review_threshold, exclude_records)
    )
    for item in unmatched:
        found_candidates = suggestions.get(item.ref.key)
        if found_candidates:
            report.candidates.append(CandidateItem(item, found_candidates))
        else:
            report.unmatched.append(item)
    return report


def _candidates(
    items: Sequence[RemoteItem],
    index: RecordIndex,
    review_threshold: float,
    exclude_records: frozenset[str],
) -> dict[str, tuple[Candidate, ...]]:
    if not items:
        return {}
    pool: dict[str, dict[str, Any]] = {
        rid: dict(record) for rid, record in index.canonical.items() if rid not in exclude_records
    }
    item_ids = {f"zotero:{item.ref.key}": item for item in items}
    for pseudo_id, item in item_ids.items():
        pool[pseudo_id] = dict(item.csl)
    found: dict[str, list[Candidate]] = {}
    for id_a, id_b in find_candidate_pairs(pool).pairs:
        if (id_a in item_ids) == (id_b in item_ids):
            continue  # two records, or two items: not a question for this mapping
        pseudo_id, record_id = (id_a, id_b) if id_a in item_ids else (id_b, id_a)
        scored = score_pair(pool[record_id], pool[pseudo_id])
        if scored.doi_veto or scored.score < review_threshold:
            continue
        found.setdefault(item_ids[pseudo_id].ref.key, []).append(Candidate(record_id, scored.score))
    return {
        key: tuple(sorted(c, key=lambda x: (-x.score, x.record_id))[:3]) for key, c in found.items()
    }
