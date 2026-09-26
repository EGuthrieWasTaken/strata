"""Run the labelled dedup benchmark and (re)write docs/dedup-benchmark-results.md.

Implements the "published in the repository" half of
openspec:deduplication#validation-against-a-labelled-benchmark. The fixture itself
(`tests/fixtures/dedup-benchmark/`) is checked in and hand-labelled (see its
README for provenance and `scripts/generate_dedup_benchmark_fixture.py` for
how it was built); this script loads it, runs `strata.dedup.engine.run_dedup`
against a throwaway repo at the default (non-strict) thresholds, scores the
result with `strata.dedup.benchmark.compute_metrics`, and writes the report.

`tests/integration/test_dedup_benchmark.py` calls `run_benchmark()` directly
and asserts the v1 acceptance targets, so CI enforces the same numbers this
script publishes -- the two are never allowed to drift apart.

Usage: uv run python scripts/dedup_benchmark.py
"""

from __future__ import annotations

import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from strata.core.init import init_repository
from strata.core.records import read_records, write_records
from strata.core.repo import open_repo
from strata.dedup.benchmark import BenchmarkMetrics, compute_metrics, final_cluster_ids
from strata.dedup.engine import run_dedup

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "dedup-benchmark"
REPORT_PATH = Path(__file__).resolve().parent.parent / "docs" / "dedup-benchmark-results.md"

# v1 acceptance target, openspec:deduplication#validation-against-a-labelled-benchmark.
TARGET_RECALL = 0.95
TARGET_FALSE_MERGE_RATE = 0.001


def load_fixture() -> tuple[list[dict[str, Any]], set[tuple[str, str]], set[tuple[str, str]]]:
    """Records, ground-truth duplicate pairs, and the labelled confusable (hard-negative) pairs."""
    records_path = FIXTURE_DIR / "records.ndjson"
    records = [
        json.loads(line)
        for line in records_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    labels = json.loads((FIXTURE_DIR / "labels.json").read_text(encoding="utf-8"))
    duplicate_pairs = {(a, b) for a, b in labels["duplicate_pairs"]}
    confusable_pairs = {(a, b) for a, b in labels["confusable_pairs"]}
    return records, duplicate_pairs, confusable_pairs


def run_benchmark(repo_root: Path) -> tuple[BenchmarkMetrics, int, int, int]:
    """Run the fixture through `run_dedup` at default thresholds.

    Returns `(metrics, candidate_pairs_considered, review_queue_size,
    confusable_pairs_reviewed)`. `confusable_pairs_reviewed` is how many of
    the fixture's labelled hard-negative pairs were routed to human review
    rather than falling straight to "distinct" -- useful context, not a
    pass/fail signal (falling to "distinct" is equally correct; both avoid a
    false merge). `repo_root` must not already exist; the caller owns
    cleaning it up (tests pass a `tmp_path` subdirectory, this module's
    `main()` uses a `TemporaryDirectory`).
    """
    records, duplicate_pairs, confusable_pairs = load_fixture()
    init_repository(
        repo_root, title="Dedup Benchmark", actor_handle="benchmark", actor_name="Benchmark"
    )
    repo = open_repo(repo_root)
    write_records(repo, records)

    outcome = run_dedup(repo, actor="benchmark")

    final_records = read_records(repo)
    metrics = compute_metrics(
        duplicate_pairs=duplicate_pairs,
        auto_merged_pairs=set(outcome.auto_merged),
        final_cluster_of=final_cluster_ids(final_records),
    )
    reviewed_pairs = {_pair_key(c.record_a, c.record_b) for c in outcome.review_queue}
    confusable_reviewed = sum(1 for pair in confusable_pairs if _pair_key(*pair) in reviewed_pairs)
    return (
        metrics,
        outcome.candidate_pairs_considered,
        len(outcome.review_queue),
        confusable_reviewed,
    )


def _pair_key(a: str, b: str) -> tuple[str, str]:
    return (a, b) if a < b else (b, a)


def render_report(
    metrics: BenchmarkMetrics,
    candidate_pairs_considered: int,
    review_queue_size: int,
    confusable_pairs_reviewed: int,
) -> str:
    generated = datetime.now(UTC).strftime("%Y-%m-%d")
    verdict = "PASS" if _meets_targets(metrics) else "FAIL"
    return f"""\
# Dedup benchmark results

Generated {generated} by `scripts/dedup_benchmark.py` against the fixture in
`tests/fixtures/dedup-benchmark/` (55 hand-labelled, synthesised records --
**not** a real ASySD or `revtools` export; see that directory's `README.md`
for why and how it was built). Enforced by
`tests/integration/test_dedup_benchmark.py` on every CI run, so these numbers
cannot drift from what the test suite actually checks.

Evaluated at default (non-strict) thresholds: `auto_merge_threshold=0.95`,
`review_threshold=0.80`, per openspec:deduplication#thresholds-and-actions.

| Metric | Value | v1 target (openspec:deduplication#validation-against-a-labelled-benchmark) |
|---|---|---|
| Recall | {metrics.recall:.3f} | >= {TARGET_RECALL} |
| False-merge rate | {metrics.false_merge_rate:.4f} | <= {TARGET_FALSE_MERGE_RATE} |
| Precision | {metrics.precision:.3f} | (not targeted) |
| F1 | {metrics.f1:.3f} | (not targeted) |

**{verdict}** against the v1 acceptance bar.

Detail:
- {metrics.total_duplicate_pairs} ground-truth duplicate pairs (same-work
  clusters of 2-3 records each); {metrics.resolved_duplicate_pairs} ended up
  in the same final cluster after `strata dedup` (directly auto-merged, or
  transitively via a chain of two auto-merges).
- {metrics.true_positive_events} correct auto-merge actions,
  {metrics.false_positive_events} incorrect ones (false merges).
- {candidate_pairs_considered} candidate pairs proposed by blocking in
  total, of which {review_queue_size} were queued for human review rather
  than auto-merged or silently discarded -- among them
  {confusable_pairs_reviewed} of the fixture's labelled "confusable"
  hard-negative pairs (deliberately adversarial true negatives, e.g. an
  erratum vs. its original, or a two-part study); the rest of the confusable
  pairs scored low enough to fall to plain "distinct" with no event at all.
  Either outcome is correct -- both avoid a false merge. See the fixture's
  `README.md` for what each hard-negative pair is testing.

Recall and the false-merge rate are the two numbers
openspec:deduplication#validation-against-a-labelled-benchmark requires; precision
and F1 are reported for context, not gated on. Recall is computed against
each ground-truth pair's *final canonical id* after dedup, not against the
literal `dedup-merge` event log, so a three-record chain (A absorbs B, then
A absorbs C) correctly credits the untouched pair (B, C) as resolved --
see `strata.dedup.benchmark`'s module docstring for why that distinction
matters.

This is a small (55-record), hand-curated benchmark, not a large real-world
corpus: it demonstrates the scoring/blocking/threshold logic is *correct* on
a set of realistic cross-database formatting variations and a handful of
deliberately hard true negatives (an erratum, a two-part study, same-author
same-issue distinct papers), not that recall/false-merge-rate will hold at
this level on an arbitrary real dataset. Performance at 50,000 records is
checked separately (`tests/benchmark/`, advisory CI tier, not this file).
"""


def _meets_targets(metrics: BenchmarkMetrics) -> bool:
    return metrics.recall >= TARGET_RECALL and metrics.false_merge_rate <= TARGET_FALSE_MERGE_RATE


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        metrics, candidate_pairs_considered, review_queue_size, confusable_reviewed = run_benchmark(
            Path(tmp) / "repo"
        )

    report = render_report(
        metrics, candidate_pairs_considered, review_queue_size, confusable_reviewed
    )
    REPORT_PATH.write_text(report, encoding="utf-8")
    print(report)
    if not _meets_targets(metrics):
        raise SystemExit(f"dedup benchmark did not meet v1 targets: {metrics}")


if __name__ == "__main__":
    main()
