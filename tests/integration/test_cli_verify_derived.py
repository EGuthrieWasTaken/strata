"""`strata verify` notices a derived file that is not what regeneration writes
(`E_DERIVED_DRIFT`; openspec:repository-verification#cross-schema-validation-rules and
openspec:repository-format#repository-layout).

`verify` used to check only that the counts the events *would* produce close, so a counts file that
had gone out of date (after a web dedup merge, for one) passed. Found while writing the web write
screens (OpenSpec change `add-web-ui-write-surfaces`); making `verify` check the files then showed
that `strata init`, `strata import`, `strata dedup` and `strata fix` left derived files out of date
too, so a test below runs a whole review through the commands and holds every one to the check.
"""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from strata import gitio
from strata.cli import main as cli_main
from strata.cli.main import EXIT_OK, EXIT_VALIDATION, app
from strata.core import records as records_mod
from strata.core.repo import open_repo
from strata.protocol import pool as pool_mod

runner = CliRunner()

_A = (
    '[{"title": "Learning and spacing effects in memory consolidation", '
    '"author": [{"family": "Cepeda"}, {"family": "Vul"}], '
    '"issued": {"date-parts": [[2008]]}, "container-title": "Psychological Science", '
    '"volume": "19", "page": "1095", "DOI": "10.1000/spacing"}]'
)
_B = (
    '[{"title": "Spacing and learning effects in memory consolidation", '
    '"author": [{"family": "Cepeda"}, {"family": "Vul"}], '
    '"issued": {"date-parts": [[2008]]}, "container-title": "Psychological Science", '
    '"volume": "19", "page": "1095"}, '
    '{"title": "Unrelated paper about sleep", "author": [{"family": "Doe"}], '
    '"issued": {"date-parts": [[2012]]}, "DOI": "10.1000/sleep"}]'
)


@pytest.fixture(autouse=True)
def _wide_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    for console in (cli_main.out_console, cli_main.err_console):
        monkeypatch.setattr(console, "_width", 1000)


def _run(root: Path, *args: str) -> tuple[int, str]:
    result = runner.invoke(app, ["-C", str(root), *args])
    return result.exit_code, " ".join(result.output.split())


def _ok(root: Path, *args: str) -> None:
    code, out = _run(root, *args)
    assert code == EXIT_OK, out


def _init(tmp_path: Path) -> Path:
    root = tmp_path / "review"
    result = runner.invoke(
        app, ["init", str(root), "--title", "T", "--actor", "ethan", "--actor-name", "Ethan"]
    )
    assert result.exit_code == EXIT_OK, result.output
    return root


def _drift(root: Path) -> list[str]:
    return pool_mod.derived_drift(open_repo(root))


def _with_records(tmp_path: Path) -> Path:
    root = _init(tmp_path)
    export = tmp_path / "a.json"
    export.write_text(_A, encoding="utf-8")
    _ok(
        root, "--why", "a search for the drift test", "search", "add", "--database", "MEDLINE",
        "--platform", "Ovid", "--by", "ethan", "--query", "q",
    )  # fmt: skip
    _ok(
        root, "--why", "importing the first file", "import", str(export), "--by", "ethan",
        "--search", "S-01-medline",
    )  # fmt: skip
    return root


# ------------------------------------------------------------------------------- the check


def test_a_new_review_verifies_clean_and_its_derived_files_are_real(tmp_path: Path) -> None:
    root = _init(tmp_path)

    code, out = _run(root, "verify")

    assert code == EXIT_OK, out
    assert _drift(root) == []
    irr = json.loads((root / "derived" / "irr.json").read_text())
    assert sorted(irr) == ["full-text", "title-abstract"]  # not the `{}` placeholder it began as
    assert json.loads((root / "derived" / "counts.json").read_text())["assertions"]


def test_a_counts_file_that_is_out_of_date_is_reported(tmp_path: Path) -> None:
    root = _with_records(tmp_path)
    assert _run(root, "verify")[0] == EXIT_OK
    counts = root / "derived" / "counts.json"
    counts.write_text(counts.read_text().replace('"lhs":1', '"lhs":0', 1), encoding="utf-8")

    code, out = _run(root, "verify")

    assert code == EXIT_VALIDATION
    assert "E_DERIVED_DRIFT" in out and "derived/counts.json" in out
    assert "strata verify --fix" in out


def test_a_change_that_forgot_to_regenerate_is_reported(tmp_path: Path) -> None:
    # What `strata fix` used to do: write the record and the event, and leave the pool as it was.
    root = _with_records(tmp_path)
    repo = open_repo(root)
    record_id = records_mod.read_records(repo)[0]["id"]
    records_mod.amend_field(
        repo,
        record_id=record_id,
        field="title",
        value="A title nobody told the pool",
        actor="ethan",
    )

    code, out = _run(root, "verify")

    assert code == EXIT_VALIDATION
    assert "E_DERIVED_DRIFT" in out and "derived/pool.tsv" in out
    assert "derived/counts.json" not in out  # only the file that is wrong


def test_a_derived_file_that_does_not_exist_is_not_drift(tmp_path: Path) -> None:
    root = _with_records(tmp_path)
    (root / "derived" / "pool.tsv").unlink()

    code, out = _run(root, "verify")

    assert code == EXIT_OK, out


def test_fast_verification_does_not_check_drift_yet(tmp_path: Path) -> None:
    # Recorded so the gap is visible: the specification wants `--fast` to check drift within two
    # seconds on 50,000 records, and regenerating the views does not fit that yet.
    root = _with_records(tmp_path)
    (root / "derived" / "counts.json").write_text("{}\n", encoding="utf-8")

    assert _run(root, "verify", "--fast")[0] == EXIT_OK
    assert _run(root, "verify")[0] == EXIT_VALIDATION


# ------------------------------------------------------------------------------------- --fix


def test_fix_regenerates_what_drifted_and_leaves_the_rest_alone(tmp_path: Path) -> None:
    root = _with_records(tmp_path)
    (root / "derived" / "counts.json").write_text("{}\n", encoding="utf-8")
    gitio.add_all(root)
    gitio.commit(root, "test: a counts file gone wrong\n\nStrata-Op: test\nStrata-Actor: ethan")

    code, out = _run(root, "verify", "--fix")

    assert code == EXIT_OK, out
    assert "regenerated derived/counts.json" in out
    assert "regenerated derived/pool.tsv" not in out
    assert _drift(root) == []
    status = gitio.run(["status", "--porcelain"], cwd=root).stdout.split()
    assert status == ["M", "derived/counts.json"]  # regenerated, not committed
    assert _run(root, "verify")[0] == EXIT_OK


def test_fix_has_nothing_to_do_on_a_repository_that_verifies(tmp_path: Path) -> None:
    root = _with_records(tmp_path)

    code, out = _run(root, "verify", "--fix")

    assert code == EXIT_OK
    assert "regenerated" not in out
    assert gitio.run(["status", "--porcelain"], cwd=root).stdout == ""


def test_fix_reports_in_json_what_it_regenerated(tmp_path: Path) -> None:
    root = _with_records(tmp_path)
    (root / "derived" / "irr.json").write_text("{}\n", encoding="utf-8")

    code, out = _run(root, "--json", "verify", "--fix")

    assert code == EXIT_OK
    report = json.loads(out)
    assert report["ok"] is True and report["regenerated"] == ["derived/irr.json"]


def test_fix_does_not_pretend_to_repair_what_it_does_not_regenerate(tmp_path: Path) -> None:
    root = _with_records(tmp_path)
    (root / "protocol" / "searches" / "S-01-medline.yaml").write_text("id: broken\n")

    code, out = _run(root, "verify", "--fix")

    assert code == EXIT_VALIDATION
    assert "E_SCHEMA" in out


# ------------------------------------------------------------- no command leaves the views stale


def test_no_command_leaves_a_derived_file_out_of_date(tmp_path: Path) -> None:
    root = _init(tmp_path)
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    a.write_text(_A, encoding="utf-8")
    b.write_text(_B, encoding="utf-8")
    steps: list[tuple[str, ...]] = [
        ("--why", "adding sam to the team", "actor", "add", "sam", "Sam", "--role", "screener"),
        ("--why", "a database search", "search", "add", "--database", "MEDLINE", "--platform",
         "Ovid", "--by", "ethan", "--query", "q"),
        ("--why", "importing the first file", "import", str(a), "--by", "ethan", "--search",
         "S-01-medline"),
        ("--why", "importing the second file", "import", str(b), "--by", "ethan", "--search",
         "S-01-medline"),
        ("--why", "adding the exclusion criterion", "criteria", "add", "--kind", "exclusion",
         "--label", "Not empirical", "--definition", "Not an empirical study", "--applies-at",
         "title-abstract,full-text", "--by", "ethan"),
        ("--why", "merging the duplicate pair", "dedup", "--by", "ethan"),
    ]  # fmt: skip
    for step in steps:
        _ok(root, *step)
        assert _drift(root) == [], f"after {' '.join(step[2:6])}"

    ids = sorted(
        r["id"]
        for r in records_mod.read_records(open_repo(root))
        if r.get("strata", {}).get("canonical", True)
    )
    decisions = tmp_path / "decisions.tsv"
    decisions.write_text(
        "record_id\tdecision\tcriteria\tnote\n" + "".join(f"{i}\tinclude\t\t\n" for i in ids),
        encoding="utf-8",
    )
    later: list[tuple[str, ...]] = [
        ("--why", "correcting a title", "fix", ids[0], "--field", "title", "--value", "A new title",
         "--by", "ethan"),
        ("--why", "assigning both of us", "assign", "title-abstract", "--actors", "ethan,sam",
         "--by", "ethan"),
        ("--why", "ethan screens", "screen", "title-abstract", "--by", "ethan", "--decisions",
         str(decisions)),
        ("--why", "sam screens", "screen", "title-abstract", "--by", "sam", "--decisions",
         str(decisions)),
        ("--why", "retrieving a full text", "retrieve", "--by", "ethan", "--report",
         "rpt_" + ids[0][4:], "--outcome", "retrieved", "--source", "institutional-access"),
        ("--why", "tightening the criterion", "criteria", "edit", "EXC-01", "--direction",
         "tightened", "--by", "ethan", "--definition", "Not an empirical study at all"),
        ("--why", "deactivating sam", "actor", "deactivate", "sam"),
    ]  # fmt: skip
    for step in later:
        _ok(root, *step)
        assert _drift(root) == [], f"after {' '.join(step[2:6])}"

    code, out = _run(root, "verify")
    assert code == EXIT_OK, out
