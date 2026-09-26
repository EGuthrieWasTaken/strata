"""The labelled dedup benchmark's CI gate:
openspec:deduplication#validation-against-a-labelled-benchmark.

Runs `scripts/dedup_benchmark.py`'s `run_benchmark()` against the checked-in
fixture (`tests/fixtures/dedup-benchmark/`) and asserts the v1 acceptance
bar. `scripts/dedup_benchmark.py` also writes `docs/dedup-benchmark-results.md`
from the exact same function, so this test and that published report can
never silently disagree with each other.
"""

from __future__ import annotations

from pathlib import Path

from scripts.dedup_benchmark import (
    TARGET_FALSE_MERGE_RATE,
    TARGET_RECALL,
    load_fixture,
    run_benchmark,
)


def test_dedup_benchmark_meets_v1_acceptance_targets(tmp_path: Path) -> None:
    metrics, candidate_pairs_considered, review_queue_size, confusable_reviewed = run_benchmark(
        tmp_path / "repo"
    )

    assert metrics.recall >= TARGET_RECALL, metrics
    assert metrics.false_merge_rate <= TARGET_FALSE_MERGE_RATE, metrics

    # Sanity checks on the fixture/harness itself, so a future edit that
    # accidentally hollows out the benchmark (e.g. blocking finding zero
    # candidates) fails loudly here rather than passing the targets above
    # vacuously.
    assert metrics.total_duplicate_pairs > 0
    assert candidate_pairs_considered >= metrics.total_duplicate_pairs
    assert review_queue_size > 0  # the confusable hard negatives exercise this
    assert confusable_reviewed > 0


def test_dedup_benchmark_fixture_has_labelled_hard_negatives() -> None:
    _records, duplicate_pairs, confusable_pairs = load_fixture()
    assert len(duplicate_pairs) > 0
    assert len(confusable_pairs) > 0
    assert duplicate_pairs.isdisjoint(confusable_pairs)
