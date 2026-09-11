from pathlib import Path

from typer.testing import CliRunner

from strata.cli.main import EXIT_NOT_REPO, EXIT_OK, EXIT_USAGE, app

runner = CliRunner()


def _init(tmp_path: Path) -> Path:
    root = tmp_path / "review"
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
            "--actor-email",
            "ethan@example.edu",
        ],
    )
    assert result.exit_code == EXIT_OK, result.output
    return root


def test_init_creates_expected_layout(tmp_path: Path) -> None:
    root = _init(tmp_path)
    for rel in [
        "strata.toml",
        ".gitattributes",
        ".gitignore",
        ".strata/schema-version",
        ".strata/hooks/pre-commit",
        "records/records.ndjson",
        "records/aliases.ndjson",
        "protocol/criteria.yaml",
        "derived/pool.tsv",
    ]:
        assert (root / rel).exists(), rel
    assert (root / ".git").is_dir()


def test_init_requires_title_non_interactively(tmp_path: Path) -> None:
    result = runner.invoke(app, ["init", str(tmp_path / "review"), "--actor", "ethan"])
    assert result.exit_code == EXIT_USAGE


def test_init_refuses_nonempty_directory(tmp_path: Path) -> None:
    root = tmp_path / "review"
    root.mkdir()
    (root / "existing.txt").write_text("hi", encoding="utf-8")
    result = runner.invoke(
        app, ["init", str(root), "--title", "T", "--actor", "ethan", "--actor-name", "E"]
    )
    assert result.exit_code != EXIT_OK


def test_verify_passes_on_freshly_initialised_repo(tmp_path: Path) -> None:
    root = _init(tmp_path)
    result = runner.invoke(app, ["-C", str(root), "verify"])
    assert result.exit_code == EXIT_OK, result.output


def test_status_reports_project_title(tmp_path: Path) -> None:
    root = _init(tmp_path)
    result = runner.invoke(app, ["-C", str(root), "status"])
    assert result.exit_code == EXIT_OK
    assert "Test Review" in result.output


def test_doctor_reports_healthy_after_init(tmp_path: Path) -> None:
    root = _init(tmp_path)
    result = runner.invoke(app, ["-C", str(root), "doctor"])
    assert result.exit_code == EXIT_OK, result.output


def test_commands_fail_outside_a_repo(tmp_path: Path) -> None:
    result = runner.invoke(app, ["-C", str(tmp_path), "status"])
    assert result.exit_code == EXIT_NOT_REPO


def test_config_get_and_set(tmp_path: Path) -> None:
    root = _init(tmp_path)
    get_result = runner.invoke(app, ["-C", str(root), "config", "screening.mode"])
    assert get_result.exit_code == EXIT_OK
    assert "dual" in get_result.output

    set_result = runner.invoke(app, ["-C", str(root), "config", "screening.mode", "single"])
    assert set_result.exit_code == EXIT_OK

    reread = runner.invoke(app, ["-C", str(root), "config", "screening.mode"])
    assert "single" in reread.output


def test_actor_add_list_deactivate(tmp_path: Path) -> None:
    root = _init(tmp_path)
    add_result = runner.invoke(
        app, ["-C", str(root), "actor", "add", "sam", "Sam Okonkwo", "--role", "screener"]
    )
    assert add_result.exit_code == EXIT_OK, add_result.output

    list_result = runner.invoke(app, ["-C", str(root), "actor", "list"])
    assert "sam" in list_result.output

    dup_result = runner.invoke(app, ["-C", str(root), "actor", "add", "sam", "Sam Again"])
    assert dup_result.exit_code == EXIT_USAGE

    deactivate_result = runner.invoke(app, ["-C", str(root), "actor", "deactivate", "sam"])
    assert deactivate_result.exit_code == EXIT_OK

    list_after = runner.invoke(app, ["-C", str(root), "actor", "list"])
    assert "inactive" in list_after.output
