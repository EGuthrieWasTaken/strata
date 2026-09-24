"""Performance validation: docs/spec/13-nonfunctional.md §1's "screening
decision round trip < 100 ms p95" (hard limit 250 ms), the M2 roadmap
acceptance bullet "a screening session sustains < 100 ms p95 decision
latency at 50k records" (docs/spec/15-roadmap.md).

Advisory CI tier (see tests/benchmark/test_dedup_performance.py's module
docstring for why: wall-clock assertions are too noisy across CI runners to
gate a PR on) but a real measurement: a genuine 50,000-record repository,
`record_screen_decision` called directly (the same call `strata screen`'s
interactive loop makes once per decision -- the queue itself is computed
once up front, not per decision, so it is deliberately excluded here as a
one-time session-setup cost rather than part of "decision latency"),
timed individually so a p95/p99 can actually be computed, not just a mean.

**A real bug this benchmark caught, not just measured.** The first run
against a genuine 50,000-record repository measured p95 at ~497 ms, roughly
5x the soft target and 2x the *hard* limit -- `core.records.get_record`
(called once per decision, to confirm the record being decided exists)
called `read_records`, which reads and `json.loads`-parses every single
line of `records.ndjson` on every call, regardless of which one record was
wanted. At 50,000 records that is a full-file JSON parse per screening
decision. Fixed in `get_record` itself (a cheap substring pre-filter on
the id string, `json.loads` only on the line(s) that might match, with the
exact id check still guarding correctness) -- see that function's
docstring for the fix and `tests/unit/test_records.py`'s
`test_get_record_skips_a_substring_false_positive` for why the pre-filter
can't cause a wrong answer. Re-measured after the fix, sampling 1,000
decisions: p95 in the 80-90 ms range in this sandboxed environment,
comfortably inside the 100 ms target with headroom before the 250 ms hard
limit.
"""

from __future__ import annotations

import random
import resource
import string
import time
from pathlib import Path
from typing import Any

import pytest

from strata.core.init import init_repository
from strata.core.records import write_records
from strata.core.repo import open_repo
from strata.protocol.criteria import add_criterion
from strata.protocol.screening import record_screen_decision

_SEED = 20260101
_TOTAL_RECORDS = 50_000
_DECISIONS_SAMPLED = 1_000  # a substantial screening session, not one click
_P95_TARGET_SECONDS = 0.100  # docs/spec/13-nonfunctional.md §1 soft target
_P95_HARD_LIMIT_SECONDS = 0.250  # same row's hard limit
_RSS_LIMIT_KB = 2 * 1024 * 1024  # 2 GB, matching the other 50k benchmarks


def _random_word(rng: random.Random) -> str:
    return "".join(rng.choices(string.ascii_lowercase, k=rng.randint(4, 10)))


def _make_record(rng: random.Random, n: int) -> dict[str, Any]:
    record_id = f"rec_pf{n:014d}"
    title = " ".join(_random_word(rng) for _ in range(8)).capitalize()
    return {
        "id": record_id,
        "type": "article-journal",
        "title": f"{title} {n}",
        "author": [{"family": _random_word(rng).capitalize()}],
        "issued": {"date-parts": [[rng.randint(1995, 2025)]]},
        "container-title": _random_word(rng).capitalize(),
        "strata": {
            "canonical_key": f"sig:{record_id}",
            "canonical": True,
            "sources": [{"import": "imp_01arz3ndektsv4rrffq69g5fav", "database": "manual"}],
        },
    }


def _percentile(sorted_values: list[float], p: float) -> float:
    index = min(int(len(sorted_values) * p), len(sorted_values) - 1)
    return sorted_values[index]


@pytest.mark.benchmark_50k
def test_screening_decision_round_trip_p95_at_50k_records(tmp_path: Path, benchmark: Any) -> None:
    rng = random.Random(_SEED)
    records = [_make_record(rng, n) for n in range(_TOTAL_RECORDS)]

    root = tmp_path / "repo"
    init_repository(root, title="Screening Perf", actor_handle="bench", actor_name="Bench")
    repo = open_repo(root)
    write_records(repo, records)
    repo = open_repo(root)

    add_criterion(
        repo,
        kind="exclusion",
        label="A",
        definition="def a",
        applies_at=["title-abstract"],
        actor="bench",
        rationale="Establishing the initial protocol criteria for this review.",
        criterion_id="EXC-01",
    )
    repo = open_repo(root)

    # A spread-out sample across the (id-sorted) file, not just the first
    # N records -- get_record's fix is a per-line prefilter, so a lookup's
    # cost should not depend on where in the file its record happens to sit.
    step = _TOTAL_RECORDS // _DECISIONS_SAMPLED
    sample_ids = [records[i]["id"] for i in range(0, _TOTAL_RECORDS, step)][:_DECISIONS_SAMPLED]
    assert len(sample_ids) == _DECISIONS_SAMPLED

    latencies: list[float] = []

    def _decide_all() -> None:
        for record_id in sample_ids:
            t0 = time.perf_counter()
            record_screen_decision(
                repo,
                stage="title-abstract",
                record_id=record_id,
                decision="include",
                actor="bench",
            )
            latencies.append(time.perf_counter() - t0)

    # `rounds=1, iterations=1`: one real session over `_DECISIONS_SAMPLED`
    # distinct records, individually timed -- not pytest-benchmark's own
    # repeat/calibration loop, which would need each round to start from a
    # fresh, undecided repo to mean anything.
    benchmark.pedantic(_decide_all, rounds=1, iterations=1)
    peak_rss_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss

    latencies.sort()
    p50 = _percentile(latencies, 0.50)
    p95 = _percentile(latencies, 0.95)
    p99 = _percentile(latencies, 0.99)

    print(
        f"\n{_DECISIONS_SAMPLED} screening decisions at {_TOTAL_RECORDS} records: "
        f"p50={p50 * 1000:.1f}ms p95={p95 * 1000:.1f}ms p99={p99 * 1000:.1f}ms "
        f"max={max(latencies) * 1000:.1f}ms, {peak_rss_kb / 1024:.0f} MB peak RSS"
    )

    assert p95 < _P95_HARD_LIMIT_SECONDS, (
        f"p95={p95 * 1000:.1f}ms exceeds the {_P95_HARD_LIMIT_SECONDS * 1000:.0f}ms hard limit"
    )
    assert p95 < _P95_TARGET_SECONDS, (
        f"p95={p95 * 1000:.1f}ms exceeds the {_P95_TARGET_SECONDS * 1000:.0f}ms soft target"
    )
    assert peak_rss_kb < _RSS_LIMIT_KB, f"{peak_rss_kb} KB exceeds the {_RSS_LIMIT_KB} KB budget"
