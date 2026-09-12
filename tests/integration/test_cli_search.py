import json
from pathlib import Path

from typer.testing import CliRunner

from strata import gitio
from strata.cli.main import EXIT_OK, EXIT_RATIONALE_REFUSED, EXIT_USAGE, app

runner = CliRunner()


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


def test_search_add_requires_rationale_non_interactively(tmp_path: Path) -> None:
    root = _init(tmp_path)
    result = runner.invoke(
        app,
        [
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
            "1 exp Learning/",
        ],
    )
    assert result.exit_code == EXIT_RATIONALE_REFUSED, result.output
    # The record is written before the commit is attempted, but nothing is
    # staged/committed without a rationale -- the tree is left dirty.
    assert gitio.is_dirty(root)


def test_search_add_with_why_commits_with_trailers(tmp_path: Path) -> None:
    root = _init(tmp_path)
    result = runner.invoke(
        app,
        [
            "--why",
            "first database search of the review",
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
            "2026-03-04",
            "--query",
            "1 exp Learning/",
            "--hits",
            "4182",
        ],
    )
    assert result.exit_code == EXIT_OK, result.output
    assert not gitio.is_dirty(root)

    message = gitio.run(["log", "-1", "--format=%B"], cwd=root).stdout
    assert "Strata-Op: search-add" in message
    assert "Strata-Search: S-01-medline" in message
    assert "Strata-Actor: ethan" in message
    assert "first database search of the review" in message

    search_file = root / "protocol" / "searches" / "S-01-medline.yaml"
    assert search_file.exists()
    assert "query: |" in search_file.read_text(encoding="utf-8")


def test_search_add_rejects_short_rationale(tmp_path: Path) -> None:
    root = _init(tmp_path)
    result = runner.invoke(
        app,
        [
            "--why",
            "wip",
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
    assert result.exit_code == EXIT_RATIONALE_REFUSED, result.output


def test_search_add_no_commit_flag_skips_commit(tmp_path: Path) -> None:
    root = _init(tmp_path)
    result = runner.invoke(
        app,
        [
            "--no-commit",
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
    assert gitio.is_dirty(root)


def test_search_add_without_query_warns_and_records_pending(tmp_path: Path) -> None:
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
        ],
    )
    assert result.exit_code == EXIT_OK, result.output
    assert "no query string recorded" in result.output


def test_search_add_prompts_for_rationale_interactively(tmp_path, monkeypatch) -> None:
    # Same technique as test_init_prompts_interactively_when_flags_omitted in
    # test_cli_more.py: CliRunner.invoke() swaps in its own sys.stdin, so the
    # module's `sys` binding itself must be replaced to survive that swap.
    class _FakeStdin:
        def isatty(self) -> bool:
            return True

    class _FakeSys:
        stdin = _FakeStdin()

    root = _init(tmp_path)
    monkeypatch.setattr("strata.cli.main.sys", _FakeSys())
    monkeypatch.setattr(
        "strata.cli.main.typer.prompt", lambda *a, **kw: "an interactively supplied rationale"
    )
    result = runner.invoke(
        app,
        [
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
    message = gitio.run(["log", "-1", "--format=%B"], cwd=root).stdout
    assert "an interactively supplied rationale" in message


def test_search_add_reads_rationale_from_why_file(tmp_path: Path) -> None:
    root = _init(tmp_path)
    why_file = tmp_path / "rationale.txt"
    why_file.write_text("a rationale supplied via --why-file", encoding="utf-8")
    result = runner.invoke(
        app,
        [
            "--why-file",
            str(why_file),
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
    message = gitio.run(["log", "-1", "--format=%B"], cwd=root).stdout
    assert "a rationale supplied via --why-file" in message


def test_search_add_skips_rationale_when_not_required(tmp_path: Path) -> None:
    root = _init(tmp_path)
    config_result = runner.invoke(
        app, ["-C", str(root), "config", "git.require_rationale", "false"]
    )
    assert config_result.exit_code == EXIT_OK, config_result.output
    gitio.add_all(root)
    gitio.commit(root, "chore: disable rationale requirement for this test\n")
    result = runner.invoke(
        app,
        [
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
    assert not gitio.is_dirty(root)


def test_search_add_reads_query_from_file(tmp_path: Path) -> None:
    root = _init(tmp_path)
    query_file = tmp_path / "query.txt"
    query_file.write_text("1 exp Learning/\n2 1 and spaced\n", encoding="utf-8")
    result = runner.invoke(
        app,
        [
            "--why",
            "query supplied via a file this time",
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
            "--query-file",
            str(query_file),
        ],
    )
    assert result.exit_code == EXIT_OK, result.output
    search_file = root / "protocol" / "searches" / "S-01-medline.yaml"
    assert "1 exp Learning/" in search_file.read_text(encoding="utf-8")


def test_search_add_rejects_unknown_actor(tmp_path: Path) -> None:
    root = _init(tmp_path)
    result = runner.invoke(
        app,
        [
            "-C",
            str(root),
            "search",
            "add",
            "--database",
            "MEDLINE",
            "--platform",
            "Ovid",
            "--by",
            "nobody",
            "--query",
            "q",
        ],
    )
    assert result.exit_code == EXIT_USAGE, result.output


def test_search_list_empty_and_populated(tmp_path: Path) -> None:
    root = _init(tmp_path)
    empty = runner.invoke(app, ["-C", str(root), "search", "list"])
    assert empty.exit_code == EXIT_OK
    assert "no searches recorded" in empty.output

    add_result = runner.invoke(
        app,
        [
            "--why",
            "initial MEDLINE search",
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
            "--hits",
            "100",
        ],
    )
    assert add_result.exit_code == EXIT_OK, add_result.output

    listed = runner.invoke(app, ["-C", str(root), "search", "list"])
    assert listed.exit_code == EXIT_OK
    assert "S-01-medline" in listed.output
    assert "100 hits" in listed.output

    listed_json = runner.invoke(app, ["--json", "-C", str(root), "search", "list"])
    payload = json.loads(listed_json.output)
    assert payload[0]["id"] == "S-01-medline"


def test_status_reports_pending_search_warning(tmp_path: Path) -> None:
    root = _init(tmp_path)
    add_result = runner.invoke(
        app,
        [
            "--no-commit",
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
        ],
    )
    assert add_result.exit_code == EXIT_OK, add_result.output

    status_result = runner.invoke(app, ["-C", str(root), "status"])
    assert status_result.exit_code == EXIT_OK
    assert "has no query string recorded" in status_result.output
    assert "PRISMA item 7" in status_result.output

    status_json = runner.invoke(app, ["--json", "-C", str(root), "status"])
    payload = json.loads(status_json.output)
    assert payload["search_count"] == 1
    assert payload["pending_searches"] == ["S-01-psycinfo"]
