import json
from pathlib import Path

from typer.testing import CliRunner

from strata.cli.main import EXIT_OK, EXIT_USAGE, app
from strata.core.repo import open_repo
from strata.core.verify import verify_repository
from strata.protocol.screening import all_screen_events

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


def _set_single_assignment(root: Path) -> None:
    from strata.core import manifest as manifest_mod

    doc = manifest_mod.load_manifest_doc(root)
    manifest_mod.set_value(
        doc, "screening.assignment", {"title-abstract": ["ethan"], "full-text": ["ethan"]}
    )
    manifest_mod.write_manifest(root, doc)


def _add_criterion(root: Path, criterion_id: str, applies_at: str = "title-abstract") -> None:
    result = runner.invoke(
        app,
        [
            "-C",
            str(root),
            "--why",
            "Adding a criterion mid-review after pilot extraction.",
            "criteria",
            "add",
            "--kind",
            "exclusion",
            "--label",
            "Under 18",
            "--definition",
            "Mean sample age under 18.",
            "--applies-at",
            applies_at,
            "--by",
            "ethan",
            "--id",
            criterion_id,
        ],
    )
    assert result.exit_code == EXIT_OK, result.output


def test_rescreen_nothing_to_rescreen_on_fresh_repo(tmp_path: Path) -> None:
    root = _init(tmp_path)
    result = runner.invoke(app, ["-C", str(root), "rescreen", "--by", "ethan"])
    assert result.exit_code == EXIT_OK, result.output
    assert "nothing to rescreen" in result.output


def test_rescreen_keep_previous_clears_staleness(tmp_path: Path) -> None:
    root = _init(tmp_path)
    _set_single_assignment(root)
    _import(root, tmp_path, "one.json", _CSL_ONE_RECORD)

    screen_result = runner.invoke(
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
    assert screen_result.exit_code == EXIT_OK, screen_result.output

    _add_criterion(root, "EXC-07")

    rescreen_result = runner.invoke(
        app,
        [
            "--why",
            "Re-screening records made stale by the new criterion.",
            "-C",
            str(root),
            "rescreen",
            "--by",
            "ethan",
        ],
        input="k\n",
    )
    assert rescreen_result.exit_code == EXIT_OK, rescreen_result.output

    repo = open_repo(root)
    events = all_screen_events(repo, "title-abstract")
    assert len(events) == 2
    assert events[-1]["body"]["decision"] == "include"

    stale_tsv = repo.path("derived", "stale.tsv").read_text(encoding="utf-8")
    assert stale_tsv.splitlines() == [
        "record_id\tstage\tprior_decision\tprior_criteria\treason\tsince_version\ttitle"
    ]

    report = verify_repository(repo)
    assert report.ok, report.issues


def test_rescreen_re_decide_records_new_decision(tmp_path: Path) -> None:
    root = _init(tmp_path)
    _set_single_assignment(root)
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
    _add_criterion(root, "EXC-07")

    result = runner.invoke(
        app,
        [
            "--why",
            "Re-screening records made stale by the new criterion.",
            "-C",
            str(root),
            "rescreen",
            "--by",
            "ethan",
        ],
        input="e\n1\n\n",
    )
    assert result.exit_code == EXIT_OK, result.output

    repo = open_repo(root)
    events = all_screen_events(repo, "title-abstract")
    assert events[-1]["body"]["decision"] == "exclude"
    assert events[-1]["body"]["criteria"] == ["EXC-07"]


def test_rescreen_mark_forces_manual_staleness(tmp_path: Path) -> None:
    root = _init(tmp_path)
    _set_single_assignment(root)
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
    repo = open_repo(root)
    from strata.core.records import read_records

    (record_id,) = [r["id"] for r in read_records(repo)]

    mark_result = runner.invoke(
        app,
        [
            "--why",
            "Flagging this record for a second look.",
            "-C",
            str(root),
            "rescreen",
            "--stage",
            "title-abstract",
            "--by",
            "ethan",
            "--mark",
            record_id,
        ],
    )
    assert mark_result.exit_code == EXIT_OK, mark_result.output

    stale_tsv = repo.path("derived", "stale.tsv").read_text(encoding="utf-8")
    assert "manual" in stale_tsv


def test_rescreen_json_output(tmp_path: Path) -> None:
    root = _init(tmp_path)
    _set_single_assignment(root)
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
    _add_criterion(root, "EXC-07")

    result = runner.invoke(
        app,
        [
            "--why",
            "Re-screening records made stale by the new criterion.",
            "--json",
            "-C",
            str(root),
            "rescreen",
            "--by",
            "ethan",
        ],
        input="k\n",
    )
    assert result.exit_code == EXIT_OK, result.output
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload == {"decided": 1}


def test_rescreen_unknown_stage_is_usage_error(tmp_path: Path) -> None:
    root = _init(tmp_path)
    result = runner.invoke(
        app, ["-C", str(root), "rescreen", "--stage", "bogus-stage", "--by", "ethan"]
    )
    assert result.exit_code == EXIT_USAGE, result.output
