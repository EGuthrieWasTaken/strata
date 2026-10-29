"""Correcting a record, adding a criterion and assigning reviewers in the browser:
openspec:web-ui#correcting-a-record, #adding-a-criterion, #assigning-reviewers
(OpenSpec change `add-web-ui-write-surfaces`, tasks 5.1 to 5.3).

Everything goes through the real ASGI app against a real temporary review. Each screen is also
held to its command: the same input on an identical review must leave the same commit.
"""

from __future__ import annotations

import html
import json
import re
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from typer.testing import CliRunner

from strata import gitio
from strata.cli.main import EXIT_OK, app
from strata.core import operations as ops
from strata.core import records as records_mod
from strata.core.actor import add_actor
from strata.core.init import init_repository
from strata.core.repo import Repo, open_repo
from strata.protocol import rescreen as rescreen_mod
from strata.protocol import screening as screening_mod
from strata.web.app import create_app
from tests.integration._equivalence import committed_snapshot

runner = CliRunner()
_TOKEN = "test-session-token-0123456789"
_WHY = "Recorded from a test of the browser screens"
_PAPERS = json.dumps(
    [
        {"title": "Original title", "DOI": "10.1000/aaa", "issued": {"date-parts": [[2008]]}},
        {"title": "Second paper", "DOI": "10.1000/bbb", "issued": {"date-parts": [[2015]]}},
    ]
)


def _review(tmp_path: Path, name: str = "review") -> Repo:
    """A review with two actors, a recorded search and its two imported records."""
    root = tmp_path / name
    init_repository(root, title="Record Ops", actor_handle="ethan", actor_name="Ethan")
    repo = open_repo(root)
    add_actor(repo, handle="sam", name="Sam", role="screener")
    gitio.add(root, ["strata.toml"])
    gitio.commit(root, "test: add sam")
    ops.record_search(
        repo,
        database="MEDLINE",
        platform="Ovid",
        executed="2026-03-04",
        executed_by="ethan",
        query="q",
        rationale="a database search for the test",
    )
    export = tmp_path / f"{name}-papers.json"
    export.write_text(_PAPERS, encoding="utf-8")
    ops.import_file(
        repo,
        export,
        imported_by="ethan",
        search_id="S-01-medline",
        rationale="importing the two test papers",
    )
    return open_repo(root)  # the actor added above is only in a freshly opened repo's config


def _client(repo: Repo) -> TestClient:
    client = TestClient(
        create_app(repo_root=repo.root, actor="ethan", session_token=_TOKEN),
        base_url="http://127.0.0.1:8000",
    )
    assert client.get(f"/?token={_TOKEN}").status_code == 200
    return client


def _post(client: TestClient, path: str, data: dict[str, Any]) -> Any:
    return client.post(path, data={"csrf_token": _TOKEN, **data}, follow_redirects=False)


def _id_of(repo: Repo, title: str) -> str:
    return str(next(r["id"] for r in records_mod.read_records(repo) if r["title"] == title))


def _count(repo: Repo) -> int:
    return len(gitio.log(repo.root))


def _clean(repo: Repo) -> bool:
    return gitio.run(["status", "--porcelain", "--untracked-files=all"], cwd=repo.root).stdout == ""


def _head(repo: Repo) -> str:
    return gitio.run(["log", "-1", "--format=%B"], cwd=repo.root).stdout


def _text(response: Any) -> str:
    """The page as a reader sees it: tags gone, entities decoded, whitespace collapsed."""
    return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", response.text)))


def _cli(*args: str) -> None:
    result = runner.invoke(app, list(args))
    assert result.exit_code == EXIT_OK, result.output


# --------------------------------------------------------------------------- correcting a record


def test_the_record_page_offers_the_fields_a_correction_can_change(tmp_path: Path) -> None:
    repo = _review(tmp_path)
    rid = _id_of(repo, "Original title")

    page = _client(repo).get(f"/records/{rid}")

    assert page.status_code == 200
    assert f'action="/records/{rid}/fix"' in page.text
    options = re.findall(r'<option value="([^"]+)"', page.text)
    assert "title" in options and "DOI" in options
    assert "author" not in options and "issued" not in options
    assert "now &ldquo;Original title&rdquo;" in page.text


def test_correcting_a_field_records_the_amendment_and_the_timeline_shows_it(
    tmp_path: Path,
) -> None:
    repo = _review(tmp_path)
    rid = _id_of(repo, "Original title")
    client = _client(repo)
    before = _count(repo)

    response = _post(
        client,
        f"/records/{rid}/fix",
        {"field": "title", "value": "Corrected title", "rationale": "fixing a typo in the title"},
    )

    assert response.status_code == 303
    assert response.headers["location"] == f"/records/{rid}"
    assert _count(repo) == before + 1
    assert _clean(repo)
    assert _head(repo) == (
        f"fix({rid}): corrected title\n\nfixing a typo in the title\n\n"
        "Strata-Op: fix\nStrata-Actor: ethan\n\n"
    )
    events = [
        json.loads(line)
        for line in (repo.root / "events" / "fix" / "ethan.ndjson").read_text().splitlines()
    ]
    assert [e["ev"] for e in events] == ["record-amend"]
    assert events[0]["body"]["old"] == "Original title"
    assert events[0]["body"]["new"] == "Corrected title"

    page = _text(client.get(f"/records/{rid}"))
    assert "RECORD-AMEND" in page
    assert "Original title" in page and "Corrected title" in page


def test_a_correction_is_what_strata_fix_records(tmp_path: Path) -> None:
    via_cli = _review(tmp_path, "cli")
    via_web = _review(tmp_path, "web")
    rid = _id_of(via_cli, "Original title")
    assert rid == _id_of(via_web, "Original title")

    _cli(
        "--why", "fixing a typo in the title", "-C", str(via_cli.root), "fix", rid,
        "--field", "title", "--value", "Corrected title", "--by", "ethan",
    )  # fmt: skip
    _post(
        _client(via_web),
        f"/records/{rid}/fix",
        {"field": "title", "value": "Corrected title", "rationale": "fixing a typo in the title"},
    )

    assert committed_snapshot(via_cli.root) == committed_snapshot(via_web.root)


def test_a_field_strata_fix_refuses_is_refused_with_its_reason_and_nothing_is_recorded(
    tmp_path: Path,
) -> None:
    repo = _review(tmp_path)
    rid = _id_of(repo, "Original title")
    before = _count(repo)

    response = _post(
        _client(repo), f"/records/{rid}/fix", {"field": "author", "value": "x", "rationale": _WHY}
    )

    assert response.status_code == 422
    assert "cannot be corrected with `strata fix`" in _text(response)
    assert _count(repo) == before
    assert _clean(repo)


def test_a_correction_without_a_rationale_writes_nothing(tmp_path: Path) -> None:
    repo = _review(tmp_path)
    rid = _id_of(repo, "Original title")
    before = _count(repo)

    response = _post(
        _client(repo), f"/records/{rid}/fix", {"field": "title", "value": "x", "rationale": ""}
    )

    assert response.status_code == 422
    assert "a rationale is required" in _text(response)
    assert _count(repo) == before
    assert _clean(repo)


def test_a_correction_with_a_rationale_that_is_not_one_is_refused_in_the_commands_words(
    tmp_path: Path,
) -> None:
    repo = _review(tmp_path)
    rid = _id_of(repo, "Original title")

    response = _post(
        _client(repo),
        f"/records/{rid}/fix",
        {"field": "title", "value": "x", "rationale": "update"},
    )

    assert response.status_code == 422
    result = runner.invoke(
        app,
        ["--why", "update", "-C", str(repo.root), "fix", rid, "--field", "title", "--value", "x",
         "--by", "ethan"],
    )  # fmt: skip
    assert " ".join(result.output.split()).removeprefix("error: ") in _text(response)
    assert _clean(repo)


def test_a_correction_keeps_what_was_typed_when_it_is_turned_away(tmp_path: Path) -> None:
    repo = _review(tmp_path)
    rid = _id_of(repo, "Original title")

    response = _post(
        _client(repo),
        f"/records/{rid}/fix",
        {"field": "volume", "value": "12", "rationale": ""},
    )

    assert response.status_code == 422
    assert 'value="12"' in response.text
    assert '<option value="volume" selected>' in response.text


def test_a_correction_of_an_unknown_record_is_a_404(tmp_path: Path) -> None:
    repo = _review(tmp_path)

    response = _post(
        _client(repo),
        "/records/rec_nope/fix",
        {"field": "title", "value": "x", "rationale": _WHY},
    )

    assert response.status_code == 404
    assert _clean(repo)


# ----------------------------------------------------------------------------- adding a criterion

_CRITERION = {
    "kind": "exclusion",
    "label": "Not empirical",
    "definition": "Not an empirical study",
    "applies_at": ["title-abstract"],
    "rationale": "adding the empirical-study criterion",
}


def test_the_criterion_form_says_it_is_recorded_as_tightened(tmp_path: Path) -> None:
    repo = _review(tmp_path)

    page = _client(repo).get("/criteria/new")

    assert page.status_code == 200
    text = _text(page)
    assert "recorded as tightened" in text
    assert 'name="applies_at" value="title-abstract"' in page.text
    assert 'name="applies_at" value="full-text"' in page.text
    assert 'href="/criteria/new"' in _client(repo).get("/criteria").text


def test_adding_a_criterion_records_it_and_advances_the_version(tmp_path: Path) -> None:
    repo = _review(tmp_path)
    client = _client(repo)
    before = _count(repo)

    response = _post(client, "/criteria", _CRITERION)

    assert response.status_code == 303
    assert response.headers["location"] == "/criteria?added=EXC-01"
    assert _count(repo) == before + 1
    assert _clean(repo)
    assert _head(repo) == (
        "criteria-add(EXC-01): add criterion EXC-01\n\nadding the empirical-study criterion\n\n"
        "Strata-Op: criteria-add\nStrata-Criterion: EXC-01\nStrata-Actor: ethan\n\n"
    )
    listing = _text(client.get(response.headers["location"]))
    assert "Not empirical" in listing
    assert "Added EXC-01" in listing and "recorded as tightened" in listing


def test_the_added_note_names_only_a_criterion_that_exists(tmp_path: Path) -> None:
    repo = _review(tmp_path)

    page = _client(repo).get("/criteria?added=EXC-99")

    assert 'data-testid="added-note"' not in page.text


def test_a_criterion_is_what_strata_criteria_add_records_and_stales_the_same_decisions(
    tmp_path: Path,
) -> None:
    def prepare(name: str) -> Repo:
        repo = _review(tmp_path, name)
        _cli(
            "--why", "adding the population criterion", "-C", str(repo.root), "criteria", "add",
            "--kind", "inclusion", "--label", "Adults only", "--definition", "Participants are 18+",
            "--applies-at", "title-abstract", "--by", "ethan",
        )  # fmt: skip
        # Both reviewers: a decision only goes stale once its record is resolved.
        for title in ("Original title", "Second paper"):
            for reviewer in ("ethan", "sam"):
                screening_mod.record_screen_decision(
                    repo,
                    stage="title-abstract",
                    record_id=_id_of(repo, title),
                    decision="include",
                    actor=reviewer,
                    cited=["INC-01"],
                )
        gitio.add(repo.root, ["events"])
        gitio.commit(repo.root, "test: screening decisions")
        return repo

    via_cli = prepare("cli")
    via_web = prepare("web")
    assert rescreen_mod.compute_stale_records(via_cli) == []

    _cli(
        "--why", _CRITERION["rationale"], "-C", str(via_cli.root), "criteria", "add",
        "--kind", "exclusion", "--label", "Not empirical", "--definition", "Not an empirical study",
        "--applies-at", "title-abstract", "--by", "ethan",
    )  # fmt: skip
    assert _post(_client(via_web), "/criteria", _CRITERION).status_code == 303

    assert committed_snapshot(via_cli.root) == committed_snapshot(via_web.root)
    stale_cli = rescreen_mod.compute_stale_records(via_cli)
    assert stale_cli, "the comparison would prove nothing if no decision went stale"
    assert stale_cli == rescreen_mod.compute_stale_records(via_web)


def test_a_criterion_without_a_rationale_is_refused_and_the_protocol_is_unchanged(
    tmp_path: Path,
) -> None:
    repo = _review(tmp_path)
    criteria_file = repo.root / "protocol" / "criteria.yaml"
    before_file = criteria_file.read_text() if criteria_file.exists() else None
    before = _count(repo)

    response = _post(_client(repo), "/criteria", {**_CRITERION, "rationale": ""})

    assert response.status_code == 422
    assert "a rationale is required" in _text(response)
    assert _count(repo) == before
    assert _clean(repo)
    assert (criteria_file.read_text() if criteria_file.exists() else None) == before_file


def test_a_criterion_needs_a_rationale_even_when_the_review_does_not_require_one(
    tmp_path: Path,
) -> None:
    repo = _review(tmp_path)
    toml = repo.root / "strata.toml"
    toml.write_text(
        toml.read_text().replace("require_rationale = true", "require_rationale = false")
    )
    gitio.add(repo.root, ["strata.toml"])
    gitio.commit(repo.root, "test: rationale optional")

    response = _post(_client(repo), "/criteria", {**_CRITERION, "rationale": ""})

    assert response.status_code == 422
    assert _clean(repo)


def test_a_criterion_at_a_stage_that_is_not_configured_is_refused_with_the_reason(
    tmp_path: Path,
) -> None:
    repo = _review(tmp_path)

    response = _post(_client(repo), "/criteria", {**_CRITERION, "applies_at": ["nowhere"]})

    assert response.status_code == 422
    assert "unconfigured stage" in _text(response)
    assert _clean(repo)


def test_a_criterion_form_turned_away_keeps_what_was_typed(tmp_path: Path) -> None:
    repo = _review(tmp_path)

    response = _post(_client(repo), "/criteria", {**_CRITERION, "rationale": ""})

    assert "Not an empirical study" in response.text
    assert 'value="Not empirical"' in response.text
    assert re.search(r'value="title-abstract"\s+checked', response.text)
    assert re.search(r'value="exclusion"\s+checked', response.text)


# ----------------------------------------------------------------------------- assigning reviewers


def _assign(**overrides: Any) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "actors": ["ethan", "sam"],
        "filter": "",
        "rationale": "assigning both of us",
    }
    fields.update(overrides)
    return fields


def test_the_assign_page_shows_each_reviewers_queue_and_the_record_count(tmp_path: Path) -> None:
    repo = _review(tmp_path)

    page = _client(repo).get("/assign/title-abstract")

    assert page.status_code == 200
    text = _text(page)
    assert "2 records at this stage" in text
    assert "Ethan (ethan)" in text and "Sam (sam)" in text


def test_a_filter_preview_says_how_many_records_match_and_records_nothing(
    tmp_path: Path,
) -> None:
    repo = _review(tmp_path)
    before = _count(repo)

    page = _client(repo).get("/assign/title-abstract", params={"filter": "year >= 2010"})

    assert page.status_code == 200
    text = _text(page)
    assert "1 of 2 records match (nothing saved yet)" in text
    assert "Second paper" in text
    assert _count(repo) == before
    assert _clean(repo)


def test_a_filter_that_does_not_parse_shows_the_parsers_message(tmp_path: Path) -> None:
    repo = _review(tmp_path)

    page = _client(repo).get("/assign/title-abstract", params={"filter": "year >="})

    assert page.status_code == 200
    assert "invalid filter: expected a value, got ''" in _text(page)
    assert _clean(repo)


def test_assigning_two_reviewers_fills_both_queues(tmp_path: Path) -> None:
    repo = _review(tmp_path)
    client = _client(repo)
    before = _count(repo)

    response = _post(client, "/assign/title-abstract", _assign())

    assert response.status_code == 303
    assert response.headers["location"] == "/assign/title-abstract?done=1"
    assert _count(repo) == before + 1
    assert _clean(repo)
    assert _head(repo) == (
        "assign(title-abstract): assigned 2 title-abstract record(s)\n\nassigning both of us\n\n"
        "Strata-Op: assign\nStrata-Actor: ethan\nStrata-Actors: ethan,sam\n\n"
    )
    everyone = sorted(r["id"] for r in records_mod.read_records(repo))
    assert screening_mod.stage_queue(repo, "title-abstract", "ethan") == everyone
    assert screening_mod.stage_queue(repo, "title-abstract", "sam") == everyone
    page = _text(client.get(response.headers["location"]))
    assert "Assignment recorded" in page


def test_an_assignment_is_what_strata_assign_records(tmp_path: Path) -> None:
    via_cli = _review(tmp_path, "cli")
    via_web = _review(tmp_path, "web")

    _cli(
        "--why", "assigning both of us", "-C", str(via_cli.root), "assign", "title-abstract",
        "--actors", "ethan,sam", "--by", "ethan",
    )  # fmt: skip
    _post(_client(via_web), "/assign/title-abstract", _assign())

    assert committed_snapshot(via_cli.root) == committed_snapshot(via_web.root)


def test_an_assignment_limited_by_a_filter_is_what_strata_assign_records(tmp_path: Path) -> None:
    via_cli = _review(tmp_path, "cli")
    via_web = _review(tmp_path, "web")

    _cli(
        "--why", "only sam sees the older paper", "-C", str(via_cli.root), "assign",
        "title-abstract", "--actors", "sam", "--by", "ethan", "--filter", "year < 2010",
    )  # fmt: skip
    _post(
        _client(via_web),
        "/assign/title-abstract",
        _assign(actors=["sam"], filter="year < 2010", rationale="only sam sees the older paper"),
    )

    assert committed_snapshot(via_cli.root) == committed_snapshot(via_web.root)
    older = _id_of(via_web, "Original title")
    assert screening_mod.stage_queue(via_web, "title-abstract", "sam") == sorted(
        r["id"] for r in records_mod.read_records(via_web)
    )
    assert older not in screening_mod.stage_queue(via_web, "title-abstract", "ethan")


def test_assigning_with_a_filter_that_does_not_parse_records_nothing(tmp_path: Path) -> None:
    repo = _review(tmp_path)
    before = _count(repo)

    response = _post(_client(repo), "/assign/title-abstract", _assign(filter="year >="))

    assert response.status_code == 422
    assert "invalid filter: expected a value, got ''" in _text(response)
    assert _count(repo) == before
    assert _clean(repo)


def test_assigning_to_records_that_match_nothing_is_refused_in_the_commands_words(
    tmp_path: Path,
) -> None:
    repo = _review(tmp_path)

    response = _post(_client(repo), "/assign/title-abstract", _assign(filter="year > 2100"))

    assert response.status_code == 422
    assert "no records matched to assign" in _text(response)
    assert _clean(repo)


def test_assigning_someone_who_is_not_an_actor_or_no_one_is_refused(tmp_path: Path) -> None:
    repo = _review(tmp_path)
    client = _client(repo)

    ghost = _post(client, "/assign/title-abstract", _assign(actors=["ghost"]))
    nobody = _post(client, "/assign/title-abstract", {"filter": "", "rationale": _WHY})

    assert ghost.status_code == 422 and "not an actor of this review: ghost" in _text(ghost)
    assert nobody.status_code == 422 and "Choose at least one reviewer" in _text(nobody)
    assert _clean(repo)


def test_assigning_without_a_rationale_writes_nothing(tmp_path: Path) -> None:
    repo = _review(tmp_path)
    before = _count(repo)

    response = _post(_client(repo), "/assign/title-abstract", _assign(rationale=""))

    assert response.status_code == 422
    assert _count(repo) == before
    assert _clean(repo)


def test_an_unknown_stage_is_a_404_on_both_verbs(tmp_path: Path) -> None:
    repo = _review(tmp_path)
    client = _client(repo)

    assert client.get("/assign/nowhere").status_code == 404
    assert _post(client, "/assign/nowhere", _assign()).status_code == 404


def test_the_dashboard_links_to_assignment_for_every_stage(tmp_path: Path) -> None:
    repo = _review(tmp_path)

    page = _client(repo).get("/")

    assert 'href="/assign/title-abstract"' in page.text
    assert 'href="/assign/full-text"' in page.text
