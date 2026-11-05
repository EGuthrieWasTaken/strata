"""The suggestions screen and the labelling of agent work in the web interface:
openspec:web-ui#suggestions-screen, openspec:web-ui#agent-work-is-labelled."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from strata import gitio
from strata.core import agents as agents_mod
from strata.core.events import agent_scope
from strata.core.manifest import load_manifest_doc, write_manifest
from strata.core.repo import Repo, open_repo
from strata.protocol import criteria as criteria_mod
from strata.protocol import pool as pool_mod
from strata.protocol import screening as screening_mod
from strata.protocol import suggestions as sugg
from strata.web.app import create_app
from tests.unit._m3 import decide
from tests.unit._m6 import AGENT, MODEL, STAGE, context, suggest_screen, suggest_world

_TOKEN = "test-session-token-0123456789"
WHY = "Agree: the abstract meets the population criterion."


@pytest.fixture(scope="module")
def template(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, list[str]]:
    repo, ids = suggest_world(tmp_path_factory.mktemp("template"))
    doc = load_manifest_doc(repo.root)
    doc["ai"]["show_suggestions"] = "always"  # so the list does not depend on who has decided
    write_manifest(repo.root, doc)
    return repo.root, ids


@pytest.fixture
def world(template: tuple[Path, list[str]], tmp_path: Path) -> tuple[Repo, list[str]]:
    source, ids = template
    target = tmp_path / "review"
    shutil.copytree(source, target)
    return open_repo(target), ids


def _client(repo: Repo, *, actor: str = "ethan") -> TestClient:
    app = create_app(repo_root=repo.root, actor=actor, session_token=_TOKEN)
    client = TestClient(app, base_url="http://127.0.0.1:8000")
    assert client.get(f"/?token={_TOKEN}").status_code == 200
    return client


def _post(client: TestClient, path: str, **data: str) -> object:
    return client.post(path, data={"csrf_token": _TOKEN, **data}, follow_redirects=False)


# ----------------------------------------------------------------------- the screen


def test_the_screen_lists_what_a_person_needs_to_decide(world: tuple[Repo, list[str]]) -> None:
    repo, ids = world
    suggest_screen(repo, ids[0], "include", rationale="Meets the population criterion.")
    page = _client(repo).get("/suggestions")
    assert page.status_code == 200
    text = page.text
    assert f"include {ids[0]} at {STAGE}" in text
    assert "Meets the population criterion." in text
    assert f"model {MODEL}" in text and "(self-reported)" in text
    assert "invoked by sam" in text
    assert 'data-testid="ai-label"' in text
    assert "Nothing in them has taken effect" in text
    assert 'action="/suggestions/' in text


def test_a_criteria_suggestion_shows_what_it_would_make_stale(
    world: tuple[Repo, list[str]],
) -> None:
    repo, ids = world
    decide(repo, STAGE, ids, "include")
    sugg.make_suggestion(
        repo,
        context=context(),
        op="criteria-edit",
        args={"criterion": "EXC-01", "direction": "tightened", "definition": "A tighter text."},
        rationale="Too loose.",
    )
    text = _client(repo).get("/suggestions").text
    assert "What it would make stale" in text
    assert "4 decisions" in text


def test_adopting_in_the_browser_records_the_persons_own_opinion(
    world: tuple[Repo, list[str]],
) -> None:
    repo, ids = world
    event = suggest_screen(repo, ids[0], "include")
    client = _client(repo)
    response = _post(client, f"/suggestions/{event['id']}/adopt", rationale=WHY)
    assert response.status_code == 303  # type: ignore[attr-defined]
    repo = open_repo(repo.root)
    (screen,) = screening_mod.all_screen_events(repo, STAGE)
    assert (screen["actor"], screen["body"]["decision"]) == ("ethan", "include")
    assert "agent" not in screen
    assert not sugg.pending(repo)
    assert f"Strata-Suggestion: {event['id']}" in gitio.commit_message(repo.root, "HEAD")
    assert "No suggestions waiting" in client.get("/suggestions").text


def test_adopting_in_the_browser_is_the_same_as_on_the_command_line(
    world: tuple[Repo, list[str]],
) -> None:
    """Same function, same event body: compare with a second suggestion adopted through the core."""
    from strata.core import agent_ops

    repo, ids = world
    via_web = suggest_screen(repo, ids[0], "include")
    via_core = suggest_screen(repo, ids[1], "include")
    _post(_client(repo), f"/suggestions/{via_web['id']}/adopt", rationale=WHY)
    agent_ops.adopt(open_repo(repo.root), via_core["id"], by="ethan", rationale=WHY)
    events = screening_mod.all_screen_events(open_repo(repo.root), STAGE)
    bodies = [{k: v for k, v in e["body"].items() if k != "record"} for e in events]
    assert len(bodies) == 2 and bodies[0] == bodies[1]


def test_rejecting_without_a_reason_is_refused_and_the_suggestion_stays(
    world: tuple[Repo, list[str]],
) -> None:
    repo, ids = world
    event = suggest_screen(repo, ids[0])
    response = _post(_client(repo), f"/suggestions/{event['id']}/reject", reason="")
    assert response.status_code == 422  # type: ignore[attr-defined]
    assert "needs a reason" in response.text  # type: ignore[attr-defined]
    assert len(sugg.pending(open_repo(repo.root))) == 1


def test_rejecting_keeps_the_reason(world: tuple[Repo, list[str]]) -> None:
    repo, ids = world
    event = suggest_screen(repo, ids[0])
    response = _post(
        _client(repo), f"/suggestions/{event['id']}/reject", reason="The abstract is off topic."
    )
    assert response.status_code == 303  # type: ignore[attr-defined]
    item = sugg.get_suggestion(open_repo(repo.root), event["id"])
    assert (item.status, item.resolution["reason"]) == ("rejected", "The abstract is off topic.")  # type: ignore[index]


def test_adopting_without_a_rationale_is_refused(world: tuple[Repo, list[str]]) -> None:
    repo, ids = world
    event = suggest_screen(repo, ids[0])
    response = _post(_client(repo), f"/suggestions/{event['id']}/adopt", rationale="")
    assert response.status_code == 422  # type: ignore[attr-defined]
    assert not screening_mod.all_screen_events(repo, STAGE)


def test_when_the_criteria_moved_the_screen_asks_for_confirmation(
    world: tuple[Repo, list[str]],
) -> None:
    repo, ids = world
    event = suggest_screen(repo, ids[0])
    criteria_mod.retire_criterion(repo, "EXC-02", actor="ethan", rationale="Duplicates EXC-01.")
    client = _client(repo)
    refused = _post(client, f"/suggestions/{event['id']}/adopt", rationale=WHY)
    assert refused.status_code == 409  # type: ignore[attr-defined]
    assert "criteria changed from v2 to v3" in refused.text  # type: ignore[attr-defined]
    assert 'name="confirm"' in refused.text  # type: ignore[attr-defined]
    assert not screening_mod.all_screen_events(open_repo(repo.root), STAGE)
    done = _post(client, f"/suggestions/{event['id']}/adopt", rationale=WHY, confirm="1")
    assert done.status_code == 303  # type: ignore[attr-defined]


def test_a_hostile_rationale_is_escaped(world: tuple[Repo, list[str]]) -> None:
    repo, ids = world
    hostile = '<script>alert("x")</script> & <img src=x onerror=alert(1)>'
    suggest_screen(repo, ids[0], rationale=hostile)
    text = _client(repo).get("/suggestions").text
    assert "<script>alert" not in text
    assert "<img src=x" not in text
    assert "&lt;script&gt;" in text


def test_a_hostile_suggestion_id_cannot_inject_markup(world: tuple[Repo, list[str]]) -> None:
    repo, _ = world
    response = _post(
        _client(repo), "/suggestions/%3Cscript%3E/adopt", rationale="A reasonable reason."
    )
    assert response.status_code == 422  # type: ignore[attr-defined]
    assert "<script>" not in response.text  # type: ignore[attr-defined]


def test_a_blinded_reviewer_does_not_see_suggestions_about_records_they_have_not_decided(
    world: tuple[Repo, list[str]],
) -> None:
    repo, ids = world
    doc = load_manifest_doc(repo.root)
    doc["ai"]["show_suggestions"] = "after-own-decision"
    write_manifest(repo.root, doc)
    repo = open_repo(repo.root)
    suggest_screen(repo, ids[0])
    page = _client(repo).get("/suggestions").text
    assert f"include {ids[0]}" not in page
    assert "No suggestions waiting" in page
    assert "cannot influence you" in page
    decide(repo, STAGE, ids[:1], "include", actors=("ethan",))
    assert f"include {ids[0]}" in _client(repo).get("/suggestions").text


def test_an_observer_sees_the_list_but_no_forms(world: tuple[Repo, list[str]]) -> None:
    from strata.core.actor import add_actor

    repo, ids = world
    add_actor(repo, handle="olive", name="Olive", role="observer")
    suggest_screen(repo, ids[0])
    page = _client(open_repo(repo.root), actor="olive").get("/suggestions").text
    assert "cannot adopt or reject" in page
    assert 'name="rationale"' not in page


def test_a_review_without_ai_says_so(tmp_path: Path) -> None:
    from tests.unit._m3 import init_review

    repo = init_review(tmp_path)
    page = _client(repo).get("/suggestions").text
    assert "not enabled" in page
    assert "strata ai enable" in page


# ------------------------------------------------------------------------- the labels


def test_the_dashboard_says_ai_is_on_the_policy_and_links_to_suggestions(
    world: tuple[Repo, list[str]],
) -> None:
    repo, ids = world
    suggest_screen(repo, ids[0])
    text = _client(repo).get("/").text
    assert "AI participation is on" in text
    assert "screening: suggest" in text and "criteria: suggest" in text
    assert "1 suggestion waiting" in text
    assert 'href="/suggestions"' in text


def test_the_dashboard_says_when_ai_is_off(tmp_path: Path) -> None:
    from tests.unit._m3 import init_review

    text = _client(init_review(tmp_path)).get("/").text
    assert "AI participation is off for this review" in text
    assert "/suggestions" not in text


def _count_review(world: tuple[Repo, list[str]]) -> tuple[Repo, list[str]]:
    """`ethan` and the agent are assigned to every record; the agent excludes, ethan includes."""
    repo, ids = world
    doc = load_manifest_doc(repo.root)
    doc["screening"]["assignment"] = {STAGE: ["ethan", AGENT]}
    doc["ai"]["policy"]["screening"] = "count"
    write_manifest(repo.root, doc)
    repo = open_repo(repo.root)
    decide(repo, STAGE, ids[:1], "include", actors=("ethan",))
    ctx = agents_mod.AgentContext(
        actor=AGENT, model=MODEL, invoked_by="sam", client_name="claude-code", client_version="2.1"
    )
    with agent_scope(AGENT, ctx.envelope_value()):
        screening_mod.record_screen_decision(
            repo, stage=STAGE, record_id=ids[0], decision="exclude", actor=AGENT, cited=["EXC-01"]
        )
    pool_mod.regenerate_all(repo)
    return open_repo(repo.root), ids


def test_the_record_timeline_labels_the_agents_decision(world: tuple[Repo, list[str]]) -> None:
    repo, ids = _count_review(world)
    text = _client(repo).get(f"/records/{ids[0]}").text
    assert text.count('data-testid="ai-label"') >= 1
    assert f"model {MODEL}" in text and "(self-reported)" in text
    assert "via claude-code 2.1" in text and "invoked by sam" in text


def test_the_adjudication_screen_labels_each_opinion_as_a_persons_or_an_ais(
    world: tuple[Repo, list[str]],
) -> None:
    repo, ids = _count_review(world)
    page = _client(repo).get(f"/adjudicate/{STAGE}")
    assert page.status_code == 200
    text = page.text
    assert text.count('data-testid="ai-label"') == 1
    assert text.count('data-testid="person-label"') == 1
    assert "<strong>AI</strong>" in text and "<strong>Person</strong>" in text  # words, not colour


def test_history_labels_a_commit_made_for_an_agent(world: tuple[Repo, list[str]]) -> None:
    repo, ids = world
    event = suggest_screen(repo, ids[0])
    _post(_client(repo), f"/suggestions/{event['id']}/adopt", rationale=WHY)
    text = _client(open_repo(repo.root)).get("/history").text
    assert f"adopted from a suggestion by {AGENT}" in text
