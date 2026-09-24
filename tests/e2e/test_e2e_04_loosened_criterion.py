"""E2E-04: loosening a criterion stales the exclusions that cited it and
leaves inclusions alone.

docs/spec/14-testing.md §5: "Criteria loosened (not tightened): assert that
exclusions citing it go stale and inclusions do not." A scripted run against
a real git repository, single reviewer (assignment defaults to the one
actor per docs/spec/03-schemas.md §"screening.assignment" when unset), so
the scenario is about criteria/staleness mechanics, not dual-review
interaction (that is E2E-01's job).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from strata import gitio
from strata.cli.main import EXIT_OK, app
from strata.core.records import read_records
from strata.core.repo import Repo, open_repo
from strata.core.verify import verify_repository
from strata.protocol.rescreen import compute_stale_records

runner = CliRunner()

_RECORDS = """\
[
  {
    "id": "1",
    "type": "article-journal",
    "title": "A randomised trial of spaced retrieval practice",
    "author": [{"family": "Cepeda", "given": "Nicholas"}],
    "issued": {"date-parts": [[2008]]},
    "container-title": "Psychological Science",
    "DOI": "10.1111/e2e04.included",
    "abstract": "An included study, screened before the criterion was loosened."
  },
  {
    "id": "2",
    "type": "article-journal",
    "title": "A conference abstract on retrieval practice",
    "author": [{"family": "Roediger", "given": "Henry"}],
    "issued": {"date-parts": [[2009]]},
    "container-title": "Conference Proceedings",
    "DOI": "10.1111/e2e04.excluded",
    "abstract": "Excluded for being a conference abstract, not a full report."
  }
]
"""


def _run(args: list[str], input: str | None = None) -> object:  # noqa: A002
    result = runner.invoke(app, args, input=input)
    assert result.exit_code == EXIT_OK, result.output
    return result


@pytest.mark.req("E2E-04")
def test_loosened_criterion_stales_the_exclusion_not_the_inclusion(tmp_path: Path) -> None:
    root = tmp_path / "review"
    _run(
        [
            "init",
            str(root),
            "--title",
            "E2E-04 loosened criterion",
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
            "exclusion",
            "--label",
            "Conference abstract",
            "--definition",
            "The report is a conference abstract, not a full report.",
            "--applies-at",
            "title-abstract",
            "--by",
            "ethan",
            "--id",
            "EXC-01",
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

    repo = open_repo(root)
    included_id = _record_id_by_doi(repo, "10.1111/e2e04.included")
    excluded_id = _record_id_by_doi(repo, "10.1111/e2e04.excluded")
    # `screen`'s queue is sorted by canonical record id, not import order --
    # feed decisions in that order, not by DOI/title.
    decisions = {
        included_id: "i\n\n",
        excluded_id: "e\n1\n\n",
    }
    screen_all_input = "".join(decisions[rid] for rid in sorted(decisions))
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
        input=screen_all_input,
    )

    repo = open_repo(root)
    assert compute_stale_records(repo) == []

    # Loosen EXC-01: now excludes *fewer* papers than before.
    edit_result = _run(
        [
            "-C",
            str(root),
            "--why",
            "Piloting showed conference abstracts sometimes have enough detail; relaxing this.",
            "criteria",
            "edit",
            "EXC-01",
            "--direction",
            "loosened",
            "--by",
            "ethan",
            "--definition",
            "The report is a conference abstract with insufficient methodological detail.",
        ]
    )
    assert "loosened" in edit_result.output

    repo = open_repo(root)
    stale = compute_stale_records(repo)
    stale_ids = {s.record_id for s in stale}
    canonical_ids = {r["id"] for r in _canonical_records(repo)}

    # Only the exclusion that cited EXC-01 goes stale; the inclusion (which
    # never cited it, and could not be newly excluded by a loosened
    # criterion anyway) is untouched.
    assert stale_ids == {excluded_id}
    assert stale[0].reason == "criterion-loosened"
    assert stale[0].prior_decision == "exclude"
    assert stale[0].prior_criteria == ("EXC-01",)
    assert included_id in canonical_ids
    assert included_id not in stale_ids

    # Re-screen the one stale record: re-affirm the exclusion now that its
    # grounds have been reconsidered. Unlike `screen`, `rescreen` has no
    # note prompt -- just the decision, plus a citation prompt for `[e]xclude`.
    rescreen_result = _run(
        [
            "--why",
            "Re-screening records made stale by the loosened conference-abstract criterion.",
            "-C",
            str(root),
            "rescreen",
            "--by",
            "ethan",
        ],
        input="e\n1\n",
    )
    assert "1 decision" in rescreen_result.output

    repo = open_repo(root)
    assert compute_stale_records(repo) == []
    pool_tsv = (root / "derived" / "pool.tsv").read_text(encoding="utf-8")
    assert pool_tsv.count("\tinclude\t") == 1
    assert pool_tsv.count("\texclude\t") == 1

    report = verify_repository(repo)
    assert report.ok, report.issues
    assert not gitio.is_dirty(root)


def _canonical_records(repo: Repo) -> list[dict]:
    return [r for r in read_records(repo) if r["strata"]["canonical"]]


def _record_id_by_doi(repo: Repo, doi: str) -> str:
    for record in _canonical_records(repo):
        if record.get("DOI") == doi:
            return record["id"]
    raise AssertionError(f"no canonical record with DOI {doi!r}")
