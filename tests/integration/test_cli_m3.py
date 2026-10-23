"""`strata retrieve`, `strata studies` and the retrieval line of `strata status` (M3)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from typer.testing import CliRunner

from strata import gitio
from strata.cli.main import EXIT_OK, EXIT_USAGE, app
from strata.core import fulltext
from strata.core.repo import Repo
from strata.core.verify import verify_repository
from strata.protocol import retrieval, studies
from tests.unit._m3 import add_records, decide, init_review, record, rpt

runner = CliRunner()
WHY = ("--why", "Recording this for the review record.")


def _cli(repo: Repo, *args: str, input: str | None = None, code: int = EXIT_OK) -> Any:  # noqa: A002
    result = runner.invoke(app, [*WHY, "-C", str(repo.root), *args], input=input)
    assert result.exit_code == code, result.output
    return result


def _commit_all(repo: Repo) -> None:
    gitio.add_all(repo.root)
    if gitio.is_dirty(repo.root):
        gitio.commit(repo.root, "test: fixture\n\nStrata-Op: test\nStrata-Actor: ethan")


def _subjects(repo: Repo) -> list[str]:
    return gitio.log(repo.root, fmt="%s")


def _sought(tmp_path: Path, n: int = 3) -> Repo:
    repo = init_review(tmp_path)
    decide(repo, "title-abstract", add_records(repo, n))
    _commit_all(repo)
    return repo


# --- strata retrieve -------------------------------------------------------------------------


def test_retrieve_lists_the_outstanding_reports_as_json(tmp_path: Path) -> None:
    repo = _sought(tmp_path)
    out = json.loads(_cli(repo, "--json", "retrieve", "--by", "ethan").output)
    assert (out["sought"], out["outstanding"]) == (3, 3)
    assert [r["report"] for r in out["reports"]] == [rpt(1), rpt(2), rpt(3)]
    assert out["reports"][0]["doi"] == "10.1000/test.1"


def test_retrieve_list_prints_a_human_summary(tmp_path: Path) -> None:
    repo = _sought(tmp_path)
    text = _cli(repo, "retrieve", "--by", "ethan", "--list").output
    assert "3 reports sought. 3 outstanding." in text


def test_retrieve_records_one_scripted_outcome_and_commits_it(tmp_path: Path) -> None:
    repo = _sought(tmp_path)
    _cli(
        repo,
        "retrieve", "--by", "ethan", "--report", rpt(1), "--outcome", "retrieved",
        "--source", "institutional-access", "--version", "version-of-record",
        "--path", "cepeda-2008.pdf",
    )  # fmt: skip
    [entry] = fulltext.read_manifest(repo)
    assert entry["path"] == "cepeda-2008.pdf" and entry["locator"] == {"doi": "10.1000/test.1"}
    assert _subjects(repo)[0].startswith("retrieve:")
    assert not gitio.is_dirty(repo.root)
    tracked = gitio.run(["ls-files"], cwd=repo.root).stdout
    assert "fulltext/manifest.ndjson" in tracked and ".pdf" not in tracked
    assert not verify_repository(repo).issues


def test_retrieve_scripted_not_retrieved_with_a_locator_override(tmp_path: Path) -> None:
    repo = _sought(tmp_path)
    _cli(
        repo,
        "retrieve", "--by", "ethan", "--report", rpt(1), "--outcome", "not-retrieved",
        "--reason", "no-response-from-author",
    )  # fmt: skip
    _cli(
        repo,
        "retrieve", "--by", "ethan", "--report", rpt(2), "--outcome", "retrieved",
        "--source", "author-copy", "--locator", "pmid=19076480",
    )  # fmt: skip
    assert fulltext.read_manifest(repo)[0]["locator"] == {"pmid": "19076480"}
    counts = retrieval.retrieval_counts(repo)
    assert counts.reasons == {"no-response-from-author": 1}


def test_retrieve_scripted_usage_errors(tmp_path: Path) -> None:
    repo = _sought(tmp_path)
    _cli(repo, "retrieve", "--by", "ethan", "--report", rpt(1), code=EXIT_USAGE)  # no outcome
    _cli(
        repo, "retrieve", "--by", "ethan", "--report", rpt(1), "--outcome", "not-retrieved",
        code=EXIT_USAGE,
    )  # fmt: skip  # reason missing
    _cli(
        repo, "retrieve", "--by", "ethan", "--report", rpt(1), "--outcome", "retrieved",
        "--source", "s", "--locator", "doi", code=2,
    )  # fmt: skip  # malformed locator
    assert retrieval.all_retrieval_events(repo) == []


def test_retrieve_interactively_records_each_outcome(tmp_path: Path) -> None:
    repo = _sought(tmp_path)
    # report 1: have the file (defaults); report 2: not retrievable; report 3: skip
    keys = "f\n\n\n\n" + "n\nno-access\n" + "s\n"
    result = _cli(repo, "retrieve", "--by", "ethan", input=keys)
    assert "2 outcome(s) recorded" in result.output
    states = retrieval.retrieval_states(repo)
    assert states[rpt(1)].status == "retrieved"
    assert states[rpt(2)].status == "not-retrieved"
    assert rpt(3) not in states  # skipping records nothing
    [entry] = fulltext.read_manifest(repo)
    assert entry["source"] == "institutional-access" and entry["version"] == "version-of-record"
    assert _subjects(repo)[0].startswith("retrieve:")


def test_retrieve_interactively_handles_ill_other_and_a_bad_choice(tmp_path: Path) -> None:
    repo = _sought(tmp_path)
    keys = "i\n" + "zzz\n" + "n\nother\nwithdrawn\n" + "q\n"
    _cli(repo, "retrieve", "--by", "ethan", input=keys)
    states = retrieval.retrieval_states(repo)
    assert states[rpt(1)].status == "ill-requested"
    assert states[rpt(2)].event["body"]["reason_text"] == "withdrawn"


def test_retrieve_interactive_reports_a_validation_error_and_carries_on(tmp_path: Path) -> None:
    repo = _sought(tmp_path, 1)
    # 'other' with no text is refused, then the user answers properly
    keys = "n\nother\n   \n" + "n\nlanguage\n" + "q\n"
    result = _cli(repo, "retrieve", "--by", "ethan", input=keys)
    assert "free text" in result.output
    assert retrieval.retrieval_states(repo)[rpt(1)].event["body"]["reason"] == "language"


def test_retrieve_open_doi_does_not_record_anything(tmp_path: Path, monkeypatch: Any) -> None:
    repo = _sought(tmp_path, 1)
    opened: list[str] = []
    monkeypatch.setattr("strata.cli.main.webbrowser.open", opened.append)
    _cli(repo, "retrieve", "--by", "ethan", input="u\nq\n")
    assert opened == ["https://doi.org/10.1000/test.1"]
    assert retrieval.all_retrieval_events(repo) == []


def test_status_shows_retrieval_progress(tmp_path: Path) -> None:
    repo = _sought(tmp_path)
    _cli(
        repo, "retrieve", "--by", "ethan", "--report", rpt(1), "--outcome", "retrieved",
        "--source", "s",
    )  # fmt: skip
    text = _cli(repo, "status").output
    assert "3 reports sought" in text and "1 retrieved" in text and "2 outstanding" in text
    assert "NEXT  strata retrieve" in text
    payload = json.loads(_cli(repo, "--json", "status").output)
    assert payload["retrieval"]["sought"] == 3 and payload["retrieval"]["retrieved"] == 1


# --- strata studies --------------------------------------------------------------------------


def _full_text_review(tmp_path: Path, records: list[dict[str, Any]] | int) -> Repo:
    repo = init_review(tmp_path)
    decide(repo, "full-text", add_records(repo, records))
    _commit_all(repo)
    return repo


def test_studies_summarises_reports_and_suggestions_as_json(tmp_path: Path) -> None:
    repo = _full_text_review(
        tmp_path,
        [
            record(1, abstract="NCT00713310"),
            record(2, abstract="NCT00713310"),
            record(3, abstract="Three experiments."),
        ],
    )
    out = json.loads(_cli(repo, "--json", "studies").output)
    assert (out["reports"], out["studies"]) == (3, 3)
    assert out["groupings"][0]["reports"] == [rpt(1), rpt(2)]
    assert "NCT00713310" in out["groupings"][0]["evidence"][0]
    assert out["splits"] == [{"report": rpt(3), "parts": 3, "evidence": "Three experiments"}]
    text = _cli(repo, "studies", "--list").output
    assert "3 included reports -> 3 studies" in text and "suggested grouping" in text


def test_studies_group_and_split_are_scriptable_and_need_a_rationale(tmp_path: Path) -> None:
    repo = _full_text_review(tmp_path, 4)
    _cli(repo, "studies", "--group", rpt(1), "--group", rpt(2), code=EXIT_USAGE)  # no --by
    _cli(repo, "studies", "--by", "ethan", "--group", rpt(1), "--group", rpt(2))
    assert len(studies.study_map(repo).members) == 3
    assert _subjects(repo)[0].startswith("studies:")
    _cli(repo, "studies", "--by", "ethan", "--split", rpt(3), "--into", "2")
    assert len(studies.study_map(repo).members) == 4
    _cli(repo, "studies", "--by", "ethan", "--group", rpt(9), code=EXIT_USAGE)  # not included
    _cli(repo, "studies", "--by", "ethan", "--split", rpt(4), "--into", "1", code=EXIT_USAGE)
    assert not verify_repository(repo).issues


def test_studies_group_json_output(tmp_path: Path) -> None:
    repo = _full_text_review(tmp_path, 2)
    out = json.loads(
        _cli(
            repo, "--json", "studies", "--by", "ethan", "--group", rpt(1), "--group", rpt(2)
        ).output
    )
    assert out["reports"] == [rpt(1), rpt(2)] and out["study"].startswith("std_")


def test_studies_interactive_groups_after_showing_both(tmp_path: Path) -> None:
    repo = _full_text_review(
        tmp_path, [record(1, abstract="NCT00713310"), record(2, abstract="NCT00713310")]
    )
    result = _cli(repo, "studies", "--by", "ethan", input="?\ng\n")
    assert "Suggested grouping" in result.output and "NCT00713310" in result.output
    [current] = studies.study_map(repo).members.values()
    assert current == (rpt(1), rpt(2))
    assert studies.suggestions(repo).groupings == []


def test_studies_interactive_keep_separate_is_remembered(tmp_path: Path) -> None:
    repo = _full_text_review(
        tmp_path, [record(1, abstract="NCT00713310"), record(2, abstract="NCT00713310")]
    )
    _cli(repo, "studies", "--by", "ethan", input="k\n")
    assert len(studies.study_map(repo).members) == 2
    assert studies.suggestions(repo).groupings == []


def test_studies_interactive_split_and_keep_as_one(tmp_path: Path) -> None:
    repo = _full_text_review(
        tmp_path,
        [record(1, abstract="Three experiments."), record(2, abstract="Two studies were run.")],
    )
    _cli(repo, "studies", "--by", "ethan", input="s\nk\n")
    current = studies.study_map(repo)
    assert len(current.studies_of[rpt(1)]) == 3  # split into the suggested three
    assert len(current.studies_of[rpt(2)]) == 1  # kept as one
    assert studies.suggestions(repo).splits == []


def test_studies_interactive_quit_and_skip_decide_nothing(tmp_path: Path) -> None:
    repo = _full_text_review(
        tmp_path, [record(1, abstract="NCT00713310"), record(2, abstract="NCT00713310")]
    )
    result = _cli(repo, "studies", "--by", "ethan", input="s\n")
    assert "0 decision(s) recorded" in result.output
    _cli(repo, "studies", "--by", "ethan", input="q\n")
    assert studies.all_study_events(repo) == []


def test_studies_interactive_needs_an_actor(tmp_path: Path) -> None:
    repo = _full_text_review(tmp_path, 2)
    _cli(repo, "studies", code=EXIT_USAGE)
