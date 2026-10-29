"""Pins `strata search add` and `strata import` as they behave today.

Written before the two commands moved onto `strata.core.operations` (OpenSpec change
`add-web-ui-write-surfaces`, task 1.1) and kept afterwards: every assertion here is about what a
person at a terminal sees and what lands in the repository, so it must hold on both sides of that
move. The looser behavioural tests in `test_cli_search.py` and `test_cli_import.py` stay as they
are; these pin the exact text, files and commit messages.

Output is compared after collapsing whitespace (rich wraps at the terminal width) and replacing the
temporary directory and generated import ids, which are the only parts that differ between runs.
"""

import json
import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from strata import gitio
from strata.cli import main as cli_main
from strata.cli.main import EXIT_OK, EXIT_RATIONALE_REFUSED, EXIT_USAGE, app

runner = CliRunner()

_IMPORT_ID = re.compile(r"imp_[0-9a-z]{26}")

_TWO_PAPERS = json.dumps(
    [
        {"title": "First paper", "DOI": "10.1000/aaa"},
        {"title": "Second paper", "DOI": "10.1000/bbb"},
    ]
)

_SEARCH_ARGS = [
    "search",
    "add",
    "--database",
    "MEDLINE",
    "--platform",
    "Ovid",
    "--by",
    "ethan",
    "--executed",
    "2026-03-04",
    "--query",
    "1 exp Learning/",
    "--hits",
    "4182",
    "--export-file",
    "medline.ris",
]


@pytest.fixture(autouse=True)
def _wide_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    # rich wraps at the terminal width, and it can break a long temporary path mid-token, which
    # whitespace collapsing cannot undo. A fixed, very wide terminal makes the output
    # independent of how long the temporary directory's name is. The consoles are built when the
    # module is imported, so the width is set on them rather than through COLUMNS.
    for console in (cli_main.out_console, cli_main.err_console):
        monkeypatch.setattr(console, "_width", 1000)


def _init(tmp_path: Path) -> Path:
    root = tmp_path / "review"
    result = runner.invoke(
        app,
        ["init", str(root), "--title", "Test Review", "--actor", "ethan", "--actor-name", "Ethan"],
    )
    assert result.exit_code == EXIT_OK, result.output
    return root


def _normalise(text: str, tmp_path: Path) -> str:
    text = text.replace(str(tmp_path), "<TMP>").replace("<TMP>\\", "<TMP>/")  # Windows paths
    return _IMPORT_ID.sub("<IMPORT>", " ".join(text.split()))


def _head_message(root: Path) -> str:
    return _IMPORT_ID.sub("<IMPORT>", gitio.run(["log", "-1", "--format=%B"], cwd=root).stdout)


def _head_files(root: Path) -> list[str]:
    out = gitio.run(["show", "--name-only", "--format=", "HEAD"], cwd=root).stdout
    return sorted(_IMPORT_ID.sub("<IMPORT>", line) for line in out.splitlines() if line)


def _commit_count(root: Path) -> int:
    return len(gitio.log(root))


def _status(root: Path) -> list[str]:
    out = gitio.run(["status", "--porcelain", "--untracked-files=all"], cwd=root).stdout
    return sorted(_IMPORT_ID.sub("<IMPORT>", line) for line in out.splitlines() if line)


def _add_search(root: Path) -> None:
    result = runner.invoke(
        app,
        ["--why", "first database search of the review", "-C", str(root), *_SEARCH_ARGS],
    )
    assert result.exit_code == EXIT_OK, result.output


def _write(tmp_path: Path, name: str, text: str = _TWO_PAPERS) -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------------------------
# strata search add
# ---------------------------------------------------------------------------------------------


def test_search_add_output_commit_and_file(tmp_path: Path) -> None:
    root = _init(tmp_path)
    before = _commit_count(root)

    result = runner.invoke(
        app, ["--why", "first database search of the review", "-C", str(root), *_SEARCH_ARGS]
    )

    assert result.exit_code == EXIT_OK
    assert result.output == "recorded search S-01-medline\n"
    assert _commit_count(root) == before + 1
    assert _head_message(root) == (
        "search-add(S-01-medline): record search S-01-medline\n"
        "\n"
        "first database search of the review\n"
        "\n"
        "Strata-Op: search-add\n"
        "Strata-Search: S-01-medline\n"
        "Strata-Actor: ethan\n"
        "\n"
    )
    assert _head_files(root) == ["protocol/searches/S-01-medline.yaml"]
    assert (root / "protocol" / "searches" / "S-01-medline.yaml").read_text(encoding="utf-8") == (
        "id: S-01-medline\n"
        "database: MEDLINE\n"
        "platform: Ovid\n"
        "executed: '2026-03-04'\n"
        "executed_by: ethan\n"
        "query: |-\n"
        "  1 exp Learning/\n"
        "limits: null\n"
        "hits: 4182\n"
        "export_files:\n"
        "- medline.ris\n"
        "peer_reviewed_by: null\n"
        "notes: null\n"
        "supersedes: null\n"
    )
    assert _status(root) == []


def test_search_add_without_query_records_pending_and_warns(tmp_path: Path) -> None:
    root = _init(tmp_path)

    result = runner.invoke(
        app,
        [
            "--why",
            "recorded before the query string is finalised",
            "-C",
            str(root),
            "search",
            "add",
            "--database",
            "PsycINFO",
            "--platform",
            "EBSCO",
            "--by",
            "ethan",
            "--executed",
            "2026-03-05",
        ],
    )

    assert result.exit_code == EXIT_OK
    assert _normalise(result.output, tmp_path) == (
        "warning: no query string recorded for S-01-psycinfo (PRISMA item 7) — supply it "
        "before the review is finalised recorded search S-01-psycinfo"
    )
    text = (root / "protocol" / "searches" / "S-01-psycinfo.yaml").read_text(encoding="utf-8")
    assert "query: |-\n  PENDING\n" in text
    assert _status(root) == []


def test_search_add_query_file_supplies_the_query(tmp_path: Path) -> None:
    root = _init(tmp_path)
    query_file = _write(tmp_path, "query.txt", "line one\nline two\n")

    result = runner.invoke(
        app,
        [
            "--why",
            "long strategy supplied from a file",
            "-C",
            str(root),
            "search",
            "add",
            "--database",
            "Embase",
            "--platform",
            "Ovid",
            "--by",
            "ethan",
            "--executed",
            "2026-03-06",
            "--query-file",
            str(query_file),
        ],
    )

    assert result.exit_code == EXIT_OK
    text = (root / "protocol" / "searches" / "S-01-embase.yaml").read_text(encoding="utf-8")
    # The query is stripped of its trailing newline, hence `|-`.
    assert "query: |-\n  line one\n  line two\n" in text


def test_search_add_no_commit_reports_and_leaves_the_file_untracked(tmp_path: Path) -> None:
    root = _init(tmp_path)
    before = _commit_count(root)

    result = runner.invoke(app, ["--no-commit", "-C", str(root), *_SEARCH_ARGS])

    assert result.exit_code == EXIT_OK
    assert result.output == "recorded search S-01-medline (not committed)\n"
    assert _commit_count(root) == before
    assert _status(root) == ["?? protocol/searches/S-01-medline.yaml"]


def test_search_add_numbers_searches_per_database_and_supersedes(tmp_path: Path) -> None:
    root = _init(tmp_path)
    _add_search(root)

    result = runner.invoke(
        app,
        [
            "--why",
            "re-run of the MEDLINE search before submission",
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
            "--executed",
            "2026-09-01",
            "--query",
            "1 exp Learning/",
            "--supersedes",
            "S-01-medline",
        ],
    )

    assert result.exit_code == EXIT_OK
    assert result.output == "recorded search S-02-medline\n"
    assert _head_files(root) == ["protocol/searches/S-02-medline.yaml"]
    assert "supersedes: S-01-medline\n" in (
        root / "protocol" / "searches" / "S-02-medline.yaml"
    ).read_text(encoding="utf-8")
    # The earlier search is untouched.
    assert "supersedes: null\n" in (root / "protocol" / "searches" / "S-01-medline.yaml").read_text(
        encoding="utf-8"
    )


@pytest.mark.parametrize(
    ("extra", "message"),
    [
        (["--id", "S-01-medline"], "error: a search 'S-01-medline' already exists"),
        (["--by", "nobody"], "error: executed_by 'nobody' is not a configured actor"),
        (["--supersedes", "S-99"], "error: supersedes references unknown search 'S-99'"),
    ],
)
def test_search_add_refusals_say_why_and_write_nothing(
    tmp_path: Path, extra: list[str], message: str
) -> None:
    root = _init(tmp_path)
    _add_search(root)
    before = _commit_count(root)

    result = runner.invoke(
        app,
        [
            "--why",
            "an attempt that should be refused",
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
            *extra,
        ],
    )

    assert result.exit_code == EXIT_USAGE
    assert result.output == message + "\n"
    assert _commit_count(root) == before
    assert _status(root) == []


def test_search_add_without_a_required_rationale_writes_nothing(tmp_path: Path) -> None:
    root = _init(tmp_path)
    before = _commit_count(root)

    result = runner.invoke(app, ["-C", str(root), *_SEARCH_ARGS])

    assert result.exit_code == EXIT_RATIONALE_REFUSED
    assert _commit_count(root) == before
    assert _status(root) == []


def test_search_add_with_rationale_not_required_commits_without_a_body(tmp_path: Path) -> None:
    root = _init(tmp_path)
    toggled = runner.invoke(
        app,
        ["--why", "turning rationale off for this test", "-C", str(root), "config"]
        + ["git.require_rationale", "false"],
    )
    assert toggled.exit_code == EXIT_OK, toggled.output
    gitio.add(root, ["strata.toml"])
    gitio.commit(root, "test: rationale off")

    result = runner.invoke(app, ["-C", str(root), *_SEARCH_ARGS])

    assert result.exit_code == EXIT_OK
    assert _head_message(root) == (
        "search-add(S-01-medline): record search S-01-medline\n"
        "\n"
        "Strata-Op: search-add\n"
        "Strata-Search: S-01-medline\n"
        "Strata-Actor: ethan\n"
        "\n"
    )


# ---------------------------------------------------------------------------------------------
# strata import
# ---------------------------------------------------------------------------------------------

# `derived/pool.tsv` is here since `strata verify` began holding the derived files to regeneration:
# an import used to commit the counts and leave the pool without the records it had just added.
_IMPORT_FILES = [
    "derived/counts.json",
    "derived/pool.tsv",
    "events/import/ethan.ndjson",
    "imports/<IMPORT>/manifest.yaml",
    "imports/<IMPORT>/raw/export.json",
    "records/records.ndjson",
]


def _import_args(root: Path, *files: Path, extra: list[str] | None = None) -> list[str]:
    return [
        "-C",
        str(root),
        "import",
        *[str(f) for f in files],
        "--by",
        "ethan",
        "--search",
        "S-01-medline",
        *(extra or []),
    ]


def test_import_output_commit_and_files(tmp_path: Path) -> None:
    root = _init(tmp_path)
    _add_search(root)
    export = _write(tmp_path, "export.json")
    before = _commit_count(root)

    result = runner.invoke(
        app, ["--why", "importing the first MEDLINE export", *_import_args(root, export)]
    )

    assert result.exit_code == EXIT_OK
    assert _normalise(result.output, tmp_path) == (
        "imported <TMP>/export.json as <IMPORT>: 2 new, 0 matched existing, 0 rejected"
    )
    assert _commit_count(root) == before + 1
    assert _head_message(root) == (
        "import(<IMPORT>): import export.json\n"
        "\n"
        "importing the first MEDLINE export\n"
        "\n"
        "Strata-Op: import\n"
        "Strata-Import: <IMPORT>\n"
        "Strata-Actor: ethan\n"
        "\n"
    )
    assert _head_files(root) == _IMPORT_FILES
    assert _status(root) == []
    # The raw file is stored unmodified.
    (raw,) = (root / "imports").glob("*/raw/export.json")
    assert raw.read_text(encoding="utf-8") == _TWO_PAPERS


def test_import_again_reports_already_imported_and_commits_nothing(tmp_path: Path) -> None:
    root = _init(tmp_path)
    _add_search(root)
    export = _write(tmp_path, "export.json")
    first = runner.invoke(app, ["--why", "the first import", *_import_args(root, export)])
    assert first.exit_code == EXIT_OK
    before = _commit_count(root)

    # No rationale given: nothing would be committed, so none is needed.
    again = runner.invoke(app, _import_args(root, export))

    assert again.exit_code == EXIT_OK
    assert _normalise(again.output, tmp_path) == (
        "already imported <TMP>/export.json as <IMPORT> — no changes made"
    )
    assert _commit_count(root) == before
    assert _status(root) == []


def test_import_json_shapes(tmp_path: Path) -> None:
    root = _init(tmp_path)
    _add_search(root)
    export = _write(tmp_path, "export.json")
    bad = _write(tmp_path, "export.xyz", "not a bibliography")

    created = runner.invoke(
        app, ["--why", "checking the json output", "--json", *_import_args(root, export)]
    )
    assert created.exit_code == EXIT_OK
    (entry,) = json.loads(created.output)
    assert sorted(entry) == [
        "already_imported",
        "column_mapping",
        "dry_run",
        "encoding",
        "existing_ids_appended",
        "file",
        "format",
        "import_id",
        "nondeterministic_rows",
        "records_created",
        "rejected",
        "rows_read",
        "rows_rejected",
    ]
    assert (entry["records_created"], entry["rows_rejected"], entry["format"]) == (
        2,
        0,
        "csl-json",
    )
    assert entry["file"] == str(export)

    mixed = runner.invoke(app, ["--json", *_import_args(root, export, bad, extra=["--dry-run"])])
    assert mixed.exit_code == EXIT_USAGE
    done, failed = json.loads(mixed.output)
    assert done["already_imported"] is True
    assert failed == {
        "file": str(bad),
        "error": "unsupported file extension '.xyz'; pass --format explicitly",
    }


def test_import_dry_run_reports_and_writes_nothing(tmp_path: Path) -> None:
    root = _init(tmp_path)
    _add_search(root)
    export = _write(tmp_path, "export.json")
    before = _commit_count(root)

    result = runner.invoke(app, _import_args(root, export, extra=["--dry-run"]))

    assert result.exit_code == EXIT_OK
    assert _normalise(result.output, tmp_path) == (
        "would import <TMP>/export.json as <IMPORT>: 2 new, 0 matched existing, 0 rejected"
    )
    assert _commit_count(root) == before
    assert _status(root) == []
    assert not (root / "imports").exists() or not list((root / "imports").iterdir())


def test_import_no_commit_leaves_exactly_the_import_uncommitted(tmp_path: Path) -> None:
    root = _init(tmp_path)
    _add_search(root)
    export = _write(tmp_path, "export.json")
    before = _commit_count(root)

    result = runner.invoke(app, ["--no-commit", *_import_args(root, export)])

    assert result.exit_code == EXIT_OK
    assert _normalise(result.output, tmp_path) == (
        "imported <TMP>/export.json as <IMPORT>: 2 new, 0 matched existing, 0 rejected"
    )
    assert _commit_count(root) == before
    assert _status(root) == [
        " M derived/counts.json",
        " M derived/pool.tsv",
        " M records/records.ndjson",
        "?? events/import/ethan.ndjson",
        "?? imports/<IMPORT>/manifest.yaml",
        "?? imports/<IMPORT>/raw/export.json",
    ]


def test_import_several_files_is_one_commit_each_and_a_failure_does_not_stop_the_rest(
    tmp_path: Path,
) -> None:
    root = _init(tmp_path)
    _add_search(root)
    first = _write(tmp_path, "a.json", '[{"title": "First paper", "DOI": "10.1000/aaa"}]')
    bad = _write(tmp_path, "b.xyz", "this is not a bibliography")
    third = _write(tmp_path, "c.json", '[{"title": "Third paper", "DOI": "10.1000/ccc"}]')
    before = _commit_count(root)

    result = runner.invoke(
        app, ["--why", "importing three files at once", *_import_args(root, first, bad, third)]
    )

    assert result.exit_code == EXIT_USAGE
    assert _normalise(result.output, tmp_path) == (
        "imported <TMP>/a.json as <IMPORT>: 1 new, 0 matched existing, 0 rejected "
        "error: <TMP>/b.xyz: unsupported file extension '.xyz'; pass --format explicitly "
        "imported <TMP>/c.json as <IMPORT>: 1 new, 0 matched existing, 0 rejected"
    )
    assert _commit_count(root) == before + 2
    subjects = [_IMPORT_ID.sub("<IMPORT>", s) for s in gitio.log(root, max_count=2, fmt="%s")]
    assert subjects == ["import(<IMPORT>): import c.json", "import(<IMPORT>): import a.json"]
    assert _status(root) == []


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (
            ["--search", "S-99"],
            "error: <TMP>/export.json: unknown search 'S-99'",
        ),
        (
            ["--via", "nonsense"],
            "error: <TMP>/export.json: invalid --via 'nonsense'; must be one of "
            "['citation-searching', 'contact', 'organisation', 'registry', 'website']",
        ),
    ],
)
def test_import_refusals_say_why_and_write_nothing(
    tmp_path: Path, args: list[str], message: str
) -> None:
    root = _init(tmp_path)
    _add_search(root)
    export = _write(tmp_path, "export.json")
    before = _commit_count(root)

    result = runner.invoke(
        app,
        ["--why", "an attempt that should be refused", "-C", str(root), "import", str(export)]
        + ["--by", "ethan", *args],
    )

    assert result.exit_code == EXIT_USAGE
    assert _normalise(result.output, tmp_path) == message
    assert _commit_count(root) == before
    assert _status(root) == []


def test_import_without_a_required_rationale_writes_nothing(tmp_path: Path) -> None:
    root = _init(tmp_path)
    _add_search(root)
    export = _write(tmp_path, "export.json")
    before = _commit_count(root)

    result = runner.invoke(app, _import_args(root, export))

    assert result.exit_code == EXIT_RATIONALE_REFUSED
    assert _commit_count(root) == before
    assert _status(root) == []


def test_import_via_counts_as_another_method_and_has_no_search_trailer(tmp_path: Path) -> None:
    root = _init(tmp_path)
    export = _write(tmp_path, "export.json")

    result = runner.invoke(
        app,
        ["--why", "results found by citation chasing", "-C", str(root), "import", str(export)]
        + ["--by", "ethan", "--via", "citation-searching"],
    )

    assert result.exit_code == EXIT_OK
    assert _head_message(root) == (
        "import(<IMPORT>): import export.json\n"
        "\n"
        "results found by citation chasing\n"
        "\n"
        "Strata-Op: import\n"
        "Strata-Import: <IMPORT>\n"
        "Strata-Actor: ethan\n"
        "\n"
    )
    assert _head_files(root) == _IMPORT_FILES
