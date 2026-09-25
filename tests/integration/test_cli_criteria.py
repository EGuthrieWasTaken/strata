import json
from pathlib import Path

from typer.testing import CliRunner, Result

from strata.cli.main import EXIT_OK, EXIT_RATIONALE_REFUSED, EXIT_USAGE, app
from strata.core.repo import open_repo
from strata.core.verify import verify_repository
from strata.protocol.criteria import read_criteria_doc

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


def _add(root: Path, **kwargs: str) -> Result:
    args = [
        "-C",
        str(root),
        "--why",
        "Establishing the initial protocol criteria for this review.",
        "criteria",
        "add",
        "--kind",
        kwargs.get("kind", "exclusion"),
        "--label",
        kwargs.get("label", "Not empirical"),
        "--definition",
        kwargs.get("definition", "Not an empirical study."),
        "--applies-at",
        kwargs.get("applies_at", "title-abstract"),
        "--by",
        "ethan",
    ]
    if "criterion_id" in kwargs:
        args += ["--id", str(kwargs["criterion_id"])]
    return runner.invoke(app, args)


def test_criteria_add_commits_and_persists(tmp_path: Path) -> None:
    root = _init(tmp_path)
    result = _add(root, criterion_id="EXC-01")
    assert result.exit_code == EXIT_OK, result.output
    repo = open_repo(root)
    doc = read_criteria_doc(repo)
    assert doc["version"] == 1
    assert doc["criteria"][0]["id"] == "EXC-01"

    report = verify_repository(repo)
    assert report.ok, report.issues


def test_criteria_add_without_rationale_is_refused(tmp_path: Path) -> None:
    root = _init(tmp_path)
    result = runner.invoke(
        app,
        [
            "-C",
            str(root),
            "criteria",
            "add",
            "--kind",
            "exclusion",
            "--label",
            "Not empirical",
            "--definition",
            "Not an empirical study.",
            "--applies-at",
            "title-abstract",
            "--by",
            "ethan",
        ],
    )
    assert result.exit_code == EXIT_RATIONALE_REFUSED, result.output
    repo = open_repo(root)
    assert read_criteria_doc(repo)["version"] == 0


def test_criteria_add_bad_kind_is_usage_error(tmp_path: Path) -> None:
    root = _init(tmp_path)
    result = _add(root, kind="bogus")
    assert result.exit_code == EXIT_USAGE, result.output


def test_criteria_add_json_output(tmp_path: Path) -> None:
    root = _init(tmp_path)
    result = runner.invoke(
        app,
        [
            "-C",
            str(root),
            "--json",
            "--why",
            "Establishing the initial protocol criteria for this review.",
            "criteria",
            "add",
            "--kind",
            "inclusion",
            "--label",
            "Empirical",
            "--definition",
            "Original empirical data.",
            "--applies-at",
            "title-abstract",
            "--by",
            "ethan",
        ],
    )
    assert result.exit_code == EXIT_OK, result.output
    payload = json.loads(result.stdout)
    assert payload["id"] == "INC-01"


def test_criteria_edit_requires_direction(tmp_path: Path) -> None:
    root = _init(tmp_path)
    _add(root, criterion_id="EXC-03", label="Not in English", definition="Not in English.")
    result = runner.invoke(
        app,
        [
            "-C",
            str(root),
            "criteria",
            "edit",
            "EXC-03",
        ],
    )
    assert result.exit_code != EXIT_OK


def test_criteria_edit_editorial_guard_refuses_meaning_change(tmp_path: Path) -> None:
    root = _init(tmp_path)
    _add(root, criterion_id="EXC-03", label="Not in English", definition="Not in English.")
    result = runner.invoke(
        app,
        [
            "-C",
            str(root),
            "--why",
            "Trying to sneak a meaning change past as editorial.",
            "criteria",
            "edit",
            "EXC-03",
            "--direction",
            "editorial",
            "--definition",
            "Not in English or French.",
            "--by",
            "ethan",
        ],
    )
    assert result.exit_code == EXIT_USAGE, result.output
    assert "editorial" in result.output


def test_criteria_edit_tightened_bumps_version(tmp_path: Path) -> None:
    root = _init(tmp_path)
    _add(root, criterion_id="EXC-03", label="Not in English", definition="Not in English.")
    result = runner.invoke(
        app,
        [
            "-C",
            str(root),
            "--why",
            "Narrowing the language criterion after pilot screening.",
            "criteria",
            "edit",
            "EXC-03",
            "--direction",
            "tightened",
            "--definition",
            "Not in English, translations included too.",
            "--by",
            "ethan",
        ],
    )
    assert result.exit_code == EXIT_OK, result.output
    repo = open_repo(root)
    assert read_criteria_doc(repo)["version"] == 2


def test_criteria_retire_marks_retired(tmp_path: Path) -> None:
    root = _init(tmp_path)
    _add(root, criterion_id="EXC-01")
    result = runner.invoke(
        app,
        [
            "-C",
            str(root),
            "--why",
            "This criterion is no longer relevant to the review.",
            "criteria",
            "retire",
            "EXC-01",
            "--by",
            "ethan",
        ],
    )
    assert result.exit_code == EXIT_OK, result.output
    repo = open_repo(root)
    doc = read_criteria_doc(repo)
    assert doc["criteria"][0]["status"] == "retired"
    report = verify_repository(repo)
    assert report.ok, report.issues


def test_criteria_list_and_diff(tmp_path: Path) -> None:
    root = _init(tmp_path)
    _add(root, criterion_id="EXC-01", label="First", definition="First definition.")
    runner.invoke(
        app,
        [
            "-C",
            str(root),
            "--why",
            "Relaxing this criterion after a protocol review.",
            "criteria",
            "edit",
            "EXC-01",
            "--direction",
            "loosened",
            "--definition",
            "First definition, relaxed.",
            "--by",
            "ethan",
        ],
    )

    list_result = runner.invoke(app, ["-C", str(root), "--json", "criteria", "list"])
    assert list_result.exit_code == EXIT_OK, list_result.output
    listed = json.loads(list_result.stdout)
    assert listed[0]["id"] == "EXC-01"

    diff_result = runner.invoke(app, ["-C", str(root), "--json", "criteria", "diff", "0", "2"])
    assert diff_result.exit_code == EXIT_OK, diff_result.output
    deltas = json.loads(diff_result.stdout)
    assert [d["origin"] for d in deltas] == ["added", "edited"]


def test_criteria_diff_rejects_bad_range(tmp_path: Path) -> None:
    root = _init(tmp_path)
    result = runner.invoke(app, ["-C", str(root), "criteria", "diff", "5", "1"])
    assert result.exit_code == EXIT_USAGE, result.output


def test_criteria_edit_json_output(tmp_path: Path) -> None:
    root = _init(tmp_path)
    _add(root, criterion_id="EXC-01")
    result = runner.invoke(
        app,
        [
            "-C",
            str(root),
            "--json",
            "--why",
            "Relaxing this criterion after a protocol review.",
            "criteria",
            "edit",
            "EXC-01",
            "--direction",
            "loosened",
            "--definition",
            "Not an empirical study, relaxed.",
            "--by",
            "ethan",
        ],
    )
    assert result.exit_code == EXIT_OK, result.output
    payload = json.loads(result.stdout)
    assert payload["id"] == "EXC-01"


def test_criteria_retire_reports_error_for_unknown_id(tmp_path: Path) -> None:
    root = _init(tmp_path)
    result = runner.invoke(
        app,
        [
            "-C",
            str(root),
            "--why",
            "Testing retirement of an unknown criterion id.",
            "criteria",
            "retire",
            "EXC-99",
            "--by",
            "ethan",
        ],
    )
    assert result.exit_code == EXIT_USAGE, result.output


def test_criteria_retire_json_output(tmp_path: Path) -> None:
    root = _init(tmp_path)
    _add(root, criterion_id="EXC-01")
    result = runner.invoke(
        app,
        [
            "-C",
            str(root),
            "--json",
            "--why",
            "This criterion is no longer relevant to the review.",
            "criteria",
            "retire",
            "EXC-01",
            "--by",
            "ethan",
        ],
    )
    assert result.exit_code == EXIT_OK, result.output
    payload = json.loads(result.stdout)
    assert payload == {"id": "EXC-01", "status": "retired"}


def test_criteria_list_plain_text_output(tmp_path: Path) -> None:
    root = _init(tmp_path)
    empty_result = runner.invoke(app, ["-C", str(root), "criteria", "list"])
    assert empty_result.exit_code == EXIT_OK, empty_result.output
    assert "criteria add" in empty_result.output

    _add(root, criterion_id="EXC-01", label="First criterion")
    result = runner.invoke(app, ["-C", str(root), "criteria", "list"])
    assert result.exit_code == EXIT_OK, result.output
    assert "EXC-01" in result.output
    assert "First criterion" in result.output

    result = runner.invoke(
        app,
        [
            "-C",
            str(root),
            "--why",
            "This criterion is no longer relevant to the review.",
            "criteria",
            "retire",
            "EXC-01",
            "--by",
            "ethan",
        ],
    )
    assert result.exit_code == EXIT_OK, result.output
    retired_listing = runner.invoke(app, ["-C", str(root), "criteria", "list"])
    assert "(retired)" in retired_listing.output


def test_criteria_diff_plain_text_output(tmp_path: Path) -> None:
    root = _init(tmp_path)
    empty_diff = runner.invoke(app, ["-C", str(root), "criteria", "diff", "0", "1"])
    assert empty_diff.exit_code == EXIT_OK, empty_diff.output
    assert "no criteria changes" in empty_diff.output

    _add(root, criterion_id="EXC-01", label="First criterion")
    result = runner.invoke(app, ["-C", str(root), "criteria", "diff", "0", "1"])
    assert result.exit_code == EXIT_OK, result.output
    assert "EXC-01" in result.output
    assert "added" in result.output
