"""E2E-01: the origin scenario, docs/spec/06-workflow-screening.md §9.

The specification's own acceptance criterion, executed end to end against a
real git repository: init, criteria, two searches, two imports (with a
genuine duplicate pair so dedup does real work), dual screening, adding an
exclusion criterion mid-review, asserting the *exact* stale set it
produces, and re-screening it away.

**Why this test's numbers are not "180 of 2,918."** §9's narrative describes
adding one exclusion criterion and only 180 of 2,918 *already-included*
decisions going stale. Read literally against §4.2's normative rule --
`D.decision == "include" and there exists a change in Delta with direction
in {tightened, both}`, where `Delta` is *every* criterion change applying
at that stage since the decision was made -- adding one new criterion
applying at title-abstract makes `Delta` non-empty for *every* decision
made before that addition, regardless of what the record is about. The
rule has no per-record content test; it can only distinguish decisions by
*when* they were made relative to the change. §9 is explicitly informative,
§4.2 is explicitly normative, and docs/m2-plan.md sub-objective 1 already
established the precedent of following the normative text where the two
conflict (there, over version numbering). This test does the same: it
screens one batch of records *before* adding the new criterion and asserts
*all of that batch* goes stale (matching the implemented, brute-force-
verified engine from sub-objective 2), which is the scenario's real point
-- a protocol amendment invalidates exactly the inclusions decided under
the old rules, no more, no less -- without reproducing narrative numbers
the normative rule was never going to produce for an arbitrary corpus.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from strata import gitio
from strata.cli.main import EXIT_OK, app
from strata.core.records import read_records
from strata.core.repo import open_repo
from strata.core.verify import verify_repository
from strata.protocol.rescreen import compute_stale_records

runner = CliRunner()

_MEDLINE_RECORDS = [
    {
        "id": f"m{i}",
        "type": "article-journal",
        "title": f"Spacing effects in learning experiment {i}",
        "author": [{"family": "Cepeda", "given": "Nicholas"}],
        "issued": {"date-parts": [[2008 + i % 5]]},
        "container-title": "Psychological Science",
        "DOI": f"10.1111/medline.{i}",
        "abstract": "We investigated distributed practice effects on retention in adults.",
    }
    for i in range(1, 11)
]
# The MEDLINE and Embase exports share one record with an identical DOI
# ("medline.1"/e1) -- identity by DOI (docs/spec/01-domain-model.md §3.1)
# means these collapse into one canonical record during *import* itself
# (the second import appends a `sources` entry rather than duplicating the
# record), before `strata dedup`'s own fuzzy blocking/scoring ever runs.
# `strata dedup`'s near-duplicate matching is already extensively covered
# by M1's own test suite (tests/unit/test_blocking.py,
# tests/unit/test_scoring.py, the dedup benchmark); this scenario only
# needs the record *count* to come out right (14 canonical, not 15), which
# an exact-DOI collision demonstrates just as validly and far more simply.
_EMBASE_RECORDS = [
    {
        "id": "e1",
        "type": "article-journal",
        "title": "Spacing effects in learning experiment 1",
        "author": [{"family": "Cepeda", "given": "Nicholas"}],
        "issued": {"date-parts": [[2008]]},
        "container-title": "Psychological Science",
        "DOI": "10.1111/medline.1",
        "abstract": "We investigated distributed practice effects on retention in adults.",
    },
    *[
        {
            "id": f"e{i}",
            "type": "article-journal",
            "title": f"Retrieval practice study {i}",
            "author": [{"family": "Roediger", "given": "Henry"}],
            "issued": {"date-parts": [[2009 + i % 4]]},
            "container-title": "Medical Education",
            "DOI": f"10.1111/embase.{i}",
            "abstract": "We examined retrieval practice and the testing effect in adult learners.",
        }
        for i in range(2, 6)
    ],
]


def _write_search_export(tmp_path: Path, name: str, records: list[dict]) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(records), encoding="utf-8")
    return path


def _run(args: list[str], input: str | None = None) -> object:  # noqa: A002
    result = runner.invoke(app, args, input=input)
    assert result.exit_code == EXIT_OK, result.output
    return result


@pytest.mark.req("E2E-01")
def test_origin_scenario_exact_stale_set_and_rescreen(tmp_path: Path) -> None:
    root = tmp_path / "review"

    # Day 1: set up, record the protocol, search, import, dedup, screen.
    _run(
        [
            "init",
            str(root),
            "--title",
            "Spaced retrieval and long-term retention",
            "--actor",
            "ethan",
            "--actor-name",
            "Ethan",
        ]
    )
    _run(
        [
            "--why",
            "Sam is joining the review team as a second screener.",
            "-C",
            str(root),
            "actor",
            "add",
            "sam",
            "Sam",
            "--role",
            "screener",
        ]
    )

    for kind, label, definition, criterion_id in [
        ("inclusion", "Empirical study", "Reports original empirical data.", "INC-01"),
        ("exclusion", "Not in English", "Publications not written in English.", "EXC-01"),
    ]:
        _run(
            [
                "-C",
                str(root),
                "--why",
                "Establishing the initial protocol criteria for this review.",
                "criteria",
                "add",
                "--kind",
                kind,
                "--label",
                label,
                "--definition",
                definition,
                "--applies-at",
                "title-abstract,full-text",
                "--by",
                "ethan",
                "--id",
                criterion_id,
            ]
        )

    _run(
        [
            "-C",
            str(root),
            "--why",
            "Recording the MEDLINE search strategy per the protocol.",
            "search",
            "add",
            "--database",
            "MEDLINE",
            "--platform",
            "Ovid",
            "--by",
            "ethan",
            "--id",
            "S-01-medline",
            "--query",
            "1 exp Learning/\n2 (spac* adj3 practice).ti,ab,kf.\n3 1 and 2",
            "--hits",
            "10",
        ]
    )
    _run(
        [
            "-C",
            str(root),
            "--why",
            "Recording the Embase search strategy per the protocol.",
            "search",
            "add",
            "--database",
            "Embase",
            "--platform",
            "Ovid",
            "--by",
            "ethan",
            "--id",
            "S-02-embase",
            "--query",
            "1 exp Learning/\n2 (spac* adj3 practice).ti,ab,kf.\n3 1 and 2",
            "--hits",
            "5",
        ]
    )

    medline_file = _write_search_export(tmp_path, "medline.json", _MEDLINE_RECORDS)
    embase_file = _write_search_export(tmp_path, "embase.json", _EMBASE_RECORDS)
    _run(
        [
            "--why",
            "Importing the MEDLINE search results.",
            "-C",
            str(root),
            "import",
            str(medline_file),
            "--by",
            "ethan",
            "--search",
            "S-01-medline",
        ]
    )
    _run(
        [
            "--why",
            "Importing the Embase search results.",
            "-C",
            str(root),
            "import",
            str(embase_file),
            "--by",
            "ethan",
            "--search",
            "S-02-embase",
        ]
    )

    _run(
        [
            "--why",
            "Deduplicating the combined search results.",
            "-C",
            str(root),
            "dedup",
            "--by",
            "ethan",
        ]
    )

    repo = open_repo(root)
    all_records = read_records(repo)
    canonical_ids = sorted(r["id"] for r in all_records if r["strata"]["canonical"])
    # 10 MEDLINE + 5 Embase - 1 exact-DOI duplicate = 14 canonical records.
    assert len(canonical_ids) == 14

    # Dual screening: both ethan and sam include every record at title-abstract.
    # One `strata screen` invocation walks its *entire* queue in one
    # interactive session, so the input string repeats "include, no note"
    # once per record rather than invoking the command once per record.
    screen_all_input = "i\n\n" * len(canonical_ids)
    for actor in ("ethan", "sam"):
        _run(
            [
                "--why",
                "Screening the imported batch for the review.",
                "-C",
                str(root),
                "screen",
                "title-abstract",
                "--by",
                actor,
            ],
            input=screen_all_input,
        )

    repo = open_repo(root)
    assert compute_stale_records(repo) == []

    # Day 15: the protocol amendment.
    add_criterion_result = _run(
        [
            "-C",
            str(root),
            "--why",
            "Pilot extraction showed several child samples; restricting to adults.",
            "criteria",
            "add",
            "--kind",
            "exclusion",
            "--label",
            "Mean sample age under 18",
            "--definition",
            "The reported mean age of the analysed sample is below 18 years.",
            "--applies-at",
            "title-abstract",
            "--by",
            "ethan",
            "--id",
            "EXC-07",
        ]
    )
    assert "added" in add_criterion_result.output

    repo = open_repo(root)
    stale = compute_stale_records(repo)
    stale_ids = {s.record_id for s in stale}
    # The rule has no per-record content test (see module docstring):
    # *every* currently-included title-abstract decision is now stale,
    # citing the newly added criterion, and nothing else is.
    assert stale_ids == set(canonical_ids)
    assert all(s.stage == "title-abstract" for s in stale)
    assert all(s.reason == "criterion-added" for s in stale)
    assert all(s.prior_decision == "include" for s in stale)

    derived_stale = (root / "derived" / "stale.tsv").read_text(encoding="utf-8")
    assert derived_stale.count("\n") == len(canonical_ids) + 1  # header + one row per record

    # Day 15: the fix -- re-screen every stale record. Half are kept as
    # still-valid inclusions; half are now excluded citing the new criterion.
    # `rescreen`'s queue order is deterministic (sorted by record id, docs/
    # spec/06 §6), the same for both reviewers, so feeding both the same
    # sequence of choices makes them agree at every record -- a real dual
    # re-screen, not a conflict-generating mismatch. EXC-07 is the 3rd
    # active criterion applying at title-abstract (added after INC-01,
    # EXC-01), so citing it is "3".
    stale_ids_sorted = sorted(stale_ids)
    assert stale_ids_sorted == sorted(canonical_ids)
    rescreen_input = "".join(
        "k\n" if i % 2 == 0 else "e\n3\n" for i in range(len(stale_ids_sorted))
    )
    for actor in ("ethan", "sam"):
        rescreen_result = _run(
            [
                "--why",
                "Re-screening records made stale by the new age criterion.",
                "-C",
                str(root),
                "rescreen",
                "--by",
                actor,
            ],
            input=rescreen_input,
        )
        assert f"{len(stale_ids_sorted)} decision" in rescreen_result.output

    repo = open_repo(root)
    assert compute_stale_records(repo) == []

    kept_count = sum(1 for i in range(len(stale_ids_sorted)) if i % 2 == 0)
    excluded_count = len(stale_ids_sorted) - kept_count
    final_records = read_records(repo)
    canonical_final = [r for r in final_records if r["strata"]["canonical"]]
    pool_tsv = (root / "derived" / "pool.tsv").read_text(encoding="utf-8")
    assert pool_tsv.count("\tinclude\t") == kept_count
    assert pool_tsv.count("\texclude\t") == excluded_count
    assert len(canonical_final) == len(canonical_ids)

    report = verify_repository(repo)
    assert report.ok, report.issues
    assert not gitio.is_dirty(root)
