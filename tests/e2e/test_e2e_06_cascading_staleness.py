"""E2E-06: cascading staleness -- a title/abstract reversal orphans a
downstream full-text decision, without deleting it.

docs/spec/14-testing.md §5: "Cascading staleness: a title/abstract reversal
orphans a full-text decision and an extraction, without deleting the
extraction." Extraction does not exist until M3 (docs/m2-plan.md's own
precedent: M1 left EndNote/Excel import partial and documented it rather
than blocking on it), so this test's scope is the part of §4.4
(docs/spec/06-workflow-screening.md) M2 actually implements: the forward
cascade (a stale title-abstract `include` marks the dependent full-text
decision stale too, `protocol/rescreen.py`'s `upstream-stale` reason) and
the "never silently delete downstream work" guarantee, checked against the
full-text `screen` event itself (append-only event log) rather than an
extraction file that has nowhere to live yet.

One nuance worth being explicit about, discovered writing this test: the
cascade is a *pending-resolution* signal, not a permanent tombstone. While
title-abstract is stale (protocol changed, not yet re-decided), the
dependent full-text decision is flagged `upstream-stale` too -- that part
is asserted directly. Once the reviewer resolves it by reversing to
`exclude`, title-abstract's own opinion is fresh again (it was actively
re-decided) and so no longer stale, and `upstream-stale` stops applying
(nothing is pending for the reviewer to act on any more, and re-screening
an already-excluded record's full text would be pointless). What §4.4
actually promises for that state -- "never silently delete downstream
work" -- is that the full-text `include` opinion is *retained*: still
present in `events/screen/full-text.<actor>.ndjson`, still visible via
`derived/pool.tsv`'s `fulltext` column, even though `tiab` now governs the
record's overall disposition and shows it excluded. That retention (not a
lingering "stale" flag) is what this test asserts for the post-reversal
state.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from strata import gitio
from strata.cli.main import EXIT_OK, app
from strata.core.repo import open_repo
from strata.core.verify import verify_repository
from strata.protocol.rescreen import compute_stale_records
from strata.protocol.screening import all_screen_events

runner = CliRunner()

_RECORDS = """\
[
  {
    "id": "1",
    "type": "article-journal",
    "title": "A trial of spaced retrieval practice in adult learners",
    "author": [{"family": "Cepeda", "given": "Nicholas"}],
    "issued": {"date-parts": [[2008]]},
    "container-title": "Psychological Science",
    "DOI": "10.1111/e2e06.record",
    "abstract": "A study that progresses through both screening stages."
  }
]
"""


def _run(args: list[str], input: str | None = None) -> object:  # noqa: A002
    result = runner.invoke(app, args, input=input)
    assert result.exit_code == EXIT_OK, result.output
    return result


@pytest.mark.req("E2E-06")
def test_title_abstract_reversal_orphans_full_text_without_deleting_it(tmp_path: Path) -> None:
    root = tmp_path / "review"
    _run(
        [
            "init",
            str(root),
            "--title",
            "E2E-06 cascading staleness",
            "--actor",
            "ethan",
            "--actor-name",
            "Ethan",
        ]
    )
    _run(
        [
            "-C",
            str(root),
            "--why",
            "Establishing the initial protocol criteria for this review.",
            "criteria",
            "add",
            "--kind",
            "inclusion",
            "--label",
            "Empirical study",
            "--definition",
            "Reports original empirical data.",
            "--applies-at",
            "title-abstract",
            "--by",
            "ethan",
            "--id",
            "INC-01",
        ]
    )

    export = tmp_path / "records.json"
    export.write_text(_RECORDS, encoding="utf-8")
    _run(
        [
            "--why",
            "Importing the search results for this review.",
            "-C",
            str(root),
            "import",
            str(export),
            "--by",
            "ethan",
            "--via",
            "registry",
        ]
    )

    # The record clears both stages: included at title-abstract, then
    # included at full-text too.
    _run(
        [
            "--why",
            "Screening the pilot batch for the review.",
            "-C",
            str(root),
            "screen",
            "title-abstract",
            "--by",
            "ethan",
        ],
        input="i\n\n",
    )
    _run(
        [
            "--why",
            "Screening the full-text batch for the review.",
            "-C",
            str(root),
            "screen",
            "full-text",
            "--by",
            "ethan",
        ],
        input="i\n\n",
    )

    repo = open_repo(root)
    assert compute_stale_records(repo) == []
    (record_id,) = [s["body"]["record"] for s in all_screen_events(repo, "full-text")]

    # Day 15: a new title-abstract criterion tightens the pool.
    _run(
        [
            "-C",
            str(root),
            "--why",
            "Pilot extraction showed non-English reports slipping through; excluding them.",
            "criteria",
            "add",
            "--kind",
            "exclusion",
            "--label",
            "Not in English",
            "--definition",
            "Publications not written in English.",
            "--applies-at",
            "title-abstract",
            "--by",
            "ethan",
            "--id",
            "EXC-05",
        ]
    )

    repo = open_repo(root)
    stale = compute_stale_records(repo)
    stale_by_stage = {s.stage: s for s in stale}

    # The cascade (docs/spec/06 §4.4): the native title-abstract staleness
    # marks the dependent full-text decision stale too, *while it is still
    # pending*.
    assert set(stale_by_stage) == {"title-abstract", "full-text"}
    assert stale_by_stage["title-abstract"].reason == "criterion-added"
    assert stale_by_stage["full-text"].reason == "upstream-stale"
    assert stale_by_stage["full-text"].record_id == record_id

    # The reversal: on re-screening, the record no longer qualifies at
    # title-abstract at all.
    rescreen_result = _run(
        [
            "--why",
            "Re-screening the record made stale by the new language criterion.",
            "-C",
            str(root),
            "rescreen",
            "--stage",
            "title-abstract",
            "--by",
            "ethan",
        ],
        input="e\n1\n",
    )
    assert "1 decision" in rescreen_result.output

    repo = open_repo(root)
    # title-abstract's own opinion is fresh again (actively re-decided), so
    # nothing is pending any more -- see the module docstring for why this
    # is the correct state, not a lingering "upstream-stale" full-text row.
    assert compute_stale_records(repo) == []

    # "Never silently delete downstream work": the full-text `include`
    # opinion is still there, verbatim, in the append-only event log --
    # reversing title-abstract does not touch it.
    full_text_events = all_screen_events(repo, "full-text")
    assert len(full_text_events) == 1
    assert full_text_events[0]["body"]["record"] == record_id
    assert full_text_events[0]["body"]["decision"] == "include"

    # The pool reflects the record's overall disposition from
    # title-abstract (exclude governs), while still surfacing the retained
    # full-text opinion rather than erasing it.
    pool_tsv = (root / "derived" / "pool.tsv").read_text(encoding="utf-8")
    row = next(line for line in pool_tsv.splitlines() if line.startswith(record_id))
    columns = row.split("\t")
    assert columns[1] == "exclude"  # tiab
    assert columns[2] == "include"  # fulltext, retained

    report = verify_repository(repo)
    assert report.ok, report.issues
    assert not gitio.is_dirty(root)
