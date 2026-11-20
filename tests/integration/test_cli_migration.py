"""Migrating a review from Rayyan, Covidence or EPPI-Reviewer: `strata import --format <tool>`
for the records and `strata screen --from <tool>` for the decisions
(openspec:literature-import#migration-imports-from-incumbent-tools)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from typer.testing import CliRunner

from strata.cli.main import EXIT_OK, EXIT_USAGE, app
from strata.core import operations as ops
from strata.core.events import read_events
from strata.core.repo import Repo
from strata.protocol import screening as screening_mod
from tests.unit._m3 import init_review

runner = CliRunner()
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "migration"
WHY = "Migrating this review's records and decisions from the tool we used before."


def _cli(repo: Repo, *args: str, code: int = EXIT_OK) -> Any:
    result = runner.invoke(app, ["--json", "--why", WHY, "-C", str(repo.root), *args])
    assert result.exit_code == code, result.output
    return json.loads(result.output) if code == EXIT_OK and result.output.strip() else result


def _review(tmp_path: Path) -> Repo:
    repo = init_review(tmp_path, actors=("sam", "ada"))
    ops.add_criterion(
        repo,
        kind="inclusion",
        label="Adult learners",
        definition="Participants are adults",
        applies_at=["title-abstract", "full-text"],
        actor="ethan",
        rationale=WHY,
        criterion_id="INC-01",
    )
    return repo


def _imported(repo: Repo, name: str, fmt: str) -> None:
    _cli(
        repo,
        "import",
        str(FIXTURES / name),
        "--format",
        fmt,
        "--via",
        "citation-searching",
        "--by",
        "ethan",
    )


def _events(repo: Repo, stage: str, actor: str) -> list[dict[str, Any]]:
    return list(read_events(screening_mod.screen_events_path(repo, stage, actor)))


def test_a_rayyan_project_is_migrated_with_its_decisions_marked_imported(tmp_path: Path) -> None:
    repo = _review(tmp_path)
    _imported(repo, "rayyan-articles.csv", "rayyan")

    out = _cli(
        repo, "screen", "title-abstract", "--by", "ada", "--decisions",
        str(FIXTURES / "rayyan-articles.csv"), "--from", "rayyan", "--reviewer", "Ada",
        "--reason", "wrong population=INC-01",
    )  # fmt: skip

    assert out["recorded"] == 2 and out["skipped"] == []
    events = _events(repo, "title-abstract", "ada")
    assert {e["body"]["decision"] for e in events} == {"include", "exclude"}
    assert all(e["body"]["imported"] is True and e["actor"] == "ada" for e in events)
    (excluded,) = [e for e in events if e["body"]["decision"] == "exclude"]
    assert excluded["body"]["criteria"] == ["INC-01"]
    assert "wrong population" in excluded["body"]["note"]


def test_an_exclusion_whose_reason_names_no_criterion_is_reported_not_recorded(
    tmp_path: Path,
) -> None:
    repo = _review(tmp_path)
    _imported(repo, "rayyan-articles.csv", "rayyan")

    out = _cli(
        repo, "screen", "title-abstract", "--by", "sam", "--decisions",
        str(FIXTURES / "rayyan-articles.csv"), "--from", "rayyan", "--reviewer", "Sam",
    )  # fmt: skip

    # Sam: include Cepeda, maybe Roediger, exclude the Okonkwo trial for a reason with no criterion
    assert out["recorded"] == 2
    (skipped,) = out["skipped"]
    assert "wrong outcome" in skipped["why"] and "--reason" in skipped["why"]


def test_an_export_with_several_reviewers_needs_one_named(tmp_path: Path) -> None:
    repo = _review(tmp_path)
    _imported(repo, "rayyan-articles.csv", "rayyan")

    result = _cli(
        repo, "screen", "title-abstract", "--by", "ada", "--decisions",
        str(FIXTURES / "rayyan-articles.csv"), "--from", "rayyan", code=EXIT_USAGE,
    )  # fmt: skip
    assert "--reviewer" in result.output and "Ada, Sam" in result.output
    assert _events(repo, "title-abstract", "ada") == []


def test_a_covidence_list_is_recorded_as_its_decision_at_each_stage(tmp_path: Path) -> None:
    repo = _review(tmp_path)
    _imported(repo, "covidence-excluded.csv", "covidence")
    path = str(FIXTURES / "covidence-excluded.csv")

    ta = _cli(
        repo, "screen", "title-abstract", "--by", "ada", "--decisions", path,
        "--from", "covidence", "--list", "excluded",
    )  # fmt: skip
    ft = _cli(
        repo, "screen", "full-text", "--by", "ada", "--decisions", path, "--from", "covidence",
        "--list", "excluded", "--reason", "Wrong population=INC-01",
        "--reason", "Wrong study design=INC-01",
    )  # fmt: skip

    assert ta["recorded"] == 2 and ft["recorded"] == 2
    assert {e["body"]["decision"] for e in _events(repo, "title-abstract", "ada")} == {"include"}
    assert {e["body"]["decision"] for e in _events(repo, "full-text", "ada")} == {"exclude"}


def test_an_eppi_reviewer_export_is_migrated(tmp_path: Path) -> None:
    repo = _review(tmp_path)
    _imported(repo, "eppi-reviewer.json", "eppi-json")

    out = _cli(
        repo, "screen", "title-abstract", "--by", "ada", "--decisions",
        str(FIXTURES / "eppi-reviewer.json"), "--from", "eppi-json",
        "--reason", "Exclude: not empirical=INC-01",
    )  # fmt: skip

    assert out["recorded"] == 2  # the uncoded reference has no decision to migrate
    assert all(e["body"]["imported"] for e in _events(repo, "title-abstract", "ada"))


def test_decisions_for_records_not_yet_imported_are_reported(tmp_path: Path) -> None:
    repo = _review(tmp_path)

    out = _cli(
        repo, "screen", "title-abstract", "--by", "ada", "--decisions",
        str(FIXTURES / "eppi-reviewer.json"), "--from", "eppi-json",
    )  # fmt: skip

    assert out["recorded"] == 0
    assert all("import the file first" in s["why"] for s in out["skipped"])


# ------------------------------------------------------------------------ what is refused


def test_a_migration_that_cannot_be_read_as_asked_is_refused_with_the_reason(
    tmp_path: Path,
) -> None:
    repo = _review(tmp_path)
    rayyan = str(FIXTURES / "rayyan-articles.csv")
    covidence = str(FIXTURES / "covidence-excluded.csv")
    cases = [
        (["--from", "rayyan"], "--from needs --decisions FILE"),
        (["--decisions", rayyan, "--from", "zotero"], "--from must be one of"),
        (["--decisions", str(tmp_path / "none.csv"), "--from", "rayyan"], "no such file"),
        (["--decisions", rayyan, "--from", "rayyan", "--reviewer", "Ada", "--reason", "x"],
         "is not REASON=CRITERION"),
        (["--decisions", rayyan, "--from", "rayyan", "--reviewer", "Nobody"],
         "no reviewer 'Nobody'"),
        (["--decisions", covidence, "--from", "covidence"], "pass --list"),
        (["--decisions", covidence, "--from", "rayyan"], "not a Rayyan CSV export"),
    ]  # fmt: skip
    for args, message in cases:
        result = _cli(repo, "screen", "title-abstract", "--by", "ada", *args, code=EXIT_USAGE)
        assert message in " ".join(result.output.split()), (args, result.output)
    result = _cli(
        repo, "screen", "no-such-stage", "--by", "ada", "--decisions", rayyan, "--from", "rayyan",
        "--reviewer", "Ada", code=EXIT_USAGE,
    )  # fmt: skip
    assert "unknown stage" in result.output
    assert _events(repo, "title-abstract", "ada") == []


def test_an_irrelevant_covidence_list_says_nothing_about_full_text(tmp_path: Path) -> None:
    repo = _review(tmp_path)
    _imported(repo, "covidence-excluded.csv", "covidence")

    out = _cli(
        repo, "screen", "full-text", "--by", "ada", "--decisions",
        str(FIXTURES / "covidence-excluded.csv"), "--from", "covidence", "--list", "irrelevant",
    )  # fmt: skip

    assert out["recorded"] == 0 and out["skipped"] == []


def test_importing_a_file_as_the_wrong_tool_is_refused(tmp_path: Path) -> None:
    repo = _review(tmp_path)

    result = _cli(
        repo, "import", str(FIXTURES / "covidence-excluded.csv"), "--format", "eppi-json",
        "--via", "citation-searching", "--by", "ethan", code=EXIT_USAGE,
    )  # fmt: skip

    assert "not an EPPI-Reviewer JSON export" in result.output


def test_a_human_readable_run_lists_what_was_not_recorded(tmp_path: Path) -> None:
    repo = _review(tmp_path)
    _imported(repo, "rayyan-articles.csv", "rayyan")

    result = runner.invoke(
        app,
        ["--why", WHY, "-C", str(repo.root), "screen", "title-abstract", "--by", "sam",
         "--decisions", str(FIXTURES / "rayyan-articles.csv"), "--from", "rayyan",
         "--reviewer", "Sam"],
    )  # fmt: skip

    assert result.exit_code == EXIT_OK, result.output
    assert "recorded 2 imported decision(s)" in result.output
    assert "not recorded:" in result.output and "wrong outcome" in result.output
