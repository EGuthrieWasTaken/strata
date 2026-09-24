"""Deduplication orchestration: blocking + scoring + merge against a real repository.

Implements docs/spec/05-workflow-import.md §3.1 (stickiness), §3.4
(thresholds and actions), and the event/alias-emitting side of §3.5 that
`strata.dedup.merge`'s pure functions don't touch.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from strata.core import aliases as aliases_mod
from strata.core import records as records_mod
from strata.core.events import append_new_event, append_new_events, iter_event_files, read_events
from strata.core.repo import Repo
from strata.dedup.blocking import find_candidate_pairs
from strata.dedup.merge import choose_canonical, merge_fields
from strata.dedup.scoring import PairScore, score_pair

DEFAULT_AUTO_MERGE_THRESHOLD = 0.95
DEFAULT_REVIEW_THRESHOLD = 0.80

Decision = Literal["merge", "distinct"]


def _pair_key(a: str, b: str) -> tuple[str, str]:
    return (a, b) if a < b else (b, a)


def _as_pairs(events: list[dict[str, Any]]) -> set[tuple[str, str]]:
    """Every pair a prior `dedup-merge`/`dedup-distinct`/`dedup-unmerge` event already decided.

    `dedup-unmerge` also counts as judged (not un-judged): reversing a wrong
    auto-merge should not make the very next `strata dedup` run immediately
    propose the same merge again. A user wanting the pair reconsidered records
    a fresh decision explicitly.
    """
    judged: set[tuple[str, str]] = set()
    for envelope in events:
        body = envelope.get("body", {})
        ev = envelope.get("ev")
        if ev == "dedup-merge":
            judged.add(_pair_key(body["canonical"], body["absorbed"]))
        elif ev == "dedup-distinct":
            judged.add(_pair_key(body["a"], body["b"]))
        elif ev == "dedup-unmerge":
            judged.add(_pair_key(body["canonical"], body["restored"]))
    return judged


def judged_pairs(repo: Repo) -> set[tuple[str, str]]:
    events = [e for path in iter_event_files(repo.root) for e in read_events(path)]
    return _as_pairs(events)


def thresholds(repo: Repo, *, strict: bool) -> tuple[float, float]:
    """`(auto_merge_threshold, review_threshold)`, from `[dedup]` or `--strict`.

    §3.4 describes `--strict` as setting "both thresholds to 1.0, so every
    non-exact pair is reviewed." Taken literally that collapses the review
    band `[review_threshold, auto_merge_threshold)` to the empty interval
    `[1.0, 1.0)`, which would route every non-exact pair to *distinct*
    instead -- the opposite of the stated intent. We implement the intent
    rather than the literal numbers: `auto_merge_threshold` stays 1.0 (only
    an exact/DOI match auto-merges), and `review_threshold` drops to 0.0 so
    every blocked pair that isn't an exact match is queued for review.
    """
    if strict:
        return 1.0, 0.0
    config = repo.config.get("dedup", {})
    return (
        float(config.get("auto_merge_threshold", DEFAULT_AUTO_MERGE_THRESHOLD)),
        float(config.get("review_threshold", DEFAULT_REVIEW_THRESHOLD)),
    )


def source_trust_order(repo: Repo) -> list[str]:
    return list(repo.config.get("dedup", {}).get("source_trust", []))


@dataclass(frozen=True)
class ReviewCandidate:
    record_a: str
    record_b: str
    result: PairScore
    doi_conflict: bool


@dataclass
class DedupOutcome:
    candidate_pairs_considered: int
    auto_merged: list[tuple[str, str]] = field(default_factory=list)
    review_queue: list[ReviewCandidate] = field(default_factory=list)
    blocking_warnings: list[str] = field(default_factory=list)


def _is_doi_conflict(result: PairScore, review_threshold: float) -> bool:
    """§3.3: a DOI-vetoed pair scoring high on everything else is `doi-conflict`, not discarded."""
    return result.doi_veto and result.non_doi_score >= review_threshold


def _with_canonical_flag(record: dict[str, Any], canonical: bool) -> dict[str, Any]:
    return {**record, "strata": {**record["strata"], "canonical": canonical}}


def _merge_record(
    canonical: dict[str, Any],
    absorbed: dict[str, Any],
    *,
    source_trust: list[str],
) -> dict[str, Any]:
    """Pure: field-wise merge of `absorbed` into `canonical` (no I/O).

    Returns the new canonical record. The caller is responsible for the
    `dedup-merge` event, the `aliases.ndjson` entry, updating `absorbed`'s
    own `strata.canonical` flag, and writing both back to `records.ndjson`.
    Split out from event/alias I/O (previously one `_apply_merge` did both)
    so `run_dedup`'s per-pair loop can batch the I/O across every merge in
    one run instead of one `append_new_event`/`append_alias` call per merge
    -- each of which re-reads its whole file, making an O(n)-merge run
    O(n^2) in the number of merges. See `append_new_events`'s docstring.
    """
    fields, provenance = merge_fields(canonical, absorbed, source_trust)
    canonical_strata = canonical.get("strata", {})
    absorbed_strata = absorbed.get("strata", {})
    merged_sources = list(canonical_strata.get("sources", [])) + list(
        absorbed_strata.get("sources", [])
    )
    merged_absorbed_ids = [
        *canonical_strata.get("absorbed", []),
        absorbed["id"],
        *absorbed_strata.get("absorbed", []),
    ]
    canonical_flags = set(canonical_strata.get("flags", []))
    absorbed_flags = set(absorbed_strata.get("flags", []))
    merged_flags = sorted(canonical_flags | absorbed_flags)

    return {
        **fields,
        "id": canonical["id"],
        "strata": {
            "canonical_key": canonical_strata["canonical_key"],
            "canonical": True,
            "absorbed": merged_absorbed_ids,
            "sources": merged_sources,
            "field_provenance": provenance,
            **({"flags": merged_flags} if merged_flags else {}),
        },
    }


def _merge_event_body(
    canonical_id: str, absorbed_id: str, *, result: PairScore, method: str
) -> dict[str, Any]:
    return {
        "canonical": canonical_id,
        "absorbed": absorbed_id,
        "score": result.score if not result.doi_veto else 1.0,
        "method": method,
        "features": result.features,
    }


def run_dedup(repo: Repo, *, actor: str, strict: bool = False) -> DedupOutcome:
    """The automatic pass: auto-merge obvious duplicates, queue the rest for `--review`.

    Writes `records/records.ndjson`, appends `dedup-merge`/alias entries for
    every auto-merge, and returns the pairs that clear `review_threshold`
    (or are a `doi-conflict`) for the caller to run through
    `apply_review_decision`. Never emits an event for a pair that scores
    below `review_threshold` -- absence is the default (§3.4).

    Every auto-merge's event and alias entry is batched and written once
    after the loop (`append_new_events`, one `write_aliases`), not one at a
    time per merge -- seeing an event, alias, or `records.ndjson` write mid-run
    is never possible for another process anyway, so there's nothing this
    trades away, and it turns an O(n)-merge run from O(n^2) into O(n) in the
    number of merges.
    """
    auto_threshold, review_threshold = thresholds(repo, strict=strict)
    trust = source_trust_order(repo)

    all_records = records_mod.read_records(repo)
    by_id: dict[str, dict[str, Any]] = {
        r["id"]: r for r in all_records if r.get("strata", {}).get("canonical", True)
    }
    absorbed_records = [r for r in all_records if not r.get("strata", {}).get("canonical", True)]

    blocking_result = find_candidate_pairs(by_id)
    judged = judged_pairs(repo)
    events_path = repo.path("events", "dedup", f"{actor}.ndjson")

    auto_merged: list[tuple[str, str]] = []
    review_queue: list[ReviewCandidate] = []
    pending_events: list[tuple[str, str, dict[str, Any]]] = []

    for a_id, b_id in sorted(blocking_result.pairs):
        pair_key = _pair_key(a_id, b_id)
        if pair_key in judged:
            continue
        record_a, record_b = by_id.get(a_id), by_id.get(b_id)
        if record_a is None or record_b is None:
            continue  # one side was already absorbed earlier in this same run

        result = score_pair(record_a, record_b)
        doi_conflict = _is_doi_conflict(result, review_threshold)

        if result.score >= auto_threshold and not doi_conflict:
            canonical, absorbed = choose_canonical(record_a, record_b, trust)
            merged = _merge_record(canonical, absorbed, source_trust=trust)
            pending_events.append(
                (
                    "dedup-merge",
                    actor,
                    _merge_event_body(
                        canonical["id"], absorbed["id"], result=result, method="auto-threshold"
                    ),
                )
            )
            del by_id[absorbed["id"]]
            by_id[canonical["id"]] = merged
            absorbed_records.append(_with_canonical_flag(absorbed, canonical=False))
            auto_merged.append((canonical["id"], absorbed["id"]))
            judged.add(pair_key)
        elif result.score >= review_threshold or doi_conflict:
            candidate = ReviewCandidate(
                record_a=a_id, record_b=b_id, result=result, doi_conflict=doi_conflict
            )
            review_queue.append(candidate)

    records_mod.write_records(repo, [*by_id.values(), *absorbed_records])

    if pending_events:
        envelopes = append_new_events(events_path, pending_events)
        alias_entries = aliases_mod.read_aliases(repo)
        for envelope, (canonical_id, absorbed_id) in zip(envelopes, auto_merged, strict=True):
            alias_entries.append(
                {
                    "alias": absorbed_id,
                    "canonical": canonical_id,
                    "reason": "dedup",
                    "event": str(envelope["id"]),
                }
            )
        aliases_mod.write_aliases(repo, alias_entries)

    return DedupOutcome(
        candidate_pairs_considered=len(blocking_result.pairs),
        auto_merged=auto_merged,
        review_queue=review_queue,
        blocking_warnings=blocking_result.warnings,
    )


def apply_review_decision(
    repo: Repo,
    *,
    record_a_id: str,
    record_b_id: str,
    result: PairScore,
    decision: Decision,
    actor: str,
) -> None:
    """Apply one human decision from the review queue: `merge` or `distinct` (§3.6).

    `[k]eep both` records a `dedup-distinct` event so the pair is never
    raised again (sticky, §3.1); it changes nothing else.
    """
    trust = source_trust_order(repo)
    events_path = repo.path("events", "dedup", f"{actor}.ndjson")

    if decision == "distinct":
        append_new_event(
            events_path,
            ev="dedup-distinct",
            actor=actor,
            body={
                "a": record_a_id,
                "b": record_b_id,
                "score": result.score,
                "method": "manual-review",
            },
        )
        return

    all_records = records_mod.read_records(repo)
    by_id = {r["id"]: r for r in all_records}
    record_a, record_b = by_id[record_a_id], by_id[record_b_id]
    canonical, absorbed = choose_canonical(record_a, record_b, trust)
    merged = _merge_record(canonical, absorbed, source_trust=trust)
    envelope = append_new_event(
        events_path,
        ev="dedup-merge",
        actor=actor,
        body=_merge_event_body(
            canonical["id"], absorbed["id"], result=result, method="manual-review"
        ),
    )
    aliases_mod.append_alias(
        repo,
        alias=absorbed["id"],
        canonical=canonical["id"],
        reason="dedup",
        event=str(envelope["id"]),
    )
    by_id[canonical["id"]] = merged
    by_id[absorbed["id"]] = _with_canonical_flag(absorbed, canonical=False)
    records_mod.write_records(repo, list(by_id.values()))


def undo_merge(repo: Repo, *, canonical_id: str, absorbed_id: str, actor: str) -> None:
    """Reverse one merge (`strata dedup --undo`).

    Restores `absorbed`'s `strata.canonical` flag and drops its alias entry.
    It does **not** revert field-level changes the merge made to the
    canonical record (e.g. an overwritten title): the `dedup-merge` event
    body (`canonical`, `absorbed`, `score`, `method`, `features`) never
    recorded the canonical's pre-merge field values, so there is nothing to
    restore them from. `strata why` can show what the merge changed; this
    undoes membership, not content.
    """
    all_records = records_mod.read_records(repo)
    by_id = {r["id"]: r for r in all_records}
    by_id[absorbed_id] = _with_canonical_flag(by_id[absorbed_id], canonical=True)
    records_mod.write_records(repo, list(by_id.values()))

    aliases_mod.remove_alias(repo, absorbed_id)

    events_path = repo.path("events", "dedup", f"{actor}.ndjson")
    append_new_event(
        events_path,
        ev="dedup-unmerge",
        actor=actor,
        body={"canonical": canonical_id, "restored": absorbed_id},
    )
