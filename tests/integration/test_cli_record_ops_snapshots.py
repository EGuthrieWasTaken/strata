"""Pins `strata fix`, `strata criteria add` and `strata assign` as they behave today.

Written before the three commands moved onto `strata.core.operations` (OpenSpec change
`add-web-ui-write-surfaces`, tasks 5.1 to 5.3) and kept afterwards: every assertion is about what
a person at a terminal sees and what lands in the repository, so it must hold on both sides of
that move. The looser tests in `test_cli_records.py`, `test_cli_criteria.py` and
`test_cli_screen.py` stay as they are; these pin the exact text, files and commit messages.

Output is compared after collapsing whitespace (rich wraps at the terminal width) and replacing the
temporary directory and generated record ids, which are the only parts that differ between runs.
"""

import json
import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from strata import gitio
from strata.cli import main as cli_main
from strata.cli.main import EXIT_OK, EXIT_RATIONALE_REFUSED, EXIT_USAGE, app
from strata.core import records as records_mod
from strata.core.repo import open_repo
from strata.protocol import screening as screening_mod

runner = CliRunner()

_RECORD_ID = re.compile(r"rec_[0-9a-z]{16}")

_TWO_PAPERS = json.dumps(
    [
        {"title": "Original title", "DOI": "10.1000/aaa", "issued": {"date-parts": [[2008]]}},
        {"title": "Second paper", "DOI": "10.1000/bbb", "issued": {"date-parts": [[2015]]}},
    ]
)


@pytest.fixture(autouse=True)
def _wide_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    # See test_cli_search_import_snapshots.py: the consoles are built at import, so the width is
    # set on them, and a very wide terminal makes the output independent of the temp path length.
    for console in (cli_main.out_console, cli_main.err_console):
        monkeypatch.setattr(console, "_width", 1000)


def _run(*args: str) -> tuple[int, str]:
    result = runner.invoke(app, list(args))
    return result.exit_code, " ".join(result.output.split())


def _review(tmp_path: Path) -> Path:
    """A review with two actors, two imported records and one search."""
    root = tmp_path / "review"
    code, out = _run("init", str(root), "--title", "T", "--actor", "ethan", "--actor-name", "Ethan")
    assert code == EXIT_OK, out
    code, out = _run(
        "--why", "adding sam to the team", "-C", str(root), "actor", "add", "sam", "Sam",
        "--role", "screener",
    )  # fmt: skip
    assert code == EXIT_OK, out
    export = tmp_path / "papers.json"
    export.write_text(_TWO_PAPERS, encoding="utf-8")
    code, out = _run(
        "--why", "a database search for the pins", "-C", str(root), "search", "add",
        "--database", "MEDLINE", "--platform", "Ovid", "--by", "ethan", "--query", "q",
    )  # fmt: skip
    assert code == EXIT_OK, out
    code, out = _run(
        "--why", "importing the two papers", "-C", str(root), "import", str(export),
        "--by", "ethan", "--search", "S-01-medline",
    )  # fmt: skip
    assert code == EXIT_OK, out
    return root


def _record_ids(root: Path) -> list[str]:
    return sorted(r["id"] for r in records_mod.read_records(open_repo(root)))


def _record_id_by_title(root: Path, title: str) -> str:
    records = records_mod.read_records(open_repo(root))
    return str(next(r["id"] for r in records if r["title"] == title))


def _head_message(root: Path) -> str:
    return _RECORD_ID.sub("<REC>", gitio.run(["log", "-1", "--format=%B"], cwd=root).stdout)


def _head_files(root: Path) -> list[str]:
    out = gitio.run(["show", "--name-only", "--format=", "HEAD"], cwd=root).stdout
    return sorted(line for line in out.splitlines() if line)


def _commit_count(root: Path) -> int:
    return len(gitio.log(root))


def _status(root: Path) -> list[str]:
    out = gitio.run(["status", "--porcelain", "--untracked-files=all"], cwd=root).stdout
    return sorted(line for line in out.splitlines() if line)


# ---------------------------------------------------------------------------------------------
# strata fix
# ---------------------------------------------------------------------------------------------


def test_fix_output_commit_and_files(tmp_path: Path) -> None:
    root = _review(tmp_path)
    rid = _record_id_by_title(root, "Original title")
    before = _commit_count(root)

    code, out = _run(
        "--why", "fixing a typo in the title", "-C", str(root), "fix", rid,
        "--field", "title", "--value", "Corrected title", "--by", "ethan",
    )  # fmt: skip

    assert code == EXIT_OK
    assert out == f"fixed {rid}.title: 'Original title' -> 'Corrected title'"
    assert _commit_count(root) == before + 1
    assert _head_message(root) == (
        "fix(<REC>): corrected title\n\nfixing a typo in the title\n\n"
        "Strata-Op: fix\nStrata-Actor: ethan\n\n"
    )
    assert _head_files(root) == ["events/fix/ethan.ndjson", "records/records.ndjson"]
    assert _status(root) == []

    events = [
        json.loads(line)
        for line in (root / "events" / "fix" / "ethan.ndjson").read_text().splitlines()
    ]
    assert [e["ev"] for e in events] == ["record-amend"]
    assert events[0]["body"] == {
        "record": rid,
        "field": "title",
        "old": "Original title",
        "new": "Corrected title",
        "source": "manual",
    }


def test_fix_accepts_a_short_id_and_prints_json(tmp_path: Path) -> None:
    root = _review(tmp_path)
    rid = _record_id_by_title(root, "Original title")

    code, out = _run(
        "--json", "--why", "adding the missing journal", "-C", str(root), "fix", rid[:8],
        "--field", "container-title", "--value", "Journal", "--by", "ethan",
    )  # fmt: skip

    assert code == EXIT_OK
    assert json.loads(out) == {
        "record": rid,
        "field": "container-title",
        "old": None,
        "new": "Journal",
    }


def test_fix_refuses_a_field_it_cannot_edit_and_writes_nothing(tmp_path: Path) -> None:
    root = _review(tmp_path)
    rid = _record_id_by_title(root, "Original title")
    before = _commit_count(root)

    code, out = _run(
        "--why", "trying to edit a structured field", "-C", str(root), "fix", rid,
        "--field", "author", "--value", "x", "--by", "ethan",
    )  # fmt: skip

    assert code == EXIT_USAGE
    assert out == (
        "error: field 'author' cannot be corrected with `strata fix` -- only plain string "
        "fields can: DOI, ISBN, PMCID, PMID, URL, abstract, container-title, issue, keyword, "
        "language, page, title, volume. `author` and `issued` are structured fields, not "
        "editable this way yet."
    )
    assert _commit_count(root) == before
    assert _status(root) == []


def test_fix_refuses_an_unknown_record_and_writes_nothing(tmp_path: Path) -> None:
    root = _review(tmp_path)
    before = _commit_count(root)

    code, out = _run(
        "--why", "correcting a record that is not there", "-C", str(root), "fix", "rec_nope",
        "--field", "title", "--value", "x", "--by", "ethan",
    )  # fmt: skip

    assert code == EXIT_USAGE
    assert out == "error: no record id starts with 'rec_nope'"
    assert _commit_count(root) == before
    assert _status(root) == []


def test_fix_without_a_rationale_is_refused_before_writing(tmp_path: Path) -> None:
    root = _review(tmp_path)
    rid = _record_id_by_title(root, "Original title")
    before = _commit_count(root)

    code, out = _run(
        "-C", str(root), "fix", rid, "--field", "title", "--value", "x", "--by", "ethan"
    )

    assert code == EXIT_RATIONALE_REFUSED
    assert (
        out
        == "error: a rationale is required; pass --why or --why-file in a non-interactive context"
    )
    assert _commit_count(root) == before
    assert _status(root) == []


def test_fix_without_commit_leaves_the_work_in_the_tree(tmp_path: Path) -> None:
    root = _review(tmp_path)
    rid = _record_id_by_title(root, "Original title")
    before = _commit_count(root)

    code, _ = _run(
        "--no-commit", "-C", str(root), "fix", rid, "--field", "volume", "--value", "12",
        "--by", "ethan",
    )  # fmt: skip

    assert code == EXIT_OK
    assert _commit_count(root) == before
    # The first fix by this actor creates its event file, so it is new rather than modified.
    assert _status(root) == [" M records/records.ndjson", "?? events/fix/ethan.ndjson"]


# ---------------------------------------------------------------------------------------------
# strata criteria add
# ---------------------------------------------------------------------------------------------

_ADD = [
    "criteria", "add", "--kind", "inclusion", "--label", "Adults only",
    "--definition", "Participants are 18 or over", "--applies-at", "title-abstract,full-text",
    "--by", "ethan",
]  # fmt: skip


def test_criteria_add_output_commit_and_files(tmp_path: Path) -> None:
    root = _review(tmp_path)
    before = _commit_count(root)

    code, out = _run("--why", "adding the population criterion", "-C", str(root), *_ADD)

    assert code == EXIT_OK
    assert out == "added INC-01 (criteria v1)"
    assert _commit_count(root) == before + 1
    assert _head_message(root) == (
        "criteria-add(INC-01): add criterion INC-01\n\nadding the population criterion\n\n"
        "Strata-Op: criteria-add\nStrata-Criterion: INC-01\nStrata-Actor: ethan\n\n"
    )
    assert _head_files(root) == [
        "derived/irr.json",
        "derived/pool.tsv",
        "events/criteria/ethan.ndjson",
        "protocol/criteria.yaml",
    ]
    assert _status(root) == []


def test_criteria_add_prints_the_criterion_as_json_and_honours_an_explicit_id(
    tmp_path: Path,
) -> None:
    root = _review(tmp_path)
    code, _ = _run("--why", "adding the first criterion", "-C", str(root), *_ADD)
    assert code == EXIT_OK

    code, out = _run(
        "--json", "--why", "adding a second criterion", "-C", str(root), "criteria", "add",
        "--kind", "exclusion", "--label", "Not empirical", "--definition", "Not an empirical study",
        "--applies-at", "title-abstract", "--by", "ethan", "--id", "EXC-77",
    )  # fmt: skip

    assert code == EXIT_OK
    assert json.loads(out) == {
        "id": "EXC-77",
        "kind": "exclusion",
        "label": "Not empirical",
        "definition": "Not an empirical study",
        "applies_at": ["title-abstract"],
        "since_version": 2,
        "status": "active",
    }


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        (
            {"--applies-at": "nowhere"},
            "error: applies_at names unconfigured stage(s) ['nowhere']; screening.stages is "
            "['title-abstract', 'full-text']",
        ),
        (
            {"--kind": "maybe"},
            "error: kind must be one of ('inclusion', 'exclusion'), got 'maybe'",
        ),
    ],
)
def test_criteria_add_refuses_bad_input_and_writes_nothing(
    tmp_path: Path, overrides: dict[str, str], message: str
) -> None:
    root = _review(tmp_path)
    args = list(_ADD)
    for flag, value in overrides.items():
        args[args.index(flag) + 1] = value
    before = _commit_count(root)

    code, out = _run("--why", "adding a criterion that will not work", "-C", str(root), *args)

    assert code == EXIT_USAGE
    assert out == message
    assert _commit_count(root) == before
    assert _status(root) == []


def test_criteria_add_without_a_rationale_is_refused_and_writes_nothing(tmp_path: Path) -> None:
    root = _review(tmp_path)
    before = _commit_count(root)

    code, out = _run("-C", str(root), *_ADD)

    assert code == EXIT_RATIONALE_REFUSED
    assert (
        out
        == "error: a rationale is required; pass --why or --why-file in a non-interactive context"
    )
    assert _commit_count(root) == before
    assert _status(root) == []


def test_criteria_add_without_commit_still_regenerates_what_it_moves(tmp_path: Path) -> None:
    root = _review(tmp_path)
    before = _commit_count(root)

    code, out = _run("--no-commit", "--why", "adding without committing", "-C", str(root), *_ADD)

    assert code == EXIT_OK
    assert out == "added INC-01 (criteria v1)"
    assert _commit_count(root) == before
    changed = {line[3:] for line in _status(root)}
    assert "protocol/criteria.yaml" in changed
    assert any(path.startswith("events/criteria") for path in changed)


# ---------------------------------------------------------------------------------------------
# strata assign
# ---------------------------------------------------------------------------------------------


def test_assign_output_commit_and_files(tmp_path: Path) -> None:
    root = _review(tmp_path)
    before = _commit_count(root)

    code, out = _run(
        "--why", "assigning both of us", "-C", str(root), "assign", "title-abstract",
        "--actors", "ethan,sam", "--by", "ethan",
    )  # fmt: skip

    assert code == EXIT_OK
    assert out == "assigned 2 record(s) at title-abstract to ethan, sam"
    assert _commit_count(root) == before + 1
    assert _head_message(root) == (
        "assign(title-abstract): assigned 2 title-abstract record(s)\n\nassigning both of us\n\n"
        "Strata-Op: assign\nStrata-Actor: ethan\nStrata-Actors: ethan,sam\n\n"
    )
    assert _head_files(root) == ["events/assign/ethan.ndjson"]
    assert _status(root) == []

    events = [
        json.loads(line)
        for line in (root / "events" / "assign" / "ethan.ndjson").read_text().splitlines()
    ]
    assert [e["ev"] for e in events] == ["assign"]
    assert events[0]["body"] == {
        "stage": "title-abstract",
        "records": _record_ids(root),
        "actors": ["ethan", "sam"],
    }


def test_assign_puts_the_records_in_each_assigned_reviewers_queue(tmp_path: Path) -> None:
    root = _review(tmp_path)
    older = _record_id_by_title(root, "Original title")

    code, _ = _run(
        "--why", "only sam sees the older paper", "-C", str(root), "assign", "title-abstract",
        "--actors", "sam", "--by", "ethan", "--filter", "year < 2010",
    )  # fmt: skip

    assert code == EXIT_OK
    repo = open_repo(root)
    assert screening_mod.stage_queue(repo, "title-abstract", "sam") == sorted(_record_ids(root))
    assert screening_mod.stage_queue(repo, "title-abstract", "ethan") == [
        rid for rid in _record_ids(root) if rid != older
    ]


def test_assign_with_a_filter_records_it_and_counts_the_matches(tmp_path: Path) -> None:
    root = _review(tmp_path)

    code, out = _run(
        "--why", "assigning a subset", "-C", str(root), "assign", "full-text",
        "--actors", "ethan", "--by", "ethan", "--filter", "year >= 2010",
    )  # fmt: skip

    assert code == EXIT_OK
    assert out == "assigned 1 record(s) at full-text to ethan"
    event = json.loads((root / "events" / "assign" / "ethan.ndjson").read_text().splitlines()[-1])
    assert event["body"]["filter"] == "year >= 2010"
    assert len(event["body"]["records"]) == 1


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (
            ["full-text", "--filter", "year >="],
            "error: invalid --filter: expected a value, got ''",
        ),
        (
            ["full-text", "--filter", "year > 2100"],
            "error: no records matched to assign",
        ),
        (
            ["nowhere"],
            "error: unknown stage 'nowhere'; configured stages are ['title-abstract', 'full-text']",
        ),
    ],
)
def test_assign_refuses_and_writes_nothing(tmp_path: Path, args: list[str], message: str) -> None:
    root = _review(tmp_path)
    before = _commit_count(root)

    code, out = _run(
        "--why", "assigning in a way that cannot work", "-C", str(root), "assign", *args,
        "--actors", "ethan", "--by", "ethan",
    )  # fmt: skip

    assert code == EXIT_USAGE
    assert out == message
    assert _commit_count(root) == before
    assert _status(root) == []


def test_assign_refuses_a_handle_that_is_not_an_actor_and_lists_who_can_be_assigned(
    tmp_path: Path,
) -> None:
    # Changed on purpose (it used to record the assignment): a typo in a handle made a queue
    # nobody could work.
    root = _review(tmp_path)
    before = _commit_count(root)

    code, out = _run(
        "--why", "assigning a handle that is not an actor", "-C", str(root), "assign",
        "full-text", "--actors", "ghost", "--by", "ethan",
    )  # fmt: skip

    assert code == EXIT_USAGE
    assert out == (
        "error: cannot assign 'ghost' (not an actor of this review); "
        "eligible actors are ['ethan', 'sam']"
    )
    assert _commit_count(root) == before
    assert _status(root) == []


def test_assign_refuses_the_whole_assignment_when_one_handle_is_wrong(tmp_path: Path) -> None:
    root = _review(tmp_path)
    before = _commit_count(root)

    code, out = _run(
        "--why", "one good handle and two bad ones", "-C", str(root), "assign", "full-text",
        "--actors", "ethan,ghost,zed,ghost", "--by", "ethan",
    )  # fmt: skip

    assert code == EXIT_USAGE
    assert out == (
        "error: cannot assign 'ghost' (not an actor of this review), "
        "'zed' (not an actor of this review); eligible actors are ['ethan', 'sam']"
    )
    assert _commit_count(root) == before
    assert not (root / "events" / "assign").exists()


def test_assign_refuses_an_actor_who_has_been_deactivated(tmp_path: Path) -> None:
    root = _review(tmp_path)
    code, _ = _run("--why", "sam has left the team", "-C", str(root), "actor", "deactivate", "sam")
    assert code == EXIT_OK
    before = _commit_count(root)

    code, out = _run(
        "--why", "assigning someone who has left", "-C", str(root), "assign", "full-text",
        "--actors", "sam", "--by", "ethan",
    )  # fmt: skip

    assert code == EXIT_USAGE
    assert out == (
        "error: cannot assign 'sam' (has been deactivated); eligible actors are ['ethan']"
    )
    assert _commit_count(root) == before


def test_assign_checks_the_handles_even_when_nothing_is_to_be_committed(tmp_path: Path) -> None:
    root = _review(tmp_path)

    code, out = _run(
        "--no-commit", "-C", str(root), "assign", "full-text", "--actors", "ghost", "--by", "ethan"
    )

    assert code == EXIT_USAGE and "cannot assign 'ghost'" in out
    assert not (root / "events" / "assign").exists()


def test_assign_without_a_rationale_is_refused_before_writing(tmp_path: Path) -> None:
    root = _review(tmp_path)
    before = _commit_count(root)

    code, out = _run(
        "-C", str(root), "assign", "title-abstract", "--actors", "ethan", "--by", "ethan"
    )

    assert code == EXIT_RATIONALE_REFUSED
    assert (
        out
        == "error: a rationale is required; pass --why or --why-file in a non-interactive context"
    )
    assert _commit_count(root) == before
    assert _status(root) == []
