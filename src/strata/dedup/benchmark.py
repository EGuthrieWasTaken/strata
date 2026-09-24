"""Labelled dedup benchmark metrics: docs/spec/05-workflow-import.md §3.8.

Pure metric computation only, deliberately separated from the I/O of loading
a fixture and running `dedup.engine.run_dedup` against a real repo -- both
`tests/integration/test_dedup_benchmark.py` (the CI gate) and
`scripts/dedup_benchmark.py` (the tool that regenerates the published report)
do that part, and share this module so the metric *definitions* live in
exactly one place.

Two different notions of "did dedup get it right" are needed:

- Precision and the false-merge rate are about *actions*: of the pairs the
  engine actually auto-merged (`dedup-merge` events), how many were correct?
  This is well-defined per merge action and unaffected by chains.
- Recall is about *ground truth*: of the pairs a human labelled as the same
  work, how many ended up in the same final cluster? This must NOT be
  computed by checking for a direct auto-merge event between that exact
  pair: a three-record cluster (A, B, C) only ever produces two merge
  events (say A absorbs B, then A absorbs C) -- the third pairwise
  combination (B, C) has no direct event of its own even though B and C are
  correctly, transitively resolved into the same canonical record. Recall
  is therefore computed against each pair's *final canonical id* after
  dedup, not against the literal event log.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


def _pair_key(a: str, b: str) -> tuple[str, str]:
    return (a, b) if a < b else (b, a)


@dataclass(frozen=True)
class BenchmarkMetrics:
    """One benchmark run's results, per docs/spec/05-workflow-import.md §3.8.

    `precision`/`false_merge_rate` are computed over auto-merge *actions*;
    `recall` is computed over ground-truth pairs against the final
    clustering. See the module docstring for why these use different
    populations. `f1` blends `precision` and `recall` with the standard
    harmonic-mean formula regardless, as the single headline number a
    benchmark report leads with.
    """

    total_duplicate_pairs: int
    resolved_duplicate_pairs: int
    true_positive_events: int
    false_positive_events: int
    precision: float
    recall: float
    f1: float
    false_merge_rate: float


def final_cluster_ids(records: list[dict[str, Any]]) -> dict[str, str]:
    """Map every record id to the id of its final canonical record.

    A canonical record maps to itself; every id in its `strata.absorbed`
    list (populated transitively by `dedup.engine._apply_merge`, so it
    already reflects chains) maps to that canonical id too. A record id not
    present in the result was never touched by dedup -- it is its own
    (singleton) cluster.
    """
    mapping: dict[str, str] = {}
    for record in records:
        strata = record.get("strata", {})
        if not strata.get("canonical", True):
            continue
        mapping[record["id"]] = record["id"]
        for absorbed_id in strata.get("absorbed", []):
            mapping[absorbed_id] = record["id"]
    return mapping


def compute_metrics(
    *,
    duplicate_pairs: set[tuple[str, str]],
    auto_merged_pairs: set[tuple[str, str]],
    final_cluster_of: dict[str, str],
) -> BenchmarkMetrics:
    """Score one benchmark run against its ground truth.

    `duplicate_pairs`: every (a, b) a human labelled as the same work.
    `auto_merged_pairs`: the literal `(canonical, absorbed)` pairs from
    `DedupOutcome.auto_merged` -- the engine's actual merge actions.
    `final_cluster_of`: `final_cluster_ids()` of `records.ndjson` after the
    run. A pair or id absent from `final_cluster_of` is its own singleton.
    """
    duplicate_pairs = {_pair_key(a, b) for a, b in duplicate_pairs}
    auto_merged_pairs = {_pair_key(a, b) for a, b in auto_merged_pairs}

    true_positive_events = auto_merged_pairs & duplicate_pairs
    false_positive_events = auto_merged_pairs - duplicate_pairs
    resolved = {
        (a, b)
        for a, b in duplicate_pairs
        if final_cluster_of.get(a, a) == final_cluster_of.get(b, b)
    }

    tp_events, fp_events = len(true_positive_events), len(false_positive_events)
    total = len(duplicate_pairs)
    recall = len(resolved) / total if total else 1.0
    precision = tp_events / (tp_events + fp_events) if (tp_events + fp_events) else 1.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    false_merge_rate = fp_events / (tp_events + fp_events) if (tp_events + fp_events) else 0.0

    return BenchmarkMetrics(
        total_duplicate_pairs=total,
        resolved_duplicate_pairs=len(resolved),
        true_positive_events=tp_events,
        false_positive_events=fp_events,
        precision=precision,
        recall=recall,
        f1=f1,
        false_merge_rate=false_merge_rate,
    )
