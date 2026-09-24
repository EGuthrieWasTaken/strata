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


def _add_actor(root: Path, handle: str = "sam") -> None:
    result = runner.invoke(
        app, ["-C", str(root), "actor", "add", handle, handle.title(), "--role", "screener"]
    )
    assert result.exit_code == EXIT_OK, result.output


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


def test_irr_reports_no_pairs_before_any_screening(tmp_path: Path) -> None:
    root = _init(tmp_path)
    result = runner.invoke(app, ["-C", str(root), "irr"])
    assert result.exit_code == EXIT_OK, result.output
    assert "no reviewer pairs" in result.output


def test_irr_computes_and_writes_derived_file(tmp_path: Path) -> None:
    root = _init(tmp_path)
    _add_actor(root)
    _import(root, tmp_path, "one.json", _CSL_ONE_RECORD)
    for actor in ("ethan", "sam"):
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
                actor,
            ],
            input="i\n\n",
        )

    result = runner.invoke(app, ["-C", str(root), "irr"])
    assert result.exit_code == EXIT_OK, result.output
    assert "ethan x sam" in result.output
    assert "kappa=1.00" in result.output

    irr_json = (root / "derived" / "irr.json").read_text(encoding="utf-8")
    payload = json.loads(irr_json)
    assert payload["title-abstract"][0]["n"] == 1


def test_irr_json_output(tmp_path: Path) -> None:
    root = _init(tmp_path)
    _add_actor(root)
    _import(root, tmp_path, "one.json", _CSL_ONE_RECORD)
    for actor in ("ethan", "sam"):
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
                actor,
            ],
            input="i\n\n",
        )

    result = runner.invoke(app, ["-C", str(root), "--json", "irr"])
    assert result.exit_code == EXIT_OK, result.output
    payload = json.loads(result.stdout)
    assert len(payload) == 1
    assert payload[0]["actor_a"] == "ethan"
    assert payload[0]["actor_b"] == "sam"
    assert payload[0]["kappa"] == 1.0


def test_irr_unknown_stage_is_usage_error(tmp_path: Path) -> None:
    root = _init(tmp_path)
    result = runner.invoke(app, ["-C", str(root), "irr", "--stage", "bogus-stage"])
    assert result.exit_code == EXIT_USAGE, result.output
