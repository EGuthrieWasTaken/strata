"""`strata ai report|revoke`, `strata audit --ai` and the AI line of `strata status`:
openspec:ai-participation#revoking-an-agent, #the-ai-ledger-and-audit."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from strata import gitio
from strata.cli.main import EXIT_OK, EXIT_RATIONALE_REFUSED, EXIT_USAGE, app
from strata.core import agents as agents_mod
from strata.core.manifest import load_manifest_doc, write_manifest
from strata.core.repo import Repo, open_repo
from strata.protocol import pool as pool_mod
from strata.protocol import rescreen as rescreen_mod
from strata.protocol import screening as screening_mod
from tests.unit._m3 import decide, init_review
from tests.unit._m6 import AGENT, MODEL, STAGE, context, suggest_world

runner = CliRunner()
WHY = "We no longer want AI help on this review."


@pytest.fixture(scope="module")
def template(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, list[str]]:
    repo, ids = suggest_world(tmp_path_factory.mktemp("template"), records=8)
    doc = load_manifest_doc(repo.root)
    doc["screening"]["assignment"] = {STAGE: ["ethan", AGENT]}
    doc["ai"]["policy"]["screening"] = "count"
    write_manifest(repo.root, doc)
    return repo.root, ids


@pytest.fixture
def world(template: tuple[Path, list[str]], tmp_path: Path) -> tuple[Repo, list[str]]:
    source, ids = template
    target = tmp_path / "review"
    shutil.copytree(source, target)
    return open_repo(target), ids


def _run(repo: Repo, *args: str, why: str | None = None, expect: int = EXIT_OK) -> str:
    prefix = ["-C", str(repo.root)] + (["--why", why] if why else [])
    result = runner.invoke(app, [*prefix, *args])
    assert result.exit_code == expect, result.output
    return " ".join(result.output.split())


def _agent_decides(
    repo: Repo, ids: list[str], decision: str = "include", invoker: str = "sam"
) -> None:
    with agents_mod.acting_as(context(invoked_by=invoker)):
        for record_id in ids:
            screening_mod.record_screen_decision(
                repo,
                stage=STAGE,
                record_id=record_id,
                decision=decision,  # type: ignore[arg-type]
                actor=AGENT,
                cited=["EXC-01"] if decision == "exclude" else None,
            )
    pool_mod.regenerate_all(repo)


# -------------------------------------------------------------------------- ai report


def test_the_report_of_a_review_without_agents_says_so(tmp_path: Path) -> None:
    repo = init_review(tmp_path)
    assert "no AI agent is registered" in _run(repo, "ai", "report")
    assert _run(repo, "--json", "ai", "report") == '{"agents": []}'


def test_the_report_lists_figures_per_agent_and_kind_invoker_and_dates(
    world: tuple[Repo, list[str]],
) -> None:
    repo, ids = world
    _agent_decides(repo, ids[:3], invoker="ethan")
    _agent_decides(repo, ids[3:5], invoker="sam")
    text = _run(repo, "ai", "report")
    assert f"{AGENT} model {MODEL} (self-reported)" in text
    assert "invoked by ethan, sam" in text
    assert "via claude-code 2.1.3" in text
    assert "screening counted 5 (5 as a reviewer, 0 later changed by a person)" in text
    payload = json.loads(_run(repo, "--json", "ai", "report"))
    (agent,) = payload["agents"]
    assert (agent["actor"], agent["model"], agent["role"]) == (AGENT, MODEL, "screener")
    assert agent["invokers"] == ["ethan", "sam"]
    assert agent["kinds"]["screening"]["counted"] == 5
    assert agent["first_active"] == agent["last_active"]


def test_an_agent_that_has_done_nothing_says_so(world: tuple[Repo, list[str]]) -> None:
    assert "has done nothing yet" in _run(world[0], "ai", "report")


# ------------------------------------------------------------------------- audit --ai


def test_the_ai_audit_samples_only_decisions_no_person_has_decided(
    world: tuple[Repo, list[str]],
) -> None:
    repo, ids = world
    _agent_decides(repo, ids[:6])
    decide(repo, STAGE, ids[:2], "include", actors=("ethan",))  # a person looked at two of them
    payload = json.loads(_run(repo, "--json", "audit", "--ai", "--sample", "20", "--seed", "7"))
    sampled = sorted(item["record"] for item in payload["items"])
    assert sampled == sorted(ids[2:6])
    assert {item["decision"] for item in payload["items"]} == {"include"}
    assert {item["actor"] for item in payload["items"]} == {AGENT}


def test_the_same_seed_gives_the_same_sample_and_another_seed_may_not(
    world: tuple[Repo, list[str]],
) -> None:
    repo, ids = world
    _agent_decides(repo, ids)
    first = _run(repo, "--json", "audit", "--ai", "--sample", "3", "--seed", "7")
    again = _run(repo, "--json", "audit", "--ai", "--sample", "3", "--seed", "7")
    assert first == again
    assert len(json.loads(first)["items"]) == 3
    assert json.loads(first)["seed"] == 7
    others = {
        _run(repo, "--json", "audit", "--ai", "--sample", "3", "--seed", str(s)) for s in range(8)
    }
    assert len(others) > 1  # the seed does choose the sample


def test_a_sample_larger_than_the_pool_is_the_whole_pool(world: tuple[Repo, list[str]]) -> None:
    repo, ids = world
    _agent_decides(repo, ids[:2])
    assert len(json.loads(_run(repo, "--json", "audit", "--ai", "--sample", "20"))["items"]) == 2


def test_the_ai_audit_in_words_names_the_model_as_self_reported_and_the_seed(
    world: tuple[Repo, list[str]],
) -> None:
    repo, ids = world
    _agent_decides(repo, ids[:2])
    text = _run(repo, "audit", "--ai", "--sample", "5", "--seed", "11")
    assert "Sampling 2 AI decision(s) no person has independently decided (seed 11" in text
    assert f"included by {AGENT} (AI, model self-reported)" in text


def test_nothing_to_audit_says_so(world: tuple[Repo, list[str]]) -> None:
    assert "no AI decisions recorded yet" in _run(world[0], "audit", "--ai")


def test_audit_needs_exactly_one_of_its_modes(world: tuple[Repo, list[str]]) -> None:
    _run(world[0], "audit", expect=EXIT_USAGE)
    _run(world[0], "audit", "--ai", "--criteria", expect=EXIT_USAGE)


# --------------------------------------------------------------------------- ai revoke


def test_revoking_deactivates_and_marks_what_still_counted_with_the_reason(
    world: tuple[Repo, list[str]],
) -> None:
    repo, ids = world
    _agent_decides(repo, ids[:3])
    decide(repo, STAGE, ids[:3], "include", actors=("ethan",))  # all three resolve to include
    assert rescreen_mod.compute_stale_records(open_repo(repo.root)) == []
    out = _run(repo, "ai", "revoke", AGENT, "--by", "ethan", why=WHY)
    assert "revoked" in out and "3 decision(s) now wait in the stale queue" in out
    repo = open_repo(repo.root)
    stale = rescreen_mod.compute_stale_records(repo)
    assert sorted((s.record_id, s.reason) for s in stale) == sorted(
        (i, "agent-revoked") for i in ids[:3]
    )
    assert next(a for a in repo.config["actors"] if a["handle"] == AGENT)["role"] == "inactive"
    message = gitio.commit_message(repo.root, "HEAD")
    assert message.startswith(f"ai-revoke({AGENT}): revoke {AGENT}") and WHY in message
    assert "Strata-Revoked: claude-opus" in message and "Strata-Marked: 3" in message
    assert len(screening_mod.all_screen_events(repo, STAGE)) == 6  # its history is untouched
    assert "[revoked]" in _run(repo, "ai", "report")


def test_a_person_who_re_screens_a_marked_record_takes_it_off_the_queue(
    world: tuple[Repo, list[str]],
) -> None:
    repo, ids = world
    _agent_decides(repo, ids[:1])
    decide(repo, STAGE, ids[:1], "include", actors=("ethan",))
    _run(repo, "ai", "revoke", AGENT, "--by", "ethan", why=WHY)
    import time

    time.sleep(1.1)
    repo = open_repo(repo.root)
    screening_mod.record_screen_decision(
        repo, stage=STAGE, record_id=ids[0], decision="include", actor="ethan"
    )
    assert rescreen_mod.compute_stale_records(open_repo(repo.root)) == []


def test_a_decision_a_person_adjudicated_is_not_marked(world: tuple[Repo, list[str]]) -> None:
    from strata.protocol import adjudication as adjudication_mod

    repo, ids = world
    _agent_decides(repo, ids[:1], "include")
    decide(repo, STAGE, ids[:1], "exclude", actors=())  # nothing
    screening_mod.record_screen_decision(
        repo, stage=STAGE, record_id=ids[0], decision="exclude", actor="ethan", cited=["EXC-01"]
    )
    adjudication_mod.record_adjudication(
        repo,
        stage=STAGE,
        record_id=ids[0],
        decision="include",
        actor="ethan",
        rationale="Included.",
    )
    pool_mod.regenerate_all(repo)
    out = _run(repo, "ai", "revoke", AGENT, "--by", "ethan", why=WHY)
    assert "0 decision(s)" in out


def test_only_a_lead_can_revoke(world: tuple[Repo, list[str]]) -> None:
    repo, _ = world
    out = _run(repo, "ai", "revoke", AGENT, "--by", "sam", why=WHY, expect=EXIT_USAGE)
    assert "not a lead" in out
    out = _run(repo, "ai", "revoke", AGENT, "--by", AGENT, why=WHY, expect=EXIT_USAGE)
    assert "not a lead" in out
    assert (
        next(a for a in open_repo(repo.root).config["actors"] if a["handle"] == AGENT)["role"]
        != "inactive"
    )


def test_revoking_something_that_is_not_an_agent_or_twice_is_refused(
    world: tuple[Repo, list[str]],
) -> None:
    repo, _ = world
    assert "not an AI agent" in _run(
        repo, "ai", "revoke", "sam", "--by", "ethan", why=WHY, expect=EXIT_USAGE
    )
    _run(repo, "ai", "revoke", AGENT, "--by", "ethan", why=WHY)
    assert "already been revoked" in _run(
        repo, "ai", "revoke", AGENT, "--by", "ethan", why=WHY, expect=EXIT_USAGE
    )


def test_revoking_needs_the_leads_rationale_and_changes_nothing_without_it(
    world: tuple[Repo, list[str]],
) -> None:
    repo, _ = world
    _run(repo, "ai", "revoke", AGENT, "--by", "ethan", expect=EXIT_RATIONALE_REFUSED)
    assert (
        next(a for a in open_repo(repo.root).config["actors"] if a["handle"] == AGENT)["role"]
        != "inactive"
    )


def test_a_revoked_agent_can_write_nothing_more(world: tuple[Repo, list[str]]) -> None:
    repo, ids = world
    _run(repo, "ai", "revoke", AGENT, "--by", "ethan", why=WHY)
    with pytest.raises(agents_mod.AgentRefused, match="deactivated"):
        agents_mod.authorise(open_repo(repo.root), kind="screening", model=MODEL, invoked_by="sam")


# ------------------------------------------------------------------------------ status


def test_status_has_no_ai_line_for_a_review_that_never_enabled_it(tmp_path: Path) -> None:
    repo = init_review(tmp_path)
    assert "AI participation is" not in _run(repo, "status")
    assert json.loads(_run(repo, "--json", "status"))["ai"] is None


def test_status_shows_that_ai_is_on_the_policy_and_the_number_of_agent_events(
    world: tuple[Repo, list[str]],
) -> None:
    repo, ids = world
    _agent_decides(repo, ids[:3])
    assert (
        "AI participation is on (screening: count, criteria: suggest) · 3 agent event(s) · 0 suggestion(s) waiting"
        in _run(repo, "status")
    )
    ai: dict[str, Any] = json.loads(_run(repo, "--json", "status"))["ai"]
    assert ai == {
        "enabled": True,
        "policy": {"screening": "count", "criteria": "suggest"},
        "agent_events": 3,
        "suggestions_waiting": 0,
    }


def test_status_on_a_review_with_ai_on_and_every_kind_off_says_so(tmp_path: Path) -> None:
    repo, _ = suggest_world(tmp_path, policy={})
    assert "AI participation is on (every kind of work is off) · 0 agent event(s)" in _run(
        repo, "status"
    )
