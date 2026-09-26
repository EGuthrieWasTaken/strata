"""Performance validation: a 50,000-record import (E2E-11, and the M1
acceptance bar in docs/roadmap.md: "50,000-record import under 60s").

Advisory CI tier (see tests/benchmark/test_dedup_performance.py's module
docstring for why: wall-clock assertions are too noisy across CI runners to
gate a PR on) but a real run against a genuine 50,000-record CSL-JSON export,
not a toy.
"""

from __future__ import annotations

import json
import random
import resource
import string
from pathlib import Path
from typing import Any

import pytest

from strata.core.init import init_repository
from strata.core.repo import open_repo
from strata.ingest.pipeline import import_file

_SEED = 20260101
_TOTAL_RECORDS = 50_000
_TIME_LIMIT_SECONDS = 60  # docs/roadmap.md's M1 acceptance bar
_RSS_LIMIT_KB = 2 * 1024 * 1024  # 2 GB, matching the dedup perf budget


def _random_word(rng: random.Random) -> str:
    return "".join(rng.choices(string.ascii_lowercase, k=rng.randint(4, 10)))


def _make_record(rng: random.Random, n: int) -> dict[str, Any]:
    title = " ".join(_random_word(rng) for _ in range(8)).capitalize()
    authors = [{"family": _random_word(rng).capitalize()} for _ in range(rng.randint(1, 4))]
    return {
        "title": f"{title} {n}",
        "author": authors,
        "issued": {"date-parts": [[rng.randint(1995, 2025)]]},
        "container-title": _random_word(rng).capitalize(),
        "volume": str(rng.randint(1, 60)),
        "page": str(rng.randint(1, 999)),
    }


def _write_export(path: Path) -> None:
    rng = random.Random(_SEED)
    records = [_make_record(rng, n) for n in range(_TOTAL_RECORDS)]
    path.write_text(json.dumps(records), encoding="utf-8")


@pytest.mark.req("E2E-11")
@pytest.mark.benchmark_50k
def test_import_50k_records_under_time_and_memory_budget(tmp_path: Path, benchmark: Any) -> None:
    export_path = tmp_path / "export.json"
    _write_export(export_path)

    root = tmp_path / "repo"
    init_repository(root, title="Import Perf", actor_handle="bench", actor_name="Bench")
    repo = open_repo(root)

    outcome = benchmark.pedantic(
        import_file,
        args=(repo, export_path),
        kwargs={"imported_by": "bench", "via": "registry"},
        rounds=1,
        iterations=1,
    )
    elapsed = benchmark.stats.stats.mean
    peak_rss_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss

    print(
        f"\nimport of {_TOTAL_RECORDS} records: {elapsed:.1f}s, "
        f"{peak_rss_kb / 1024:.0f} MB peak RSS, {outcome.records_created} created"
    )

    assert outcome.records_created == _TOTAL_RECORDS
    assert elapsed < _TIME_LIMIT_SECONDS, (
        f"{elapsed:.1f}s exceeds the {_TIME_LIMIT_SECONDS}s budget"
    )
    assert peak_rss_kb < _RSS_LIMIT_KB, f"{peak_rss_kb} KB exceeds the {_RSS_LIMIT_KB} KB budget"
