import json
from pathlib import Path

from typer.testing import CliRunner

from strata.cli.main import EXIT_GUARDRAIL, EXIT_OK, app
from strata.core.records import read_records
from strata.core.repo import open_repo
from strata.core.verify import verify_repository
from strata.protocol.screening import resolve_record_state

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


def _add_actor(root: Path, handle: str = "sam", role: str = "screener") -> None:
    result = runner.invoke(
        app, ["-C", str(root), "actor", "add", handle, handle.title(), "--role", role]
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


def _make_conflict(root: Path, tmp_path: Path) -> None:
    _add_actor(root)
    _import(root, tmp_path, "one.json", _CSL_ONE_RECORD)
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
        input="i\n\n",
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
            "sam",
        ],
        input="m\n\n",
    )


def test_adjudicate_no_conflicts(tmp_path: Path) -> None:
    root = _init(tmp_path)
    result = runner.invoke(app, ["-C", str(root), "adjudicate", "--by", "ethan"])
    assert result.exit_code == EXIT_OK, result.output
    assert "no conflicts" in result.output


def test_adjudicate_requires_authorization(tmp_path: Path) -> None:
    root = _init(tmp_path)
    _make_conflict(root, tmp_path)
    result = runner.invoke(app, ["-C", str(root), "adjudicate", "--by", "sam"])
    assert result.exit_code == EXIT_GUARDRAIL, result.output


def test_adjudicate_include_resolves_conflict_and_commits(tmp_path: Path) -> None:
    root = _init(tmp_path)
    _make_conflict(root, tmp_path)

    result = runner.invoke(
        app,
        [
            "--why",
            "Adjudicating this conflict in favour of inclusion.",
            "-C",
            str(root),
            "adjudicate",
            "--by",
            "ethan",
        ],
        input="i\n",
    )
    assert result.exit_code == EXIT_OK, result.output

    repo = open_repo(root)

    (record_id,) = [r["id"] for r in read_records(repo)]
    state = resolve_record_state(repo, "title-abstract", record_id)
    assert state.status == "include"
    assert state.adjudication is not None

    report = verify_repository(repo)
    assert report.ok, report.issues


def test_adjudicate_discuss_leaves_conflict_open(tmp_path: Path) -> None:
    root = _init(tmp_path)
    _make_conflict(root, tmp_path)

    result = runner.invoke(
        app,
        ["-C", str(root), "adjudicate", "--by", "ethan"],
        input="d\nLet's discuss at the Tuesday meeting.\n",
    )
    assert result.exit_code == EXIT_OK, result.output

    repo = open_repo(root)

    (record_id,) = [r["id"] for r in read_records(repo)]
    state = resolve_record_state(repo, "title-abstract", record_id)
    assert state.status == "conflict"


def test_adjudicate_json_output(tmp_path: Path) -> None:
    root = _init(tmp_path)
    _make_conflict(root, tmp_path)

    result = runner.invoke(
        app,
        [
            "--why",
            "Adjudicating this conflict in favour of inclusion.",
            "--json",
            "-C",
            str(root),
            "adjudicate",
            "--by",
            "ethan",
        ],
        input="i\n",
    )
    assert result.exit_code == EXIT_OK, result.output
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload == {"decided": 1}
