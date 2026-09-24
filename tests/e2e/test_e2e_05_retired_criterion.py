"""E2E-05: retiring a criterion stales every exclusion that cited it (a
cascade across however many records relied on it), and re-screening lets
each one land wherever the remaining, still-active grounds actually put it
-- some stay excluded on separate grounds, some get promoted back in.

docs/spec/14-testing.md §5: "A criterion retired after exclusions cited it;
assert cascade and re-screen." Single reviewer (see test_e2e_04's docstring
for why: this is a criteria/staleness-mechanics scenario, not a dual-review
one -- that is E2E-01's job).
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
  {"id": "a", "type": "article-journal", "title": "A rodent model of spatial memory",
   "author": [{"family": "Morris", "given": "Richard"}], "issued": {"date-parts": [[2005]]},
   "container-title": "Journal of Neuroscience", "DOI": "10.1111/e2e05.a",
   "abstract": "A study excluded for using an animal model."},
  {"id": "b", "type": "article-journal", "title": "A murine model of consolidation",
   "author": [{"family": "Morris", "given": "Richard"}], "issued": {"date-parts": [[2006]]},
   "container-title": "Journal of Neuroscience", "DOI": "10.1111/e2e05.b",
   "abstract": "Another study excluded for using an animal model."},
  {"id": "c", "type": "article-journal", "title": "An unregistered pilot report",
   "author": [{"family": "Doe", "given": "Jane"}], "issued": {"date-parts": [[2012]]},
   "container-title": "Working Paper Series", "DOI": "10.1111/e2e05.c",
   "abstract": "Excluded for not being peer reviewed, on separate grounds."},
  {"id": "d", "type": "article-journal", "title": "A human retrieval-practice trial",
   "author": [{"family": "Roediger", "given": "Henry"}], "issued": {"date-parts": [[2011]]},
   "container-title": "Psychological Science", "DOI": "10.1111/e2e05.d",
   "abstract": "An included human study, untouched by anything in this scenario."}
]
"""


def _run(args: list[str], input: str | None = None) -> object:  # noqa: A002
    result = runner.invoke(app, args, input=input)
    assert result.exit_code == EXIT_OK, result.output
    return result


def _canonical_records(repo: Repo) -> list[dict]:
    return [r for r in read_records(repo) if r["strata"]["canonical"]]


def _record_id_by_doi(repo: Repo, doi: str) -> str:
    for record in _canonical_records(repo):
        if record.get("DOI") == doi:
            return record["id"]
    raise AssertionError(f"no canonical record with DOI {doi!r}")


def _ordered_input(by_doi: dict[str, str], repo: Repo) -> str:
    """`screen`/`rescreen`'s queue is sorted by canonical record id, not
    import order -- resolve each DOI's id and concatenate in that order."""
    by_id = {_record_id_by_doi(repo, doi): text for doi, text in by_doi.items()}
    return "".join(by_id[rid] for rid in sorted(by_id))


@pytest.mark.req("E2E-05")
def test_retired_criterion_cascades_and_rescreens_to_mixed_outcomes(tmp_path: Path) -> None:
    root = tmp_path / "review"
    _run(
        [
            "init",
            str(root),
            "--title",
            "E2E-05 retired criterion",
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
            "Not peer reviewed",
            "--definition",
            "The report was not published in a peer-reviewed venue.",
            "--applies-at",
            "title-abstract",
            "--by",
            "ethan",
            "--id",
            "EXC-01",
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
            "Animal model",
            "--definition",
            "The sample was non-human.",
            "--applies-at",
            "title-abstract",
            "--by",
            "ethan",
            "--id",
            "EXC-02",
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
    # EXC-01 is criterion #1, EXC-02 is criterion #2 in this stage's active list.
    screen_input = _ordered_input(
        {
            "10.1111/e2e05.a": "e\n2\n\n",  # exclude citing EXC-02 (animal model)
            "10.1111/e2e05.b": "e\n2\n\n",  # exclude citing EXC-02 (animal model)
            "10.1111/e2e05.c": "e\n1\n\n",  # exclude citing EXC-01 (not peer reviewed)
            "10.1111/e2e05.d": "i\n\n",  # include
        },
        repo,
    )
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
        input=screen_input,
    )

    repo = open_repo(root)
    assert compute_stale_records(repo) == []

    a_id = _record_id_by_doi(repo, "10.1111/e2e05.a")
    b_id = _record_id_by_doi(repo, "10.1111/e2e05.b")
    c_id = _record_id_by_doi(repo, "10.1111/e2e05.c")
    d_id = _record_id_by_doi(repo, "10.1111/e2e05.d")

    retire_result = _run(
        [
            "-C",
            str(root),
            "--why",
            "EXC-02 turned out to be redundant with the population criterion; retiring it.",
            "criteria",
            "retire",
            "EXC-02",
            "--by",
            "ethan",
        ]
    )
    assert "retired" in retire_result.output

    repo = open_repo(root)
    stale = compute_stale_records(repo)
    stale_ids = {s.record_id for s in stale}

    # The cascade: both exclusions that cited the retired EXC-02 go stale.
    # The one citing EXC-01 (never retired) and the inclusion are untouched.
    assert stale_ids == {a_id, b_id}
    assert all(s.reason == "criterion-retired" for s in stale)
    assert all(s.prior_criteria == ("EXC-02",) for s in stale)

    # Re-screen the cascade: on a closer look, `a` still has separate
    # grounds to exclude (EXC-01), but `b` does not and is promoted to
    # include. Unlike `screen`, `rescreen` has no note prompt -- just the
    # decision, plus a citation prompt for `[e]xclude`.
    rescreen_input = _ordered_input(
        {
            "10.1111/e2e05.a": "e\n1\n",
            "10.1111/e2e05.b": "i\n",
        },
        repo,
    )
    rescreen_result = _run(
        [
            "--why",
            "Re-screening the two records made stale by retiring EXC-02.",
            "-C",
            str(root),
            "rescreen",
            "--by",
            "ethan",
        ],
        input=rescreen_input,
    )
    assert "2 decision" in rescreen_result.output

    repo = open_repo(root)
    assert compute_stale_records(repo) == []

    pool_tsv = (root / "derived" / "pool.tsv").read_text(encoding="utf-8")
    assert f"{a_id}\texclude\t" in pool_tsv
    assert f"{b_id}\tinclude\t" in pool_tsv
    assert f"{c_id}\texclude\t" in pool_tsv
    assert f"{d_id}\tinclude\t" in pool_tsv
    assert pool_tsv.count("\tinclude\t") == 2
    assert pool_tsv.count("\texclude\t") == 2

    report = verify_repository(repo)
    assert report.ok, report.issues
    assert not gitio.is_dirty(root)
