"""`strata suggestions list|show|adopt|reject` and the AI label in `strata why`:
openspec:cli#ai-participation-commands, openspec:ai-suggestions."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from strata import gitio
from strata.cli.main import (
    EXIT_CONFLICT,
    EXIT_OK,
    EXIT_RATIONALE_REFUSED,
    EXIT_USAGE,
    app,
)
from strata.core import agents as agents_mod
from strata.core.events import agent_scope
from strata.core.manifest import load_manifest_doc, write_manifest
from strata.core.repo import Repo, open_repo
from strata.protocol import criteria as criteria_mod
from strata.protocol import pool as pool_mod
from strata.protocol import screening as screening_mod
from strata.protocol import suggestions as sugg
from tests.unit._m3 import decide
from tests.unit._m6 import AGENT, MODEL, STAGE, suggest_screen, suggest_world

runner = CliRunner()
WHY = "Agree: the abstract meets the population criterion."


@pytest.fixture(scope="module")
def template(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, list[str]]:
    repo, ids = suggest_world(tmp_path_factory.mktemp("template"))
    return repo.root, ids


@pytest.fixture
def world(template: tuple[Path, list[str]], tmp_path: Path) -> tuple[Repo, list[str]]:
    source, ids = template
    target = tmp_path / "review"
    shutil.copytree(source, target)
    return open_repo(target), ids


class _Out:
    def __init__(self, result: object) -> None:
        self.exit_code: int = result.exit_code  # type: ignore[attr-defined]
        self.output = " ".join(str(result.output).split())  # type: ignore[attr-defined]


def _run(repo: Repo, *args: str, why: str | None = None, expect: int = EXIT_OK) -> _Out:
    prefix = ["-C", str(repo.root)] + (["--why", why] if why else [])
    result = runner.invoke(app, [*prefix, *args])
    assert result.exit_code == expect, result.output
    return _Out(result)


def _json(repo: Repo, *args: str, why: str | None = None) -> object:
    return json.loads(_run(repo, "--json", *args, why=why).output)


def _open_up(repo: Repo) -> Repo:
    """Let reviewers see suggestions at once, so listing does not depend on who has decided."""
    doc = load_manifest_doc(repo.root)
    doc["ai"]["show_suggestions"] = "always"
    write_manifest(repo.root, doc)
    return open_repo(repo.root)


def test_list_prints_each_pending_suggestion_with_model_invoker_operation_and_target(
    world: tuple[Repo, list[str]],
) -> None:
    repo, ids = world
    repo = _open_up(repo)
    event = suggest_screen(repo, ids[0], "include")
    (item,) = _json(repo, "suggestions", "list")  # type: ignore[misc]
    assert item["id"] == event["id"]
    assert item["model"] == MODEL
    assert item["model_is_self_reported"] is True
    assert item["invoked_by"] == "sam"
    assert item["agent"] == AGENT
    assert item["client"] == {"name": "claude-code", "version": "2.1.3"}
    assert item["op"] == "screen"
    assert item["kind"] == "screening"
    assert item["target"] == f"screen:{STAGE}:{ids[0]}"
    assert item["status"] == "pending"
    assert item["args"] == {"stage": STAGE, "record": ids[0], "decision": "include"}
    assert item["rationale"]
    assert item["record"] == ids[0] and item["stage"] == STAGE


def test_list_in_words_says_whose_idea_it_was_and_that_the_model_is_self_reported(
    world: tuple[Repo, list[str]],
) -> None:
    repo, ids = world
    repo = _open_up(repo)
    suggest_screen(repo, ids[0])
    text = _run(repo, "suggestions", "list").output
    assert f"include {ids[0]} at {STAGE}" in text
    assert f"by {AGENT} (model {MODEL}, self-reported; invoked by sam)" in text


def test_list_with_nothing_waiting_says_so(world: tuple[Repo, list[str]]) -> None:
    assert "no suggestions waiting" in _run(world[0], "suggestions", "list").output
    assert _json(world[0], "suggestions", "list") == []


def test_list_hides_what_blinding_hides_until_the_reviewer_has_decided(
    world: tuple[Repo, list[str]],
) -> None:
    repo, ids = world
    suggest_screen(repo, ids[0])
    assert _json(repo, "suggestions", "list") == []
    assert _json(repo, "suggestions", "list", "--by", "ethan") == []
    decide(repo, STAGE, ids[:1], "include", actors=("ethan",))
    assert len(_json(repo, "suggestions", "list", "--by", "ethan")) == 1  # type: ignore[arg-type]
    assert _json(repo, "suggestions", "list", "--by", "sam") == []


def test_list_all_includes_what_became_of_each_but_still_hides_the_blinded(
    world: tuple[Repo, list[str]],
) -> None:
    repo, ids = world
    repo = _open_up(repo)
    first = suggest_screen(repo, ids[0])
    suggest_screen(repo, ids[1])
    _run(repo, "suggestions", "reject", first["id"], "--by", "sam", why="Not convinced by this.")
    statuses = {s["id"]: s["status"] for s in _json(repo, "suggestions", "list", "--all")}  # type: ignore[union-attr]
    assert sorted(statuses.values()) == ["pending", "rejected"]
    assert statuses[first["id"]] == "rejected"


def test_show_gives_the_proposal_the_reasons_and_the_outcome(
    world: tuple[Repo, list[str]],
) -> None:
    repo, ids = world
    repo = _open_up(repo)
    event = suggest_screen(repo, ids[0], "include", rationale="Meets the population criterion.")
    text = _run(repo, "suggestions", "show", event["id"][:12]).output
    assert "status: pending" in text
    assert "reason given: Meets the population criterion." in text
    assert "made under criteria v2" in text
    _run(repo, "suggestions", "adopt", event["id"], "--by", "ethan", why=WHY)
    shown = _json(repo, "suggestions", "show", event["id"])
    assert shown["status"] == "adopted"  # type: ignore[index]
    assert shown["resolution"]["by"] == "ethan"  # type: ignore[index]
    assert shown["resolution"]["reason"] == WHY  # type: ignore[index]
    assert "-> ev_" in _run(repo, "suggestions", "show", event["id"]).output


def test_show_does_not_reveal_a_blinded_pending_suggestion(
    world: tuple[Repo, list[str]],
) -> None:
    repo, ids = world
    event = suggest_screen(repo, ids[0])
    out = _run(repo, "suggestions", "show", event["id"], expect=EXIT_USAGE)
    assert "blinded" in out.output


def test_show_follows_the_same_blinding_as_list_for_the_person_looking(
    world: tuple[Repo, list[str]],
) -> None:
    repo, ids = world
    event = suggest_screen(repo, ids[0])
    decide(repo, STAGE, ids[:1], "include", actors=("ethan",))
    assert len(_json(repo, "suggestions", "list", "--by", "ethan")) == 1  # type: ignore[arg-type]
    shown = _json(repo, "suggestions", "show", event["id"], "--by", "ethan")
    assert shown["id"] == event["id"]  # type: ignore[index]
    _run(repo, "suggestions", "show", event["id"], "--by", "sam", expect=EXIT_USAGE)


def test_show_a_criteria_suggestion_prints_its_impact(world: tuple[Repo, list[str]]) -> None:
    repo, ids = world
    decide(repo, STAGE, ids, "include")
    event = sugg.make_suggestion(
        repo,
        context=agents_mod.AgentContext(actor=AGENT, model=MODEL, invoked_by="sam"),
        op="criteria-edit",
        args={"criterion": "EXC-01", "direction": "tightened", "definition": "A tighter text."},
        rationale="Too loose.",
    )
    text = _run(repo, "suggestions", "show", event["id"]).output
    assert "impact: {" in text and '"stale_decisions": 4' in text


def test_adopting_records_it_as_the_persons_and_marks_the_suggestion(
    world: tuple[Repo, list[str]],
) -> None:
    repo, ids = world
    repo = _open_up(repo)
    event = suggest_screen(repo, ids[0], "include")
    out = _run(repo, "suggestions", "adopt", event["id"], "--by", "ethan", why=WHY)
    assert f"adopted {event['id']}: recorded as ethan's own" in out.output
    repo = open_repo(repo.root)
    (screen,) = screening_mod.all_screen_events(repo, STAGE)
    assert (screen["actor"], screen["body"]["decision"]) == ("ethan", "include")
    assert "agent" not in screen
    assert not sugg.pending(repo)
    message = gitio.commit_message(repo.root, "HEAD")
    assert WHY in message and f"Strata-Suggestion: {event['id']}" in message


def test_adopting_as_json_says_which_events_were_written(world: tuple[Repo, list[str]]) -> None:
    repo, ids = world
    repo = _open_up(repo)
    event = suggest_screen(repo, ids[0])
    payload = _json(repo, "suggestions", "adopt", event["id"], "--by", "ethan", why=WHY)
    assert payload["suggestion"] == event["id"] and payload["by"] == "ethan"  # type: ignore[index]
    assert len(payload["events"]) == 1  # type: ignore[index]


def test_adopting_without_a_rationale_is_refused_and_writes_nothing(
    world: tuple[Repo, list[str]],
) -> None:
    repo, ids = world
    repo = _open_up(repo)
    event = suggest_screen(repo, ids[0])
    _run(repo, "suggestions", "adopt", event["id"], "--by", "ethan", expect=EXIT_RATIONALE_REFUSED)
    assert not screening_mod.all_screen_events(repo, STAGE)
    assert len(sugg.pending(repo)) == 1


def test_adopting_never_goes_without_a_commit(world: tuple[Repo, list[str]]) -> None:
    repo, ids = world
    repo = _open_up(repo)
    event = suggest_screen(repo, ids[0])
    out = _run(
        repo,
        "--no-commit",
        "suggestions",
        "adopt",
        event["id"],
        "--by",
        "ethan",
        why=WHY,
        expect=EXIT_USAGE,
    )
    assert "always commits" in out.output
    assert not screening_mod.all_screen_events(repo, STAGE)


def test_adopting_after_the_criteria_moved_needs_confirmation(
    world: tuple[Repo, list[str]],
) -> None:
    repo, ids = world
    repo = _open_up(repo)
    event = suggest_screen(repo, ids[0])
    criteria_mod.retire_criterion(repo, "EXC-02", actor="ethan", rationale="Duplicates EXC-01.")
    out = _run(
        repo, "suggestions", "adopt", event["id"], "--by", "ethan", why=WHY, expect=EXIT_CONFLICT
    )
    assert "criteria changed from v2 to v3 (EXC-02)" in out.output
    assert "confirm" in out.output
    assert not screening_mod.all_screen_events(repo, STAGE)
    _run(repo, "suggestions", "adopt", event["id"], "--by", "ethan", "--confirm", why=WHY)
    assert len(screening_mod.all_screen_events(open_repo(repo.root), STAGE)) == 1


def test_an_observer_adopting_is_refused(world: tuple[Repo, list[str]]) -> None:
    from strata.core.actor import add_actor

    repo, ids = world
    repo = _open_up(repo)
    add_actor(repo, handle="olive", name="Olive", role="observer")
    event = suggest_screen(repo, ids[0])
    out = _run(
        repo, "suggestions", "adopt", event["id"], "--by", "olive", why=WHY, expect=EXIT_USAGE
    )
    assert "observer" in out.output


def test_adopting_without_saying_who_in_a_team_says_to_use_by(
    world: tuple[Repo, list[str]],
) -> None:
    repo, ids = world
    repo = _open_up(repo)
    event = suggest_screen(repo, ids[0])
    out = _run(repo, "suggestions", "adopt", event["id"], why=WHY, expect=EXIT_USAGE)
    assert "--by HANDLE" in out.output


def test_rejecting_keeps_the_reason_and_decides_nothing(world: tuple[Repo, list[str]]) -> None:
    repo, ids = world
    repo = _open_up(repo)
    event = suggest_screen(repo, ids[0])
    _run(repo, "suggestions", "reject", event["id"], "--by", "sam", why="Off-topic abstract.")
    repo = open_repo(repo.root)
    (item,) = sugg.suggestions(repo)
    assert (item.status, item.resolution["reason"], item.resolution["by"]) == (  # type: ignore[index]
        "rejected",
        "Off-topic abstract.",
        "sam",
    )
    assert not screening_mod.all_screen_events(repo, STAGE)
    assert _json(repo, "suggestions", "list") == []


def test_rejecting_needs_a_reason(world: tuple[Repo, list[str]]) -> None:
    repo, ids = world
    repo = _open_up(repo)
    event = suggest_screen(repo, ids[0])
    _run(repo, "suggestions", "reject", event["id"], "--by", "sam", expect=EXIT_RATIONALE_REFUSED)
    assert len(sugg.pending(repo)) == 1


def test_an_unknown_suggestion_is_a_usage_error(world: tuple[Repo, list[str]]) -> None:
    for command in ("show", "adopt", "reject"):
        out = _run(world[0], "suggestions", command, "ev_nope", why=WHY, expect=EXIT_USAGE)
        assert "no suggestion" in out.output


# ----------------------------------------------------------------------- strata why


def test_why_labels_an_agents_decision_as_ai_with_model_and_invoker(
    world: tuple[Repo, list[str]],
) -> None:
    repo, ids = world
    doc = load_manifest_doc(repo.root)
    doc["screening"]["assignment"] = {STAGE: ["ethan", AGENT]}
    doc["ai"]["policy"]["screening"] = "count"
    write_manifest(repo.root, doc)
    repo = open_repo(repo.root)
    decide(repo, STAGE, ids[:1], "include", actors=("ethan",))
    context = agents_mod.AgentContext(
        actor=AGENT, model=MODEL, invoked_by="sam", client_name="claude-code", client_version="2.1"
    )
    with agent_scope(AGENT, context.envelope_value()):
        screening_mod.record_screen_decision(
            repo, stage=STAGE, record_id=ids[0], decision="include", actor=AGENT
        )
    pool_mod.regenerate_all(repo)

    text = _run(repo, "why", ids[0]).output
    assert "SCREEN" in text
    assert f"AI: model {MODEL} (self-reported) via claude-code 2.1, invoked by sam" in text
    entries = _json(repo, "why", ids[0])
    agent_entries = [e for e in entries if e.get("agent")]  # type: ignore[union-attr]
    assert [e["actor"] for e in agent_entries] == [AGENT]
    person = next(e for e in entries if e["actor"] == "ethan")  # type: ignore[union-attr]
    assert "agent" not in person


def test_why_shows_the_suggestion_and_the_persons_event_together(
    world: tuple[Repo, list[str]],
) -> None:
    repo, ids = world
    repo = _open_up(repo)
    event = suggest_screen(repo, ids[0], "include")
    _run(repo, "suggestions", "adopt", event["id"], "--by", "ethan", why=WHY)
    decide(repo, STAGE, ids[:1], "include", actors=("sam",))
    entries = _json(repo, "why", ids[0])
    kinds = [e["kind"] for e in entries]  # type: ignore[union-attr]
    assert {"suggestion", "suggestion-resolve", "screen"} <= set(kinds)
    resolve = next(e for e in entries if e["kind"] == "suggestion-resolve")  # type: ignore[union-attr]
    screen = next(  # type: ignore[union-attr]
        e
        for e in entries
        if e["kind"] == "screen" and e["actor"] == "ethan"  # type: ignore[union-attr]
    )
    assert resolve["detail"]["outcome"] == "adopted"
    assert resolve["actor"] == "ethan"
    assert len(resolve["detail"]["result"]) == 1
    suggestion = next(e for e in entries if e["kind"] == "suggestion")  # type: ignore[union-attr]
    assert suggestion["agent"]["model"] == MODEL
    assert "agent" not in screen
