"""Pins the scriptable paths of `strata retrieve` and `strata studies` as they behave today.

Written before they moved onto `strata.core.operations` (OpenSpec change
`add-web-ui-write-surfaces`, tasks 6.1 and 6.2) and kept afterwards: every assertion is about what a
person at a terminal sees and what lands in the repository, so it must hold on both sides of that
move. `test_cli_m3.py` keeps the looser behavioural tests, including the interactive sessions, which
stay on the command line; these pin the exact text, files and commit messages of the paths the web
interface mirrors (`--report --outcome`, `--group`, `--split`).
"""

import json
import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from strata import gitio
from strata.cli import main as cli_main
from strata.cli.main import EXIT_OK, EXIT_RATIONALE_REFUSED, EXIT_USAGE, app
from strata.core.repo import Repo
from strata.protocol import pool as pool_mod
from strata.protocol import retrieval, studies
from tests.unit._m3 import add_records, decide, init_review, record, rpt

runner = CliRunner()

_STUDY_ID = re.compile(r"std_[0-9a-z]{16}")
_EVENT_ID = re.compile(r"ev_[0-9a-z]{26}")


@pytest.fixture(autouse=True)
def _wide_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    # See test_cli_search_import_snapshots.py: rich wraps at the terminal width.
    for console in (cli_main.out_console, cli_main.err_console):
        monkeypatch.setattr(console, "_width", 1000)


def _commit_all(repo: Repo) -> None:
    # The fixture writes its records and decisions directly; a review that was built with the
    # commands has its derived files in step, and `strata verify` expects them to be.
    pool_mod.regenerate_all(repo)
    gitio.add_all(repo.root)
    if gitio.is_dirty(repo.root):
        gitio.commit(repo.root, "test: fixture\n\nStrata-Op: test\nStrata-Actor: ethan")


def _run(repo: Repo, *args: str) -> tuple[int, str]:
    result = runner.invoke(app, ["-C", str(repo.root), *args])
    return result.exit_code, _STUDY_ID.sub("<STUDY>", " ".join(result.output.split()))


def _sought(tmp_path: Path) -> Repo:
    repo = init_review(tmp_path)
    decide(repo, "title-abstract", add_records(repo, 3))
    _commit_all(repo)
    return repo


def _included(tmp_path: Path) -> Repo:
    repo = init_review(tmp_path)
    records = [
        record(1, abstract="NCT00713310"),
        record(2, abstract="NCT00713310"),
        record(3, abstract="Three experiments."),
        record(4),
    ]
    decide(repo, "full-text", add_records(repo, records))
    _commit_all(repo)
    return repo


def _head_message(repo: Repo) -> str:
    text = gitio.run(["log", "-1", "--format=%B"], cwd=repo.root).stdout
    return _STUDY_ID.sub("<STUDY>", text)


def _head_files(repo: Repo) -> list[str]:
    out = gitio.run(["show", "--name-only", "--format=", "HEAD"], cwd=repo.root).stdout
    return sorted(line for line in out.splitlines() if line)


def _count(repo: Repo) -> int:
    return len(gitio.log(repo.root))


def _status(repo: Repo) -> list[str]:
    out = gitio.run(["status", "--porcelain", "--untracked-files=all"], cwd=repo.root).stdout
    return sorted(line for line in out.splitlines() if line)


# ---------------------------------------------------------------------------------------------
# strata retrieve --report --outcome
# ---------------------------------------------------------------------------------------------


def test_retrieve_a_report_output_commit_and_files(tmp_path: Path) -> None:
    repo = _sought(tmp_path)
    before = _count(repo)

    code, out = _run(
        repo, "--why", "got it from the library", "retrieve", "--by", "ethan",
        "--report", rpt(1), "--outcome", "retrieved", "--source", "institutional-access",
        "--version", "version-of-record",
    )  # fmt: skip

    assert code == EXIT_OK
    assert out == f"recorded {rpt(1)}: retrieved"
    assert _count(repo) == before + 1
    assert _head_message(repo) == (
        f"retrieve: retrieved: {rpt(1)}\n\ngot it from the library\n\n"
        "Strata-Op: retrieve\nStrata-Actor: ethan\n\n"
    )
    assert _head_files(repo) == [
        "derived/counts.json",
        "events/retrieval/ethan.ndjson",
        "fulltext/manifest.ndjson",
    ]
    assert _status(repo) == []
    [event] = retrieval.all_retrieval_events(repo)
    assert event["body"]["report"] == rpt(1)
    assert event["body"]["status"] == "retrieved"
    assert event["body"]["source"] == "institutional-access"
    assert event["body"]["version"] == "version-of-record"
    assert "path" not in event["body"]


def test_retrieve_a_report_prints_json_with_the_event_id(tmp_path: Path) -> None:
    repo = _sought(tmp_path)

    code, out = _run(
        repo, "--json", "--why", "no access to it at all", "retrieve", "--by", "ethan",
        "--report", rpt(2), "--outcome", "not-retrieved", "--reason", "no-access",
    )  # fmt: skip

    assert code == EXIT_OK
    payload = json.loads(out)
    assert payload["report"] == rpt(2) and payload["status"] == "not-retrieved"
    assert _EVENT_ID.fullmatch(payload["event"])
    assert _head_message(repo).startswith(f"retrieve: not-retrieved: {rpt(2)}\n")
    assert rpt(2) not in retrieval.outstanding_reports(repo)


def test_retrieve_an_interlibrary_loan_request_commits_only_the_event(
    tmp_path: Path,
) -> None:
    repo = _sought(tmp_path)

    code, _ = _run(
        repo, "--why", "asked for an interlibrary loan", "retrieve", "--by", "ethan",
        "--report", rpt(3), "--outcome", "ill-requested",
    )  # fmt: skip

    assert code == EXIT_OK
    # No manifest entry and no derived file: a request moves nothing the views show.
    assert _head_files(repo) == ["events/retrieval/ethan.ndjson"]
    assert rpt(3) in retrieval.outstanding_reports(repo)  # still to get


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (
            ["--outcome", "not-retrieved"],
            "error: a report marked not retrievable needs a reason from ('no-access', "
            "'not-found', 'retracted', 'language', 'no-response-from-author', 'other')",
        ),
        (
            ["--outcome", "not-retrieved", "--reason", "other"],
            "error: reason 'other' needs free text saying what happened",
        ),
        (
            ["--outcome", "retrieved"],
            "error: a retrieved document needs a source (e.g. institutional-access)",
        ),
        (
            ["--outcome", "bogus"],
            "error: status must be one of ('sought', 'ill-requested', 'retrieved', "
            "'not-retrieved'), got 'bogus'",
        ),
    ],
)
def test_retrieve_a_report_refuses_what_cannot_be_recorded_and_writes_nothing(
    tmp_path: Path, args: list[str], message: str
) -> None:
    repo = _sought(tmp_path)
    before = _count(repo)

    code, out = _run(
        repo, "--why", "an outcome that cannot be recorded", "retrieve", "--by", "ethan",
        "--report", rpt(3), *args,
    )  # fmt: skip

    assert code == EXIT_USAGE
    assert out == message
    assert _count(repo) == before
    assert _status(repo) == []
    assert retrieval.all_retrieval_events(repo) == []


def test_retrieve_a_report_that_was_not_sought_is_refused(tmp_path: Path) -> None:
    repo = _sought(tmp_path)

    code, out = _run(
        repo, "--why", "a report that was never sought", "retrieve", "--by", "ethan",
        "--report", "rpt_nope", "--outcome", "retrieved", "--source", "s",
    )  # fmt: skip

    assert code == EXIT_USAGE
    assert out == (
        "error: 'rpt_nope' is not a report sought (its record must be included at "
        "title/abstract screening)"
    )
    assert _status(repo) == []


def test_retrieve_a_report_without_a_rationale_is_refused_before_writing(tmp_path: Path) -> None:
    repo = _sought(tmp_path)
    before = _count(repo)

    code, out = _run(repo, "retrieve", "--by", "ethan", "--report", rpt(3), "--outcome", "sought")

    assert code == EXIT_RATIONALE_REFUSED
    assert out == (
        "error: a rationale is required; pass --why or --why-file in a non-interactive context"
    )
    assert _count(repo) == before
    assert _status(repo) == []


def test_retrieve_a_report_without_commit_leaves_the_work_in_the_tree(tmp_path: Path) -> None:
    repo = _sought(tmp_path)
    before = _count(repo)

    code, _ = _run(
        repo, "--no-commit", "retrieve", "--by", "ethan", "--report", rpt(1),
        "--outcome", "not-retrieved", "--reason", "no-access",
    )  # fmt: skip

    assert code == EXIT_OK
    assert _count(repo) == before
    changed = {line[3:] for line in _status(repo)}
    assert "events/retrieval/ethan.ndjson" in changed or "events/retrieval/" in changed
    assert "derived/counts.json" in changed


# ---------------------------------------------------------------------------------------------
# strata studies --group / --split
# ---------------------------------------------------------------------------------------------


def test_studies_group_output_commit_and_files(tmp_path: Path) -> None:
    repo = _included(tmp_path)
    before = _count(repo)

    code, out = _run(
        repo, "--why", "Same trial, 12-month follow-up", "studies", "--by", "ethan",
        "--group", rpt(1), "--group", rpt(2),
    )  # fmt: skip

    assert code == EXIT_OK
    assert out == "recorded grouped 2 report(s) into <STUDY>"
    assert _count(repo) == before + 1
    assert _head_message(repo) == (
        "studies: grouped 2 report(s) into <STUDY>\n\nSame trial, 12-month follow-up\n\n"
        "Strata-Op: studies\nStrata-Actor: ethan\n\n"
    )
    assert _head_files(repo) == ["events/study/ethan.ndjson"]
    assert _status(repo) == []
    assert len(studies.study_map(repo).members) == 3
    [event] = studies.all_study_events(repo)
    assert event["ev"] == "study-group"
    assert event["body"]["reports"] == [rpt(1), rpt(2)]
    assert event["body"]["rationale"] == "Same trial, 12-month follow-up"


def test_studies_split_prints_json_and_commits_the_event(tmp_path: Path) -> None:
    repo = _included(tmp_path)

    code, out = _run(
        repo, "--json", "--why", "Three experiments in one paper", "studies", "--by", "ethan",
        "--split", rpt(3), "--into", "3",
    )  # fmt: skip

    assert code == EXIT_OK
    payload = json.loads(re.sub(r"<STUDY>", "std_x", out))
    assert payload["report"] == rpt(3) and len(payload["studies"]) == 3
    assert payload["rationale"] == "Three experiments in one paper"
    assert _head_message(repo) == (
        f"studies: split {rpt(3)} into 3 studies\n\nThree experiments in one paper\n\n"
        "Strata-Op: studies\nStrata-Actor: ethan\n\n"
    )
    assert _head_files(repo) == ["events/study/ethan.ndjson"]
    assert len(studies.study_map(repo).studies_of[rpt(3)]) == 3


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["--group", "rpt_0000000000000009"], "error: not included reports: rpt_0000000000000009"),
        (
            ["--split", "rpt_0000000000000004", "--into", "1"],
            "error: a report is split into at least 2 studies",
        ),
        (
            ["--split", "rpt_0000000000000099", "--into", "2"],
            "error: not an included report: rpt_0000000000000099",
        ),
    ],
)
def test_studies_decisions_that_cannot_be_recorded_are_refused_and_write_nothing(
    tmp_path: Path, args: list[str], message: str
) -> None:
    repo = _included(tmp_path)
    before = _count(repo)

    code, out = _run(
        repo, "--why", "a grouping that cannot be recorded", "studies", "--by", "ethan", *args
    )

    assert code == EXIT_USAGE
    assert out == message
    assert _count(repo) == before
    assert _status(repo) == []
    assert studies.all_study_events(repo) == []


def test_studies_decisions_need_a_rationale_even_without_commit(tmp_path: Path) -> None:
    repo = _included(tmp_path)

    code, out = _run(repo, "--no-commit", "studies", "--by", "ethan", "--group", rpt(1))

    assert code == EXIT_RATIONALE_REFUSED
    assert out == (
        "error: a rationale is required; pass --why or --why-file in a non-interactive context"
    )
    assert studies.all_study_events(repo) == []
    assert _status(repo) == []


def test_studies_decisions_need_an_actor(tmp_path: Path) -> None:
    repo = _included(tmp_path)

    code, out = _run(repo, "--why", "Same trial, 12-month follow-up", "studies", "--group", rpt(1))

    assert code == EXIT_USAGE
    assert out == "error: --by is required to record a decision"


def test_studies_list_shows_the_suggestions_with_their_evidence(tmp_path: Path) -> None:
    repo = _included(tmp_path)

    code, out = _run(repo, "studies", "--list")

    assert code == EXIT_OK
    assert out == (
        "4 included reports -> 4 studies suggested grouping: rpt_0000000000000001 + "
        "rpt_0000000000000002 same trial registration: NCT00713310 suggested split: "
        "rpt_0000000000000003 into 3 (Three experiments)"
    )
    assert studies.all_study_events(repo) == []  # looking records nothing
    assert _status(repo) == []
