"""Full-text retrieval and study grouping in the browser: openspec:web-ui#full-text-retrieval-screen
and #study-grouping-screen (OpenSpec change `add-web-ui-write-surfaces`, tasks 6.1 and 6.2).

Everything goes through the real ASGI app against a real temporary review. Each screen is also held
to its command: the same input on an identical review must leave the same commit.
"""

from __future__ import annotations

import html
import re
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from typer.testing import CliRunner

from strata import gitio
from strata.cli.main import EXIT_OK, app
from strata.core.repo import Repo
from strata.protocol import retrieval, studies
from strata.web.app import create_app
from tests.integration._equivalence import committed_snapshot
from tests.unit._m3 import add_records, decide, init_review, record, rpt

runner = CliRunner()
_TOKEN = "test-session-token-0123456789"
_WHY = "Recorded from a test of the browser screens"


def _commit_all(repo: Repo) -> None:
    gitio.add_all(repo.root)
    if gitio.is_dirty(repo.root):
        gitio.commit(repo.root, "test: fixture\n\nStrata-Op: test\nStrata-Actor: ethan")


def _home(tmp_path: Path, name: str) -> Path:
    """A folder of its own, so two reviews built the same way can sit side by side."""
    home = tmp_path / name
    home.mkdir()
    return home


def _sought(tmp_path: Path, name: str = "review") -> Repo:
    repo = init_review(_home(tmp_path, name))
    decide(repo, "title-abstract", add_records(repo, 3))
    _commit_all(repo)
    return repo


def _included(tmp_path: Path, name: str = "review") -> Repo:
    repo = init_review(_home(tmp_path, name))
    records = [
        record(1, abstract="NCT00713310"),
        record(2, abstract="NCT00713310"),
        record(3, abstract="Three experiments."),
        record(4),
    ]
    decide(repo, "full-text", add_records(repo, records))
    _commit_all(repo)
    return repo


def _client(repo: Repo) -> TestClient:
    client = TestClient(
        create_app(repo_root=repo.root, actor="ethan", session_token=_TOKEN),
        base_url="http://127.0.0.1:8000",
    )
    assert client.get(f"/?token={_TOKEN}").status_code == 200
    return client


def _post(client: TestClient, path: str, data: dict[str, Any]) -> Any:
    return client.post(path, data={"csrf_token": _TOKEN, **data}, follow_redirects=False)


def _count(repo: Repo) -> int:
    return len(gitio.log(repo.root))


def _clean(repo: Repo) -> bool:
    return gitio.run(["status", "--porcelain", "--untracked-files=all"], cwd=repo.root).stdout == ""


def _head(repo: Repo) -> str:
    return gitio.run(["log", "-1", "--format=%B"], cwd=repo.root).stdout


def _text(response: Any) -> str:
    """The page as a reader sees it: tags gone, entities decoded, whitespace collapsed."""
    return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", response.text)))


def _cli(repo: Repo, *args: str) -> None:
    result = runner.invoke(app, ["-C", str(repo.root), *args])
    assert result.exit_code == EXIT_OK, result.output


# ------------------------------------------------------------------------------------ retrieval


def test_the_retrieval_screen_lists_what_is_sought_and_offers_no_upload(tmp_path: Path) -> None:
    repo = _sought(tmp_path)
    client = _client(repo)

    index = client.get("/retrieve")
    form = client.get(f"/retrieve/{rpt(1)}")

    assert index.status_code == 200 and form.status_code == 200
    assert "3 reports sought: 0 retrieved, 0 not retrievable, 3 outstanding" in _text(index)
    for n in (1, 2, 3):
        assert f'href="/retrieve/{rpt(n)}"' in index.text
    for page in (index, form):
        assert 'type="file"' not in page.text
        assert 'enctype="multipart' not in page.text
        assert 'name="path"' not in page.text


def test_recording_a_retrieved_report_is_what_strata_retrieve_records(tmp_path: Path) -> None:
    via_cli = _sought(tmp_path, "cli")
    via_web = _sought(tmp_path, "web")
    client = _client(via_web)

    _cli(
        via_cli, "--why", "got it from the library", "retrieve", "--by", "ethan",
        "--report", rpt(1), "--outcome", "retrieved", "--source", "institutional-access",
        "--version", "version-of-record",
    )  # fmt: skip
    response = _post(
        client,
        f"/retrieve/{rpt(1)}",
        {
            "outcome": "retrieved",
            "source": "institutional-access",
            "version": "version-of-record",
            "rationale": "got it from the library",
        },
    )

    assert response.status_code == 303 and response.headers["location"] == "/retrieve"
    assert committed_snapshot(via_cli.root) == committed_snapshot(via_web.root)
    assert _head(via_web).startswith(f"retrieve: retrieved: {rpt(1)}\n")
    assert rpt(1) not in retrieval.outstanding_reports(via_web)
    assert _clean(via_web)
    assert "2 outstanding" in _text(client.get("/retrieve"))


def test_a_report_that_cannot_be_retrieved_is_what_strata_retrieve_records(
    tmp_path: Path,
) -> None:
    via_cli = _sought(tmp_path, "cli")
    via_web = _sought(tmp_path, "web")

    _cli(
        via_cli, "--why", "no access to it at all", "retrieve", "--by", "ethan",
        "--report", rpt(2), "--outcome", "not-retrieved", "--reason", "no-access",
    )  # fmt: skip
    _post(
        _client(via_web),
        f"/retrieve/{rpt(2)}",
        {"outcome": "not-retrieved", "reason": "no-access", "rationale": "no access to it at all"},
    )

    assert committed_snapshot(via_cli.root) == committed_snapshot(via_web.root)
    assert rpt(2) not in retrieval.outstanding_reports(via_web)


def test_an_interlibrary_loan_request_is_what_strata_retrieve_records(tmp_path: Path) -> None:
    via_cli = _sought(tmp_path, "cli")
    via_web = _sought(tmp_path, "web")

    _cli(
        via_cli, "--why", "asked for an interlibrary loan", "retrieve", "--by", "ethan",
        "--report", rpt(3), "--outcome", "ill-requested",
    )  # fmt: skip
    _post(
        _client(via_web),
        f"/retrieve/{rpt(3)}",
        {
            "outcome": "ill-requested",
            "source": "",
            "rationale": "asked for an interlibrary loan",
        },
    )

    assert committed_snapshot(via_cli.root) == committed_snapshot(via_web.root)


def test_fields_that_do_not_belong_to_the_outcome_are_not_recorded(tmp_path: Path) -> None:
    # The form always carries every field; a reason typed and then abandoned must not ride along
    # on a document that was retrieved, and a path must never be taken from a request.
    repo = _sought(tmp_path)

    response = _post(
        _client(repo),
        f"/retrieve/{rpt(1)}",
        {
            "outcome": "retrieved",
            "source": "institutional-access",
            "version": "preprint",
            "reason": "no-access",
            "reason_text": "left over",
            "path": "/etc/passwd",
            "rationale": _WHY,
        },
    )

    assert response.status_code == 303
    [event] = retrieval.all_retrieval_events(repo)
    assert "reason" not in event["body"] and "reason_text" not in event["body"]
    manifest = (repo.root / "fulltext" / "manifest.ndjson").read_text()
    assert "/etc/passwd" not in manifest and '"path"' not in manifest


def test_retrieved_without_a_source_is_refused_in_the_commands_words(tmp_path: Path) -> None:
    repo = _sought(tmp_path)
    before = _count(repo)

    response = _post(
        _client(repo),
        f"/retrieve/{rpt(1)}",
        {"outcome": "retrieved", "source": "", "version": "preprint", "rationale": _WHY},
    )

    assert response.status_code == 422
    assert "a retrieved document needs a source (e.g. institutional-access)" in _text(response)
    assert _count(repo) == before and _clean(repo)
    assert retrieval.all_retrieval_events(repo) == []


def test_not_retrieved_needs_a_reason_and_other_needs_words(tmp_path: Path) -> None:
    repo = _sought(tmp_path)
    client = _client(repo)
    before = _count(repo)

    no_reason = _post(
        client, f"/retrieve/{rpt(1)}", {"outcome": "not-retrieved", "rationale": _WHY}
    )
    other = _post(
        client,
        f"/retrieve/{rpt(1)}",
        {"outcome": "not-retrieved", "reason": "other", "reason_text": " ", "rationale": _WHY},
    )

    assert no_reason.status_code == 422
    assert "a report marked not retrievable needs a reason from" in _text(no_reason)
    assert other.status_code == 422
    assert "reason 'other' needs free text saying what happened" in _text(other)
    assert _count(repo) == before and _clean(repo)


def test_a_retrieval_without_a_rationale_or_an_outcome_writes_nothing(tmp_path: Path) -> None:
    repo = _sought(tmp_path)
    client = _client(repo)
    before = _count(repo)

    no_rationale = _post(
        client,
        f"/retrieve/{rpt(1)}",
        {"outcome": "retrieved", "source": "s", "rationale": ""},
    )
    no_outcome = _post(client, f"/retrieve/{rpt(1)}", {"rationale": _WHY})

    assert no_rationale.status_code == 422 and "a rationale is required" in _text(no_rationale)
    assert no_outcome.status_code == 422 and "Say what happened" in _text(no_outcome)
    assert _count(repo) == before and _clean(repo)


def test_a_report_that_was_not_sought_is_a_404_on_both_verbs(tmp_path: Path) -> None:
    repo = _sought(tmp_path)
    client = _client(repo)

    assert client.get("/retrieve/rpt_nope").status_code == 404
    assert (
        _post(
            client, "/retrieve/rpt_nope", {"outcome": "retrieved", "source": "s", "rationale": _WHY}
        ).status_code
        == 404
    )
    assert _clean(repo)


def test_an_outcome_can_be_put_back_in_the_queue(tmp_path: Path) -> None:
    repo = _sought(tmp_path)
    client = _client(repo)
    _post(
        client,
        f"/retrieve/{rpt(1)}",
        {"outcome": "not-retrieved", "reason": "no-access", "rationale": _WHY},
    )
    assert rpt(1) not in retrieval.outstanding_reports(repo)

    response = _post(
        client, f"/retrieve/{rpt(1)}", {"outcome": "sought", "rationale": "the library found it"}
    )

    assert response.status_code == 303
    assert rpt(1) in retrieval.outstanding_reports(repo)


# -------------------------------------------------------------------------------------- studies


def test_viewing_the_studies_screen_shows_suggestions_and_records_nothing(
    tmp_path: Path,
) -> None:
    repo = _included(tmp_path)
    client = _client(repo)
    before = _count(repo)

    page = client.get("/studies")
    again = client.get("/studies")

    assert page.status_code == 200 and again.status_code == 200
    text = _text(page)
    assert "4 included reports → 4 studies" in text
    assert "same trial registration: NCT00713310" in text
    assert "It may report 3 studies" in text and "Three experiments" in text
    assert "Group these 2 reports as one study" in text
    assert studies.all_study_events(repo) == []
    assert _count(repo) == before and _clean(repo)


def test_accepting_a_suggestion_records_a_grouping_and_lowers_the_study_count(
    tmp_path: Path,
) -> None:
    via_cli = _included(tmp_path, "cli")
    via_web = _included(tmp_path, "web")
    client = _client(via_web)
    assert len(studies.study_map(via_web).members) == 4

    _cli(
        via_cli, "--why", "Same trial, 12-month follow-up", "studies", "--by", "ethan",
        "--group", rpt(1), "--group", rpt(2),
    )  # fmt: skip
    response = _post(
        client,
        "/studies/group",
        {"reports": [rpt(1), rpt(2)], "rationale": "Same trial, 12-month follow-up"},
    )

    assert response.status_code == 303 and response.headers["location"] == "/studies?done=1"
    assert len(studies.study_map(via_web).members) == 3
    assert committed_snapshot(via_cli.root) == committed_snapshot(via_web.root)
    assert _clean(via_web)
    page = _text(client.get(response.headers["location"]))
    assert "Decision recorded" in page and "4 included reports → 3 studies" in page
    assert studies.suggestions(via_web).groupings == []


def test_splitting_a_report_is_what_strata_studies_split_records(tmp_path: Path) -> None:
    via_cli = _included(tmp_path, "cli")
    via_web = _included(tmp_path, "web")

    _cli(
        via_cli, "--why", "Three experiments in one paper", "studies", "--by", "ethan",
        "--split", rpt(3), "--into", "3",
    )  # fmt: skip
    response = _post(
        _client(via_web),
        "/studies/split",
        {"report": rpt(3), "parts": "3", "rationale": "Three experiments in one paper"},
    )

    assert response.status_code == 303
    assert committed_snapshot(via_cli.root) == committed_snapshot(via_web.root)
    assert len(studies.study_map(via_web).studies_of[rpt(3)]) == 3


def test_a_decision_without_a_rationale_is_refused_even_when_the_review_does_not_ask(
    tmp_path: Path,
) -> None:
    repo = _included(tmp_path)
    toml = repo.root / "strata.toml"
    toml.write_text(
        toml.read_text().replace("require_rationale = true", "require_rationale = false")
    )
    _commit_all(repo)
    client = _client(repo)
    before = _count(repo)

    group = _post(client, "/studies/group", {"reports": [rpt(1), rpt(2)], "rationale": ""})
    split = _post(client, "/studies/split", {"report": rpt(3), "parts": "3", "rationale": ""})

    assert group.status_code == 422 and "a rationale is required" in _text(group)
    assert split.status_code == 422 and "a rationale is required" in _text(split)
    assert studies.all_study_events(repo) == []
    assert _count(repo) == before and _clean(repo)


def test_a_grouping_the_command_refuses_is_refused_with_its_reason(tmp_path: Path) -> None:
    repo = _included(tmp_path)
    client = _client(repo)

    not_included = _post(
        client,
        "/studies/group",
        {"reports": [rpt(1), "rpt_0000000000000009"], "rationale": "Same trial, follow-up"},
    )
    too_few = _post(
        client, "/studies/group", {"reports": [rpt(1)], "rationale": "Same trial, follow-up"}
    )

    assert not_included.status_code == 422
    assert "not included reports: rpt_0000000000000009" in _text(not_included)
    assert too_few.status_code == 422 and "at least two reports" in _text(too_few)
    assert studies.all_study_events(repo) == []
    assert _clean(repo)


def test_a_split_the_command_refuses_is_refused_with_its_reason(tmp_path: Path) -> None:
    repo = _included(tmp_path)
    client = _client(repo)

    unknown = _post(
        client,
        "/studies/split",
        {"report": "rpt_0000000000000099", "parts": "2", "rationale": "Two experiments"},
    )
    one = _post(
        client, "/studies/split", {"report": rpt(4), "parts": "1", "rationale": "Two experiments"}
    )
    silly = _post(
        client,
        "/studies/split",
        {"report": rpt(4), "parts": "1000000000", "rationale": "Two experiments"},
    )

    assert unknown.status_code == 422
    assert "not an included report: rpt_0000000000000099" in _text(unknown)
    assert one.status_code == 422 and "2 to 20" in _text(one)
    assert silly.status_code == 422 and "2 to 20" in _text(silly)
    assert studies.all_study_events(repo) == []
    assert _clean(repo)


def test_the_studies_screen_lists_the_studies_as_they_stand(tmp_path: Path) -> None:
    repo = _included(tmp_path)
    client = _client(repo)
    _post(
        client,
        "/studies/group",
        {"reports": [rpt(1), rpt(2)], "rationale": "Same trial, 12-month follow-up"},
    )

    page = client.get("/studies")

    assert re.search(r'data-label="Reports">Author1[^<;]*;\s*Author2[^<;]*</td>', page.text)
    assert len(studies.study_map(repo).members) == 3


def test_the_dashboard_links_to_retrieval_and_studies(tmp_path: Path) -> None:
    repo = _sought(tmp_path)

    page = _client(repo).get("/")

    assert 'href="/retrieve"' in page.text
    assert 'href="/studies"' in page.text
