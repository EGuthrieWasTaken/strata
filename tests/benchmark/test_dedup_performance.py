"""Performance validation: openspec:deduplication#performance (normative).

openspec:deduplication#performance requires deduplicating 50,000 records to complete in under 120
seconds,
single-threaded, on a 2020-era laptop, using under 2 GB of resident memory.
This lives in the advisory `benchmark` CI tier (`.github/workflows/ci.yml`'s
`benchmark` job, `continue-on-error: true`), not the blocking merge gate --
docs/m1-plan.md sub-objective 6 calls out that wall-clock/RSS assertions are
too noisy across CI runners to gate a PR on, but the run itself is real: a
genuine 50,000-record repository, not a toy, generated deterministically so
a slowdown is reproducible.

Title generation deliberately builds each title from random pseudo-words
(random lowercase letter strings), not real English vocabulary. Two earlier
approaches both caused a self-inflicted O(n^2) blowup in the *fixture*, not a
real `title-lsh` defect, by giving unrelated records' titles too much
incidental 3-gram overlap: a handful of fixed adjective/topic/method
templates (thousands of records sharing most of their title text, differing
only in a trailing serial number); and titles composed from a few hundred
real English words repeated across the corpus (real words share enough
common substrings/morphology -- "-tion", "-ing", "-ment" -- that random
7-word titles drawn from a small shared vocabulary still landed well above
the title-LSH band's ~0.8 Jaccard sensitivity far more often than chance
should allow). Random letter sequences have a near-uniform, much larger
3-gram universe, so unrelated titles land nowhere near that threshold.

Run directly with `uv run pytest tests/benchmark -q --benchmark-json=out.json`
(the CI benchmark job does exactly this); `pytest-benchmark`'s own repeat/
calibration loop is disabled (`rounds=1, iterations=1`) since re-running a
50,000-record dedup pass several times to calibrate would itself blow past
the time budget this test is trying to check.

Known gap, tracked in docs/m1-plan.md sub-objective 8: measured at **126.0s**
in the sandboxed environment this was developed in -- just over openspec:deduplication#performance's
strict
120s, though comfortably inside the M1 acceptance bar's looser 300s
(docs/roadmap.md). This used to be far worse (>240s, and climbing):
sub-objective 8 found and fixed an O(n^2) event/alias-append bug that was the
dominant cost for the ~5,000 merges this fixture produces (see
`strata.core.events.append_new_events`'s docstring). What remains is
blocking's per-record MinHash computation alone, which takes roughly 77s at
50,000 records -- a separate, smaller-magnitude cost left as a known
follow-up rather than fixed here by touching sub-objective 5's already-tested
`blocking.py` under time pressure. That may or may not also be true on the
spec's "2020-era laptop" target; either way, that's exactly why this lives in
the advisory tier rather than the blocking merge gate.
"""

from __future__ import annotations

import random
import resource
import string
from pathlib import Path
from typing import Any

import pytest

from strata.core.init import init_repository
from strata.core.records import write_records
from strata.core.repo import open_repo
from strata.dedup.engine import run_dedup

_SEED = 20260101
_TOTAL_RECORDS = 50_000
_DUPLICATE_WORKS = 5_000  # each contributes a near-duplicate pair -> 10,000 records
_TIME_LIMIT_SECONDS = 120  # openspec:deduplication#performance
_RSS_LIMIT_KB = 2 * 1024 * 1024  # 2 GB; Linux's ru_maxrss is already in KB

_JOURNALS = [
    "Journal of Clinical Medicine",
    "PLOS ONE",
    "The Lancet",
    "Nature Communications",
    "BMJ Open",
    "Psychological Science",
    "Scientific Reports",
    "Frontiers in Psychology",
]
_FAMILIES = [
    "Smith",
    "Johnson",
    "Patel",
    "Garcia",
    "Kim",
    "Muller",
    "Nguyen",
    "Rossi",
    "Andersson",
    "Dubois",
    "Kowalski",
    "Silva",
    "Yamamoto",
    "Ivanov",
    "Okafor",
]


def _random_word(rng: random.Random) -> str:
    return "".join(rng.choices(string.ascii_lowercase, k=rng.randint(4, 10)))


def _make_title(rng: random.Random) -> str:
    words = [_random_word(rng) for _ in range(8)]
    return " ".join(words).capitalize()


def _make_work(rng: random.Random) -> dict[str, Any]:
    authors = [{"family": rng.choice(_FAMILIES)} for _ in range(rng.randint(1, 5))]
    year = rng.randint(1995, 2025)
    return {
        "title": _make_title(rng),
        "author": authors,
        "issued": {"date-parts": [[year]]},
        "container-title": rng.choice(_JOURNALS),
        "volume": str(rng.randint(1, 60)),
        "page": str(rng.randint(1, 999)),
    }


def _generate_records(rng: random.Random) -> list[dict[str, Any]]:
    """`_TOTAL_RECORDS` records: `_DUPLICATE_WORKS` near-duplicate pairs plus singletons."""
    records: list[dict[str, Any]] = []
    counter = 0

    def _next_id() -> str:
        nonlocal counter
        counter += 1
        return f"rec_pf{counter:014d}"

    def _append(fields: dict[str, Any]) -> None:
        record_id = _next_id()
        records.append(
            {
                "id": record_id,
                "type": "article-journal",
                **fields,
                "strata": {
                    "canonical_key": f"sig:{record_id}",
                    "canonical": True,
                    "sources": [{"import": "imp_01arz3ndektsv4rrffq69g5fav", "database": "manual"}],
                },
            }
        )

    for _ in range(_DUPLICATE_WORKS):
        work = _make_work(rng)
        _append(dict(work))
        variant = dict(work)
        variant["container-title"] = work["container-title"].upper()
        _append(variant)

    for _ in range(_TOTAL_RECORDS - len(records)):
        _append(_make_work(rng))

    return records


@pytest.mark.benchmark_50k
def test_dedup_50k_records_under_time_and_memory_budget(tmp_path: Path, benchmark: Any) -> None:
    rng = random.Random(_SEED)
    records = _generate_records(rng)
    assert len(records) == _TOTAL_RECORDS

    root = tmp_path / "repo"
    init_repository(root, title="Perf", actor_handle="bench", actor_name="Bench")
    repo = open_repo(root)
    write_records(repo, records)

    # `rounds=1, iterations=1`: this is a single real 50,000-record dedup
    # pass, not a micro-benchmark -- letting pytest-benchmark calibrate by
    # repeating it would itself blow past the time budget being checked.
    outcome = benchmark.pedantic(
        run_dedup, args=(repo,), kwargs={"actor": "bench"}, rounds=1, iterations=1
    )
    elapsed = benchmark.stats.stats.mean
    peak_rss_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss

    print(
        f"\ndedup of {_TOTAL_RECORDS} records: {elapsed:.1f}s, "
        f"{peak_rss_kb / 1024:.0f} MB peak RSS, "
        f"{outcome.candidate_pairs_considered} candidate pairs, "
        f"{len(outcome.auto_merged)} auto-merged, "
        f"{len(outcome.review_queue)} queued for review"
    )

    assert elapsed < _TIME_LIMIT_SECONDS, (
        f"{elapsed:.1f}s exceeds the {_TIME_LIMIT_SECONDS}s budget"
    )
    assert peak_rss_kb < _RSS_LIMIT_KB, f"{peak_rss_kb} KB exceeds the {_RSS_LIMIT_KB} KB budget"
    assert len(outcome.auto_merged) > 0  # the duplicate pairs must actually be found
