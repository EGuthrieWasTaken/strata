import json
from pathlib import Path

from typer.testing import CliRunner

from strata.cli.main import EXIT_OK, EXIT_USAGE, app

runner = CliRunner()

_CSL_ONE_RECORD = """\
[
  {
    "id": "1",
    "type": "article-journal",
    "title": "A single test record",
    "author": [{"family": "Smith", "given": "Jo"}],
    "issued": {"date-parts": [[2010]]},
    "container-title": "Journal of Testing",
    "DOI": "10.1234/single.record",
    "abstract": "An abstract for the single test record."
  }
]
"""


def _init(tmp_path: Path, name: str = "review") -> Path:
    root = tmp_path / name
    result = runner.invoke(
        app,
        ["init", str(root), "--title", "Test Review", "--actor", "ethan", "--actor-name", "Ethan"],
    )
    assert result.exit_code == EXIT_OK, result.output
    return root


def _import(root: Path, tmp_path: Path, name: str, content: str) -> None:
    export = tmp_path / name
    export.write_text(content, encoding="utf-8")
    result = runner.invoke(
        app,
        [
            "--why",
            f"importing {name}",
            "-C",
            str(root),
            "import",
            str(export),
            "--by",
            "ethan",
            "--via",
            "registry",
        ],
    )
    assert result.exit_code == EXIT_OK, result.output


def test_audit_requires_criteria_flag(tmp_path: Path) -> None:
    root = _init(tmp_path)
    result = runner.invoke(app, ["-C", str(root), "audit"])
    assert result.exit_code == EXIT_USAGE, result.output


def test_audit_reports_no_exclusions_yet(tmp_path: Path) -> None:
    root = _init(tmp_path)
    result = runner.invoke(app, ["-C", str(root), "audit", "--criteria"])
    assert result.exit_code == EXIT_OK, result.output
    assert "no exclusion decisions" in result.output


def test_audit_samples_and_reports_criterion(tmp_path: Path) -> None:
    root = _init(tmp_path)
    _import(root, tmp_path, "one.json", _CSL_ONE_RECORD)
    runner.invoke(
        app,
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
            "Not empirical",
            "--definition",
            "Not an empirical study.",
            "--applies-at",
            "title-abstract",
            "--by",
            "ethan",
            "--id",
            "EXC-01",
        ],
    )
    runner.invoke(
        app,
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
        input="e\n1\nnot empirical\n",
    )

    result = runner.invoke(app, ["-C", str(root), "audit", "--criteria", "--seed", "1"])
    assert result.exit_code == EXIT_OK, result.output
    assert "EXC-01" in result.output
    assert "A single test record" in result.output


def test_audit_json_output(tmp_path: Path) -> None:
    root = _init(tmp_path)
    _import(root, tmp_path, "one.json", _CSL_ONE_RECORD)
    runner.invoke(
        app,
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
            "Not empirical",
            "--definition",
            "Not an empirical study.",
            "--applies-at",
            "title-abstract",
            "--by",
            "ethan",
            "--id",
            "EXC-01",
        ],
    )
    runner.invoke(
        app,
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
        input="e\n1\n\n",
    )

    result = runner.invoke(app, ["-C", str(root), "--json", "audit", "--criteria", "--seed", "1"])
    assert result.exit_code == EXIT_OK, result.output
    payload = json.loads(result.stdout)
    assert payload["seed"] == 1
    assert len(payload["items"]) == 1
    assert payload["items"][0]["criteria"] == ["EXC-01"]
