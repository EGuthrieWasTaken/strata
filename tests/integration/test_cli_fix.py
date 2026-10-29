"""`strata fix` corrects authors and years, keeps a record's identity in step with its
corrections, and does nothing when there is nothing to do (OpenSpec change
`add-web-ui-write-surfaces`; openspec:cli#correcting-a-record and
openspec:record-identity#identifiers-are-permanent).

Before this, `strata fix` refused `author` and the year, left the identity a record is matched by
as it had been (so an export carrying a corrected DOI was added beside the record), kept whatever
spacing and capitals it was typed with, and recorded a correction to the value a record already had.
"""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from strata import gitio
from strata.cli import main as cli_main
from strata.cli.main import EXIT_OK, EXIT_USAGE, app
from strata.core import aliases as aliases_mod
from strata.core import records as records_mod
from strata.core.repo import open_repo
from strata.protocol import pool as pool_mod

runner = CliRunner()

_PAPER = {
    "title": "Spacing effects in learning",
    "DOI": "10.1000/wrong",
    "author": [{"family": "Cepeda", "given": "N."}],
    "issued": {"date-parts": [[2008, 3]]},
}
_NO_DOI = {k: v for k, v in _PAPER.items() if k != "DOI"}


@pytest.fixture(autouse=True)
def _wide_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    for console in (cli_main.out_console, cli_main.err_console):
        monkeypatch.setattr(console, "_width", 1000)


def _run(root: Path, *args: str) -> tuple[int, str]:
    result = runner.invoke(app, ["-C", str(root), *args])
    return result.exit_code, " ".join(result.output.split())


def _ok(root: Path, *args: str) -> str:
    code, out = _run(root, *args)
    assert code == EXIT_OK, out
    return out


def _review(tmp_path: Path, rows: list[dict]) -> tuple[Path, str]:
    root = tmp_path / "review"
    result = runner.invoke(
        app, ["init", str(root), "--title", "T", "--actor", "ethan", "--actor-name", "Ethan"]
    )
    assert result.exit_code == EXIT_OK, result.output
    for database in ("MEDLINE", "Embase"):
        _ok(
            root, "--why", f"a {database} search for the fix tests", "search", "add", "--database",
            database, "--platform", "Ovid", "--by", "ethan", "--query", "q",
        )  # fmt: skip
    _import(tmp_path, root, "first.json", rows, "S-01-medline")
    return root, records_mod.read_records(open_repo(root))[0]["id"]


def _import(tmp_path: Path, root: Path, name: str, rows: list[dict], search: str) -> str:
    export = tmp_path / name
    export.write_text(json.dumps(rows), encoding="utf-8")
    return _ok(
        root, "--why", f"importing {name} for the test", "import", str(export), "--by", "ethan",
        "--search", search,
    )  # fmt: skip


def _fix(root: Path, rid: str, field: str, value: str) -> tuple[int, str]:
    return _run(
        root, "--why", "correcting the record by hand", "fix", rid, "--field", field,
        "--value", value, "--by", "ethan",
    )  # fmt: skip


def _records(root: Path) -> list[dict]:
    return records_mod.read_records(open_repo(root))


def _commits(root: Path) -> int:
    return len(gitio.log(root))


# --------------------------------------------------------------------------- authors and years


def test_the_year_can_be_corrected_and_keeps_the_month(tmp_path: Path) -> None:
    root, rid = _review(tmp_path, [_PAPER])

    code, out = _fix(root, rid, "year", "2009")

    assert code == EXIT_OK
    assert out == f"fixed {rid}.year: '2008-03' -> '2009-03'"
    assert _records(root)[0]["issued"] == {"date-parts": [[2009, 3]]}
    assert pool_mod.derived_drift(open_repo(root)) == []
    assert "2009" in (root / "derived" / "pool.tsv").read_text()


def test_the_whole_date_can_be_corrected(tmp_path: Path) -> None:
    root, rid = _review(tmp_path, [_PAPER])

    code, out = _fix(root, rid, "issued", "2009-11-30")

    assert code == EXIT_OK and out == f"fixed {rid}.issued: '2008-03' -> '2009-11-30'"
    assert _records(root)[0]["issued"] == {"date-parts": [[2009, 11, 30]]}


def test_the_authors_can_be_corrected_and_appear_readably_in_the_timeline(tmp_path: Path) -> None:
    root, rid = _review(tmp_path, [_PAPER])

    code, out = _fix(root, rid, "author", "Cepeda, Nicholas J.; Vul, Edward")

    assert code == EXIT_OK
    assert out == f"fixed {rid}.author: 'Cepeda, N.' -> 'Cepeda, Nicholas J.; Vul, Edward'"
    assert _records(root)[0]["author"] == [
        {"family": "Cepeda", "given": "Nicholas J."},
        {"family": "Vul", "given": "Edward"},
    ]
    why = _ok(root, "why", rid)
    assert "old: Cepeda, N." in why and "new: Cepeda, Nicholas J.; Vul, Edward" in why


def test_the_json_output_carries_the_stored_values(tmp_path: Path) -> None:
    root, rid = _review(tmp_path, [_PAPER])

    code, out = _run(
        root, "--json", "--why", "correcting the authors", "fix", rid, "--field", "author",
        "--value", "Vul, Edward", "--by", "ethan",
    )  # fmt: skip

    assert code == EXIT_OK
    assert json.loads(out) == {
        "record": rid,
        "field": "author",
        "old": [{"family": "Cepeda", "given": "N."}],
        "new": [{"family": "Vul", "given": "Edward"}],
    }


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("year", "nineteen", "error: a year is four digits, got 'nineteen'"),
        ("issued", "2008-13", "error: '2008-13' is not a real date"),
        ("title", "  ", "error: a title cannot be empty"),
        (
            "author",
            ", Nicholas",
            "error: an author needs a family name before the comma: ', Nicholas'",
        ),
    ],
)
def test_a_value_that_does_not_fit_is_refused_and_nothing_is_written(
    tmp_path: Path, field: str, value: str, message: str
) -> None:
    root, rid = _review(tmp_path, [_PAPER])
    before = _commits(root)

    code, out = _fix(root, rid, field, value)

    assert code == EXIT_USAGE and out == message
    assert _commits(root) == before
    assert gitio.run(["status", "--porcelain"], cwd=root).stdout == ""


# ---------------------------------------------------------------------------- tidying and nothing


def test_an_identifier_is_stored_as_an_import_stores_it_and_an_empty_value_removes_a_field(
    tmp_path: Path,
) -> None:
    root, rid = _review(tmp_path, [_PAPER])

    _ok(root, "--why", "correcting the doi", "fix", rid, "--field", "DOI", "--value",
        "  https://doi.org/10.1000/RIGHT. ", "--by", "ethan")  # fmt: skip
    assert _records(root)[0]["DOI"] == "10.1000/right"

    code, out = _fix(root, rid, "DOI", "")
    assert code == EXIT_OK and out.startswith(f"fixed {rid}.DOI: '10.1000/right' -> None")
    assert "DOI" not in _records(root)[0]


def test_a_value_the_record_already_has_is_not_recorded_and_needs_no_rationale(
    tmp_path: Path,
) -> None:
    root, rid = _review(tmp_path, [_PAPER])
    before = _commits(root)

    # No `--why`, in a script: a correction would be refused for want of one.
    code, out = _run(
        root, "fix", rid, "--field", "title", "--value", " Spacing effects in learning ",
        "--by", "ethan",
    )  # fmt: skip

    assert code == EXIT_OK
    assert out == f"unchanged {rid}.title is already 'Spacing effects in learning'"
    assert _commits(root) == before
    assert not (root / "events" / "fix").exists()


# ------------------------------------------------------------------------------------- identity


def test_an_export_carrying_the_corrected_doi_is_matched_to_the_record_not_added(
    tmp_path: Path,
) -> None:
    root, rid = _review(tmp_path, [_PAPER])

    out = _fix(root, rid, "DOI", "10.1000/right")[1]
    assert "the record keeps its id; an export carrying the corrected value now matches it" in out
    corrected = {**_PAPER, "DOI": "10.1000/right"}
    imported = _import(tmp_path, root, "corrected.json", [corrected], "S-01-embase")

    assert "0 new, 1 matched existing" in imported
    [record] = _records(root)
    assert record["id"] == rid and record["strata"]["canonical_key"] == "doi:10.1000/right"
    assert [s["search"] for s in record["strata"]["sources"]] == ["S-01-medline", "S-01-embase"]


def test_an_export_that_still_carries_the_old_doi_is_matched_as_well(tmp_path: Path) -> None:
    root, rid = _review(tmp_path, [_PAPER])
    _fix(root, rid, "DOI", "10.1000/right")

    # The same paper from another database (a different file, so not an import already made).
    imported = _import(tmp_path, root, "again.json", [{**_PAPER, "abstract": "x"}], "S-01-embase")

    assert "0 new, 1 matched existing" in imported
    assert len(_records(root)) == 1


def test_correcting_the_year_of_a_record_with_no_identifier_follows_the_identity(
    tmp_path: Path,
) -> None:
    root, rid = _review(tmp_path, [_NO_DOI])
    _fix(root, rid, "year", "2009")

    corrected = {**_NO_DOI, "issued": {"date-parts": [[2009]]}}
    again = _import(tmp_path, root, "corrected.json", [corrected], "S-01-embase")
    original = _import(
        tmp_path, root, "original.json", [{**_NO_DOI, "abstract": "x"}], "S-01-embase"
    )

    assert "0 new, 1 matched existing" in again
    assert "0 new, 1 matched existing" in original
    assert len(_records(root)) == 1


def test_the_alias_is_recorded_with_the_event_that_made_it(tmp_path: Path) -> None:
    root, rid = _review(tmp_path, [_PAPER])

    out = _run(
        root, "--json", "--why", "correcting the doi", "fix", rid, "--field", "DOI", "--value",
        "10.1000/right", "--by", "ethan",
    )[1]  # fmt: skip

    alias = json.loads(out)["alias"]
    [entry] = aliases_mod.read_aliases(open_repo(root))
    assert entry["alias"] == alias and entry["canonical"] == rid
    assert entry["reason"] == "correction"
    assert aliases_mod.resolve(open_repo(root), alias) == rid
    assert _ok(root, "verify")  # a correction leaves the repository valid


def test_correcting_onto_another_records_identity_says_so_and_dedup_can_merge_them(
    tmp_path: Path,
) -> None:
    root, first = _review(
        tmp_path,
        [
            {**_PAPER, "DOI": "10.1000/a", "title": "Spacing effects in learning"},
            {**_PAPER, "DOI": "10.1000/b", "title": "Spacing effects in learning, a replication"},
        ],
    )
    first, second = sorted(r["id"] for r in _records(root))

    code, out = _fix(root, first, "DOI", "10.1000/b")

    assert code == EXIT_OK
    assert f"{first} is now identified as {second}; run `strata dedup` to merge them" in out
    assert aliases_mod.read_aliases(open_repo(root)) == []
    merged = _ok(root, "--why", "merging the pair the correction made", "dedup", "--by", "ethan")
    assert "1 auto-merged" in merged
    assert sum(1 for r in _records(root) if r["strata"]["canonical"]) == 1
    assert _ok(root, "verify")


def test_every_correction_leaves_the_derived_files_in_step(tmp_path: Path) -> None:
    root, rid = _review(tmp_path, [_PAPER])
    for field, value in (
        ("title", "A corrected title"),
        ("year", "2010"),
        ("author", "Vul, Edward"),
        ("DOI", "10.1000/right"),
        ("DOI", ""),
    ):
        assert _fix(root, rid, field, value)[0] == EXIT_OK
        assert pool_mod.derived_drift(open_repo(root)) == [], f"after {field}"
