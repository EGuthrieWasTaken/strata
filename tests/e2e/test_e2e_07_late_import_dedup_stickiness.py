"""E2E-07: dedup after a late fourth import doesn't re-raise earlier decisions.

openspec:test-suite#end-to-end-scenarios: "Deduplication after a late fourth import,
asserting that earlier manual dedup decisions are not re-raised." A scripted
run against a real git repository: import two near-duplicate records,
resolve that pair manually (`[k]eep both`, the sticky "not duplicates"
decision per
openspec:deduplication#sticky-reversible-conservative-explainable), import two more
unrelated records later, and confirm the first pair is never queued again
while the fourth import is still correctly considered fresh.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from strata import gitio
from strata.cli.main import EXIT_OK, app

runner = CliRunner()

# Word-reordered near-duplicates (same title token set, different order --
# see tests/integration/test_cli_dedup.py's fixtures for why this, not an
# exact title, is what makes these two genuinely separate records at import
# time): lands in the review band (score ~0.85), not auto-merge.
_PAIR_A = (
    '[{"title": "Learning and spacing effects in memory consolidation", '
    '"author": [{"family": "Cepeda"}, {"family": "Vul"}], '
    '"issued": {"date-parts": [[2008]]}}]'
)
_PAIR_B = (
    '[{"title": "Spacing and learning effects in memory consolidation", '
    '"author": [{"family": "Cepeda"}, {"family": "Vul"}], '
    '"issued": {"date-parts": [[2008]]}}]'
)
_UNRELATED_C = (
    '[{"title": "Risk of bias assessment tools for randomised trials", '
    '"author": [{"family": "Higgins"}], "issued": {"date-parts": [[2011]]}}]'
)
_UNRELATED_D = (
    '[{"title": "A survey of publication bias detection methods", '
    '"author": [{"family": "Sterne"}], "issued": {"date-parts": [[2005]]}}]'
)


def _import(root: Path, tmp_path: Path, name: str, content: str) -> None:
    export = tmp_path / name
    export.write_text(content, encoding="utf-8")
    result = runner.invoke(
        app,
        [
            "--why",
            f"importing {name} for the E2E-07 scenario",
            "-C",
            str(root),
            "import",
            str(export),
            "--by",
            "ethan",
            "--via",
            "registry",
        ],
    )
    assert result.exit_code == EXIT_OK, result.output


@pytest.mark.req("E2E-07")
def test_dedup_after_late_fourth_import_does_not_reraise_judged_pair(tmp_path: Path) -> None:
    root = tmp_path / "review"
    init_result = runner.invoke(
        app,
        ["init", str(root), "--title", "E2E-07", "--actor", "ethan", "--actor-name", "Ethan"],
    )
    assert init_result.exit_code == EXIT_OK, init_result.output

    # Imports 1 and 2: a genuine near-duplicate pair.
    _import(root, tmp_path, "a.json", _PAIR_A)
    _import(root, tmp_path, "b.json", _PAIR_B)

    review = runner.invoke(
        app,
        [
            "--why",
            "reviewing the near-duplicate pair and keeping both",
            "-C",
            str(root),
            "dedup",
            "--by",
            "ethan",
            "--review",
        ],
        input="k\n",
    )
    assert review.exit_code == EXIT_OK, review.output
    assert "kept both" in review.output
    assert not gitio.is_dirty(root)

    # Import 3 and the "late fourth import": two unrelated records, added
    # well after the first pair was already judged.
    _import(root, tmp_path, "c.json", _UNRELATED_C)
    _import(root, tmp_path, "d.json", _UNRELATED_D)

    rerun = runner.invoke(app, ["--json", "-C", str(root), "dedup", "--by", "ethan"])
    assert rerun.exit_code == EXIT_OK, rerun.output
    payload = json.loads(rerun.output)

    # The first pair must never reappear -- neither auto-merged nor queued.
    assert payload["auto_merged"] == []
    assert payload["review_queue"] == []

    records_path = root / "records" / "records.ndjson"
    lines = [line for line in records_path.read_text(encoding="utf-8").splitlines() if line]
    canonical_lines = [line for line in lines if '"canonical":true' in line]
    # All four records survive as their own canonical records: the first
    # pair because it was explicitly kept distinct, the second pair because
    # nothing about them is similar enough to be a candidate at all.
    assert len(canonical_lines) == 4
