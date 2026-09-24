import json
from pathlib import Path

from typer.testing import CliRunner

from strata.cli.main import EXIT_OK, EXIT_USAGE, app
from strata.core.repo import open_repo
from strata.core.verify import verify_repository

runner = CliRunner()

_CSL_TWO_RECORDS = """\
[
  {
    "id": "1",
    "type": "article-journal",
    "title": "Spacing effects in learning",
    "author": [{"family": "Cepeda", "given": "Nicholas"}],
    "issued": {"date-parts": [[2008]]},
    "container-title": "Psychological Science",
    "DOI": "10.1111/j.1467-9280.2008.02209.x",
    "abstract": "We tested spacing effects on retention."
  },
  {
    "id": "2",
    "type": "article-journal",
    "title": "Retrieval practice and the testing effect",
    "author": [{"family": "Larsen", "given": "Douglas"}],
    "issued": {"date-parts": [[2009]]},
    "container-title": "Medical Education",
    "DOI": "10.1111/j.1365-2923.2009.03340.x",
    "abstract": "We tested retrieval practice in medical students."
  }
]
"""

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
        app,
        [
            "--why",
            f"{handle.title()} is joining the review team.",
            "-C",
            str(root),
            "actor",
            "add",
            handle,
            handle.title(),
            "--role",
            role,
        ],
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


def _add_criterion(root: Path, criterion_id: str = "EXC-01") -> None:
    result = runner.invoke(
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
            "title-abstract,full-text",
            "--by",
            "ethan",
            "--id",
            criterion_id,
        ],
    )
    assert result.exit_code == EXIT_OK, result.output


def test_screen_include_records_decision_and_commits(tmp_path: Path) -> None:
    root = _init(tmp_path)
    _add_actor(root)
    _import(root, tmp_path, "one.json", _CSL_ONE_RECORD)

    result = runner.invoke(
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
    assert result.exit_code == EXIT_OK, result.output
    assert "1 decision" in result.output or "done" in result.output

    repo = open_repo(root)
    report = verify_repository(repo)
    assert report.ok, report.issues


def test_screen_exclude_requires_criterion_and_records_note(tmp_path: Path) -> None:
    root = _init(tmp_path)
    _add_actor(root)
    _import(root, tmp_path, "one.json", _CSL_ONE_RECORD)
    _add_criterion(root)

    result = runner.invoke(
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
    assert result.exit_code == EXIT_OK, result.output

    repo = open_repo(root)
    from strata.protocol.screening import all_screen_events

    events = all_screen_events(repo, "title-abstract")
    assert len(events) == 1
    assert events[0]["body"]["decision"] == "exclude"
    assert events[0]["body"]["criteria"] == ["EXC-01"]
    assert events[0]["body"]["note"] == "not empirical"


def test_screen_skip_then_include_advances_queue(tmp_path: Path) -> None:
    root = _init(tmp_path)
    _add_actor(root)
    _import(root, tmp_path, "two.json", _CSL_TWO_RECORDS)

    result = runner.invoke(
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
        input="s\ni\n\n",
    )
    assert result.exit_code == EXIT_OK, result.output

    repo = open_repo(root)
    from strata.protocol.screening import all_screen_events

    events = all_screen_events(repo, "title-abstract")
    assert len(events) == 1


def test_screen_nothing_to_screen_when_queue_empty(tmp_path: Path) -> None:
    root = _init(tmp_path)
    _add_actor(root)
    result = runner.invoke(app, ["-C", str(root), "screen", "title-abstract", "--by", "ethan"])
    assert result.exit_code == EXIT_OK, result.output
    assert "nothing to screen" in result.output


def test_screen_json_output_for_interactive_summary(tmp_path: Path) -> None:
    root = _init(tmp_path)
    _add_actor(root)
    _import(root, tmp_path, "one.json", _CSL_ONE_RECORD)

    result = runner.invoke(
        app,
        [
            "--why",
            "Screening the pilot batch for the review.",
            "--json",
            "-C",
            str(root),
            "screen",
            "title-abstract",
            "--by",
            "ethan",
        ],
        input="i\n\n",
    )
    assert result.exit_code == EXIT_OK, result.output
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload == {"stage": "title-abstract", "decided": 1}


def test_screen_limit_caps_queue_size(tmp_path: Path) -> None:
    root = _init(tmp_path)
    _add_actor(root)
    _import(root, tmp_path, "two.json", _CSL_TWO_RECORDS)

    result = runner.invoke(
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
            "--limit",
            "1",
        ],
        input="i\n\n",
    )
    assert result.exit_code == EXIT_OK, result.output

    repo = open_repo(root)
    from strata.protocol.screening import all_screen_events

    events = all_screen_events(repo, "title-abstract")
    assert len(events) == 1


def test_screen_decisions_file_bulk_import(tmp_path: Path) -> None:
    root = _init(tmp_path)
    _add_actor(root)
    _import(root, tmp_path, "two.json", _CSL_TWO_RECORDS)

    repo = open_repo(root)
    from strata.core.records import read_records

    ids = sorted(r["id"] for r in read_records(repo))
    decisions_path = tmp_path / "decisions.tsv"
    decisions_path.write_text(
        "record_id\tdecision\tcriteria\tnote\n"
        + f"{ids[0]}\tinclude\t\t\n"
        + f"{ids[1]}\tinclude\t\t\n",
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        [
            "--why",
            "Imported screening decisions from the pilot spreadsheet.",
            "-C",
            str(root),
            "screen",
            "title-abstract",
            "--by",
            "ethan",
            "--decisions",
            str(decisions_path),
        ],
    )
    assert result.exit_code == EXIT_OK, result.output

    from strata.protocol.screening import all_screen_events

    events = all_screen_events(repo, "title-abstract")
    assert len(events) == 2
    assert all(e["body"]["imported"] is True for e in events)


def test_screen_decisions_file_json_output(tmp_path: Path) -> None:
    root = _init(tmp_path)
    _add_actor(root)
    _import(root, tmp_path, "one.json", _CSL_ONE_RECORD)
    repo = open_repo(root)
    from strata.core.records import read_records

    (record_id,) = [r["id"] for r in read_records(repo)]
    decisions_path = tmp_path / "decisions.tsv"
    decisions_path.write_text(
        f"record_id\tdecision\tcriteria\tnote\n{record_id}\tinclude\t\t\n", encoding="utf-8"
    )
    result = runner.invoke(
        app,
        [
            "--why",
            "Imported screening decisions from the pilot spreadsheet.",
            "--json",
            "-C",
            str(root),
            "screen",
            "title-abstract",
            "--by",
            "ethan",
            "--decisions",
            str(decisions_path),
        ],
    )
    assert result.exit_code == EXIT_OK, result.output
    payload = json.loads(result.stdout.strip().splitlines()[0])
    assert payload == {"stage": "title-abstract", "recorded": 1}


def test_screen_unknown_stage_is_usage_error(tmp_path: Path) -> None:
    root = _init(tmp_path)
    result = runner.invoke(app, ["-C", str(root), "screen", "bogus-stage", "--by", "ethan"])
    assert result.exit_code == EXIT_USAGE, result.output


def test_assign_default_is_all_canonical_records(tmp_path: Path) -> None:
    root = _init(tmp_path)
    _add_actor(root)
    _import(root, tmp_path, "two.json", _CSL_TWO_RECORDS)

    result = runner.invoke(
        app,
        [
            "--why",
            "Assigning both reviewers to the full pool.",
            "-C",
            str(root),
            "assign",
            "title-abstract",
            "--actors",
            "ethan,sam",
            "--by",
            "ethan",
        ],
    )
    assert result.exit_code == EXIT_OK, result.output
    assert "2 record(s)" in result.output

    repo = open_repo(root)
    report = verify_repository(repo)
    assert report.ok, report.issues


def test_assign_with_filter_narrows_records(tmp_path: Path) -> None:
    root = _init(tmp_path)
    _add_actor(root)
    _import(root, tmp_path, "two.json", _CSL_TWO_RECORDS)

    result = runner.invoke(
        app,
        [
            "--why",
            "Assigning only the 2009 records to sam for calibration.",
            "-C",
            str(root),
            "assign",
            "title-abstract",
            "--actors",
            "sam",
            "--by",
            "ethan",
            "--filter",
            "year == 2009",
        ],
    )
    assert result.exit_code == EXIT_OK, result.output
    assert "1 record(s)" in result.output


def test_assign_unknown_stage_is_usage_error(tmp_path: Path) -> None:
    root = _init(tmp_path)
    _import(root, tmp_path, "one.json", _CSL_ONE_RECORD)
    result = runner.invoke(
        app, ["-C", str(root), "assign", "bogus-stage", "--actors", "ethan", "--by", "ethan"]
    )
    assert result.exit_code == EXIT_USAGE, result.output
