import json
from pathlib import Path

from typer.testing import CliRunner

from strata import gitio
from strata.cli.main import EXIT_OK, EXIT_RATIONALE_REFUSED, EXIT_USAGE, app

runner = CliRunner()

_CLEAN_CSL = """\
[
  {"title": "First paper", "DOI": "10.1000/aaa"},
  {"title": "Second paper", "DOI": "10.1000/bbb"}
]
"""


def _init(tmp_path: Path, name: str = "review") -> Path:
    root = tmp_path / name
    result = runner.invoke(
        app,
        [
            "init",
            str(root),
            "--title",
            "Test Review",
            "--actor",
            "ethan",
            "--actor-name",
            "Ethan Test",
        ],
    )
    assert result.exit_code == EXIT_OK, result.output
    return root


def _add_search(root: Path) -> None:
    result = runner.invoke(
        app,
        [
            "--why",
            "recording the search before importing its results",
            "-C",
            str(root),
            "search",
            "add",
            "--database",
            "MEDLINE",
            "--platform",
            "Ovid",
            "--by",
            "ethan",
            "--query",
            "q",
        ],
    )
    assert result.exit_code == EXIT_OK, result.output


def test_import_commits_with_trailers(tmp_path: Path) -> None:
    root = _init(tmp_path)
    _add_search(root)
    export = tmp_path / "export.json"
    export.write_text(_CLEAN_CSL, encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "--why",
            "importing the first MEDLINE export",
            "-C",
            str(root),
            "import",
            str(export),
            "--by",
            "ethan",
            "--search",
            "S-01-medline",
        ],
    )
    assert result.exit_code == EXIT_OK, result.output
    assert "2 new" in result.output
    assert not gitio.is_dirty(root)

    message = gitio.run(["log", "-1", "--format=%B"], cwd=root).stdout
    assert "Strata-Op: import" in message
    assert "Strata-Actor: ethan" in message

    records_path = root / "records" / "records.ndjson"
    lines = [line for line in records_path.read_text(encoding="utf-8").splitlines() if line]
    assert len(lines) == 2


def test_import_idempotent_second_run_reports_already_imported(tmp_path: Path) -> None:
    root = _init(tmp_path)
    _add_search(root)
    export = tmp_path / "export.json"
    export.write_text(_CLEAN_CSL, encoding="utf-8")

    first = runner.invoke(
        app,
        [
            "--why",
            "first import",
            "-C",
            str(root),
            "import",
            str(export),
            "--by",
            "ethan",
            "--search",
            "S-01-medline",
        ],
    )
    assert first.exit_code == EXIT_OK, first.output

    second = runner.invoke(
        app,
        ["-C", str(root), "import", str(export), "--by", "ethan", "--search", "S-01-medline"],
    )
    assert second.exit_code == EXIT_OK, second.output
    assert "already imported" in second.output
    assert not gitio.is_dirty(root)

    second_json = runner.invoke(
        app,
        [
            "--json",
            "-C",
            str(root),
            "import",
            str(export),
            "--by",
            "ethan",
            "--search",
            "S-01-medline",
        ],
    )
    assert second_json.exit_code == EXIT_OK, second_json.output
    payload = json.loads(second_json.output)
    assert payload[0]["already_imported"] is True


def test_import_dry_run_writes_nothing(tmp_path: Path) -> None:
    root = _init(tmp_path)
    _add_search(root)
    export = tmp_path / "export.json"
    export.write_text(_CLEAN_CSL, encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "-C",
            str(root),
            "import",
            str(export),
            "--by",
            "ethan",
            "--search",
            "S-01-medline",
            "--dry-run",
        ],
    )
    assert result.exit_code == EXIT_OK, result.output
    assert "would import" in result.output
    assert not gitio.is_dirty(root)
    records_path = root / "records" / "records.ndjson"
    assert records_path.read_text(encoding="utf-8") == ""


def test_import_no_commit_flag_leaves_tree_dirty(tmp_path: Path) -> None:
    root = _init(tmp_path)
    _add_search(root)
    export = tmp_path / "export.json"
    export.write_text(_CLEAN_CSL, encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "--no-commit",
            "-C",
            str(root),
            "import",
            str(export),
            "--by",
            "ethan",
            "--search",
            "S-01-medline",
        ],
    )
    assert result.exit_code == EXIT_OK, result.output
    assert gitio.is_dirty(root)


def test_import_requires_rationale_non_interactively(tmp_path: Path) -> None:
    root = _init(tmp_path)
    _add_search(root)
    export = tmp_path / "export.json"
    export.write_text(_CLEAN_CSL, encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "-C",
            str(root),
            "import",
            str(export),
            "--by",
            "ethan",
            "--search",
            "S-01-medline",
        ],
    )
    assert result.exit_code == EXIT_RATIONALE_REFUSED, result.output
    # Records/manifest/events are written before the commit is attempted.
    assert gitio.is_dirty(root)


def test_import_unknown_actor_reports_usage_error(tmp_path: Path) -> None:
    root = _init(tmp_path)
    _add_search(root)
    export = tmp_path / "export.json"
    export.write_text(_CLEAN_CSL, encoding="utf-8")

    result = runner.invoke(
        app,
        ["-C", str(root), "import", str(export), "--by", "nobody", "--search", "S-01-medline"],
    )
    assert result.exit_code == EXIT_USAGE, result.output


def test_import_missing_file_reports_usage_error_and_continues(tmp_path: Path) -> None:
    root = _init(tmp_path)
    _add_search(root)
    good = tmp_path / "export.json"
    good.write_text(_CLEAN_CSL, encoding="utf-8")
    missing = tmp_path / "nope.json"

    result = runner.invoke(
        app,
        [
            "--why",
            "importing one good file and one missing file",
            "-C",
            str(root),
            "import",
            str(missing),
            str(good),
            "--by",
            "ethan",
            "--search",
            "S-01-medline",
        ],
    )
    assert result.exit_code == EXIT_USAGE, result.output
    # The good file after the bad one in the same invocation still imports.
    records_path = root / "records" / "records.ndjson"
    lines = [line for line in records_path.read_text(encoding="utf-8").splitlines() if line]
    assert len(lines) == 2


def test_import_json_output_shape(tmp_path: Path) -> None:
    root = _init(tmp_path)
    _add_search(root)
    export = tmp_path / "export.json"
    export.write_text(_CLEAN_CSL, encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "--why",
            "checking the --json output shape",
            "--json",
            "-C",
            str(root),
            "import",
            str(export),
            "--by",
            "ethan",
            "--search",
            "S-01-medline",
        ],
    )
    assert result.exit_code == EXIT_OK, result.output
    payload = json.loads(result.output)
    assert len(payload) == 1
    assert payload[0]["records_created"] == 2
    assert payload[0]["already_imported"] is False


def test_import_via_flag_without_search(tmp_path: Path) -> None:
    root = _init(tmp_path)
    export = tmp_path / "export.json"
    export.write_text(_CLEAN_CSL, encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "--why",
            "citation-chasing results",
            "-C",
            str(root),
            "import",
            str(export),
            "--by",
            "ethan",
            "--via",
            "citation-searching",
        ],
    )
    assert result.exit_code == EXIT_OK, result.output


def test_import_rejects_both_search_and_via(tmp_path: Path) -> None:
    root = _init(tmp_path)
    _add_search(root)
    export = tmp_path / "export.json"
    export.write_text(_CLEAN_CSL, encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "-C",
            str(root),
            "import",
            str(export),
            "--by",
            "ethan",
            "--search",
            "S-01-medline",
            "--via",
            "citation-searching",
        ],
    )
    assert result.exit_code == EXIT_USAGE, result.output
