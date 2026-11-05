"""Suggestions: openspec:ai-suggestions and the suggestion events of openspec:event-log."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest

from strata import gitio
from strata.core import agent_ops
from strata.core import events as events_mod
from strata.core.repo import Repo, open_repo
from strata.core.validate import SchemaValidationError, validate_event_body
from strata.core.verify import verify_repository
from strata.protocol import criteria as criteria_mod
from strata.protocol import pool as pool_mod
from strata.protocol import rescreen as rescreen_mod
from strata.protocol import screening as screening_mod
from strata.protocol import suggestions as sugg
from tests.unit._m3 import decide
from tests.unit._m6 import (
    AGENT,
    MODEL,
    STAGE,
    context,
    derived_bytes,
    suggest_screen,
    suggest_world,
)

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


def _commits(repo: Repo) -> list[str]:
    return gitio.log(repo.root, fmt="%H")


# ---------------------------------------------------------------------- the events (2.1)


@pytest.mark.req("E_SCHEMA")
def test_a_suggestion_without_an_op_is_rejected_on_write() -> None:
    with pytest.raises(SchemaValidationError, match="op"):
        validate_event_body("suggestion", {"args": {}, "rationale": "r", "criteria_version": 1})


@pytest.mark.req("E_SCHEMA")
def test_a_suggestion_without_an_op_is_rejected_on_load(world: tuple[Repo, list[str]]) -> None:
    repo, _ = world
    path = repo.path("events", "suggestion", f"{AGENT}.ndjson")
    with events_mod.agent_scope(AGENT, context().envelope_value()):
        events_mod.append_new_event(
            path,
            ev="suggestion",
            actor=AGENT,
            body={"args": {}, "rationale": "r", "criteria_version": 1},
        )
    report = verify_repository(repo, fast=True)
    assert any(i.code == "E_SCHEMA" and "op" in i.message for i in report.issues)


@pytest.mark.parametrize(
    "body",
    [
        {"suggestion": "ev_" + "0" * 26, "outcome": "adopted"},  # no reason
        {"suggestion": "not-an-id", "outcome": "adopted", "reason": "r"},
        {"suggestion": "ev_" + "0" * 26, "outcome": "approved", "reason": "r"},
        {"suggestion": "ev_" + "0" * 26, "outcome": "adopted", "reason": ""},
    ],
)
def test_a_resolution_must_name_a_suggestion_an_outcome_and_a_reason(body: dict[str, Any]) -> None:
    with pytest.raises(SchemaValidationError):
        validate_event_body("suggestion-resolve", body)


def test_suggestions_are_sharded_by_the_agent_that_made_them(
    world: tuple[Repo, list[str]],
) -> None:
    repo, ids = world
    event = suggest_screen(repo, ids[0])
    path = repo.path("events", "suggestion", f"{AGENT}.ndjson")
    assert [e["id"] for e in events_mod.read_events(path)] == [event["id"]]
    assert event["actor"] == AGENT
    assert event["agent"] == context().envelope_value()


def test_a_suggestion_does_not_move_the_folded_state_or_any_derived_file(
    world: tuple[Repo, list[str]],
) -> None:
    repo, ids = world
    decide(repo, STAGE, ids[:2], "include")
    before_states = {r: s.status for r, s in screening_mod.stage_states(repo, STAGE).items()}
    before_derived = derived_bytes(repo)
    for record_id in ids:
        for decision in ("include", "exclude"):
            suggest_screen(
                repo,
                record_id,
                decision,
                criteria=["EXC-01"] if decision == "exclude" else None,
                ctx=context(invoked_by="ethan"),
            )
    pool_mod.regenerate_all(repo)
    after_states = {r: s.status for r, s in screening_mod.stage_states(repo, STAGE).items()}
    assert after_states == before_states
    assert derived_bytes(repo) == before_derived


# ------------------------------------------------------------------- recording one (2.2)


def test_an_invalid_suggestion_is_refused_for_the_reason_a_real_decision_would_be(
    world: tuple[Repo, list[str]],
) -> None:
    """Excluding at full-text without citing a criterion."""
    repo, ids = world
    args = {"stage": "full-text", "record": ids[0], "decision": "exclude"}
    with pytest.raises(screening_mod.ScreeningError) as real:
        screening_mod.record_screen_decision(
            repo, stage="full-text", record_id=ids[0], decision="exclude", actor="sam"
        )
    with pytest.raises(screening_mod.ScreeningError) as suggested:
        sugg.make_suggestion(
            repo, context=context(), op="screen", args=args, rationale="No criterion to cite."
        )
    assert str(suggested.value) == str(real.value)
    assert "requires at least one cited criterion" in str(suggested.value)
    assert not repo.path("events", "suggestion").exists()  # nothing was recorded


def test_a_suggestion_citing_a_criterion_that_does_not_apply_is_refused(
    world: tuple[Repo, list[str]],
) -> None:
    repo, ids = world
    with pytest.raises(screening_mod.ScreeningError, match="EXC-09"):
        suggest_screen(repo, ids[0], "exclude", criteria=["EXC-09"])


def test_a_valid_suggestion_leaves_derived_byte_identical(world: tuple[Repo, list[str]]) -> None:
    repo, ids = world
    before = derived_bytes(repo)
    event = suggest_screen(repo, ids[0], "include")
    assert event["ev"] == "suggestion"
    pool_mod.regenerate_all(repo)
    assert derived_bytes(repo) == before
    assert verify_repository(open_repo(repo.root)).ok


def test_a_suggestion_records_the_operation_its_arguments_and_the_criteria_version(
    world: tuple[Repo, list[str]],
) -> None:
    repo, ids = world
    suggest_screen(repo, ids[1], "exclude", criteria=["EXC-02"], rationale="Wrong population.")
    (item,) = sugg.pending(repo)
    assert item.op == "screen"
    assert item.args == {
        "stage": STAGE,
        "record": ids[1],
        "decision": "exclude",
        "criteria": ["EXC-02"],
    }
    assert item.rationale == "Wrong population."
    assert item.criteria_version == int(criteria_mod.read_criteria_doc(repo)["version"])
    assert (item.actor, item.agent["model"], item.agent["invoked_by"]) == (AGENT, MODEL, "sam")
    assert (item.kind, item.record, item.stage) == ("screening", ids[1], STAGE)
    assert item.target == f"screen:{STAGE}:{ids[1]}"
    assert item.preview is None


def test_a_criteria_suggestion_carries_its_impact_preview(world: tuple[Repo, list[str]]) -> None:
    repo, ids = world
    decide(repo, STAGE, ids, "include")
    pool_mod.regenerate_all(repo)
    expected = rescreen_mod.preview_criterion_change_impact(
        repo, criterion_id="EXC-01", direction="tightened"
    )
    assert expected  # tightening makes the includes stale
    sugg.make_suggestion(
        repo,
        context=context(),
        op="criteria-edit",
        args={
            "criterion": "EXC-01",
            "direction": "tightened",
            "definition": "Not an empirical study of any kind.",
        },
        rationale="The definition is too loose.",
    )
    (item,) = sugg.pending(repo)
    assert item.preview == {"stale_decisions": len(expected), "by_stage": {STAGE: len(expected)}}
    assert (
        item.args["definition"] == "Not an empirical study of any kind."
    )  # the proposed text is recorded
    assert criteria_mod.get_criterion(repo, "EXC-01")["definition"] == "Not empirical."  # unchanged


def test_an_added_and_a_retired_criterion_carry_previews_too(world: tuple[Repo, list[str]]) -> None:
    repo, ids = world
    decide(repo, STAGE, ids, "include")
    sugg.make_suggestion(
        repo,
        context=context(),
        op="criteria-add",
        args={
            "kind": "exclusion",
            "label": "Animal study",
            "definition": "Not on people.",
            "applies_at": [STAGE],
        },
        rationale="Animal studies slipped through.",
    )
    sugg.make_suggestion(
        repo,
        context=context(),
        op="criteria-retire",
        args={"criterion": "EXC-02"},
        rationale="Duplicates EXC-01.",
    )
    added, retired = sugg.pending(repo)
    assert added.preview["stale_decisions"] == len(ids)  # an added criterion tightens
    assert retired.preview["stale_decisions"] == 0  # nothing cited EXC-02, and loosening
    assert criteria_mod.get_criterion(repo, "EXC-02")["status"] == "active"
    assert len(criteria_mod.list_criteria(repo)) == 2  # nothing was added


def test_a_criteria_suggestion_the_real_operation_would_refuse_is_refused(
    world: tuple[Repo, list[str]],
) -> None:
    repo, _ = world
    with pytest.raises(criteria_mod.CriteriaError, match="editorial asserts no semantic change"):
        sugg.make_suggestion(
            repo,
            context=context(),
            op="criteria-edit",
            args={"criterion": "EXC-01", "direction": "editorial", "definition": "Different."},
            rationale="Just tidying.",
        )


@pytest.mark.parametrize(
    ("op", "args", "message"),
    [
        ("teleport", {}, "unknown operation 'teleport'"),
        ("screen", {"stage": STAGE, "decision": "include"}, "screen needs record"),
        (
            "screen",
            {"stage": STAGE, "record": "r", "decision": "include", "x": 1},
            "does not take x",
        ),
    ],
)
def test_an_unknown_operation_or_wrong_arguments_are_refused(
    world: tuple[Repo, list[str]], op: str, args: dict[str, Any], message: str
) -> None:
    repo, _ = world
    with pytest.raises(sugg.SuggestionError, match=message):
        sugg.make_suggestion(repo, context=context(), op=op, args=args, rationale="r")


def test_a_suggestion_needs_a_reason(world: tuple[Repo, list[str]]) -> None:
    repo, ids = world
    with pytest.raises(sugg.SuggestionError, match="rationale is required"):
        suggest_screen(repo, ids[0], rationale="   ")


def test_none_arguments_are_dropped_rather_than_recorded(world: tuple[Repo, list[str]]) -> None:
    repo, ids = world
    sugg.make_suggestion(
        repo,
        context=context(),
        op="screen",
        args={"stage": STAGE, "record": ids[0], "decision": "include", "note": None},
        rationale="r",
    )
    assert "note" not in sugg.pending(repo)[0].args


# ------------------------------------------------------------------------ superseding


def test_a_later_suggestion_for_the_same_target_supersedes_the_earlier_one(
    world: tuple[Repo, list[str]],
) -> None:
    repo, ids = world
    first = suggest_screen(repo, ids[0], "include")
    second = suggest_screen(repo, ids[0], "exclude", criteria=["EXC-01"])
    (still,) = sugg.pending(repo)
    assert still.id == second["id"]
    earlier = sugg.get_suggestion(repo, first["id"])
    assert earlier.status == sugg.SUPERSEDED
    assert second["id"] in str(earlier.resolution["reason"])
    assert [s.status for s in sugg.suggestions(repo)] == [sugg.SUPERSEDED, sugg.PENDING]


def test_the_agent_that_superseded_is_the_author_of_the_resolution(
    world: tuple[Repo, list[str]],
) -> None:
    repo, ids = world
    suggest_screen(repo, ids[0], "include")
    suggest_screen(repo, ids[0], "exclude", criteria=["EXC-01"])
    resolutions = [
        e
        for e in events_mod.read_events(repo.path("events", "suggestion", f"{AGENT}.ndjson"))
        if e["ev"] == "suggestion-resolve"
    ]
    assert [e["agent"]["model"] for e in resolutions] == [MODEL]
    assert verify_repository(open_repo(repo.root)).ok


def test_suggestions_for_other_records_or_by_other_agents_do_not_supersede(
    world: tuple[Repo, list[str]],
) -> None:
    repo, ids = world
    suggest_screen(repo, ids[0], "include")
    suggest_screen(repo, ids[1], "include")
    assert len(sugg.pending(repo)) == 2


def test_a_resolved_suggestion_is_not_superseded_by_a_later_one(
    world: tuple[Repo, list[str]],
) -> None:
    repo, ids = world
    first = suggest_screen(repo, ids[0], "include")
    agent_ops.reject(repo, first["id"], by="sam", reason="Not convinced by this one.")
    suggest_screen(repo, ids[0], "exclude", criteria=["EXC-01"])
    assert sugg.get_suggestion(repo, first["id"]).status == sugg.REJECTED
    assert len(sugg.pending(repo)) == 1


def test_a_suggestion_is_found_by_an_unambiguous_prefix(world: tuple[Repo, list[str]]) -> None:
    repo, ids = world
    event = suggest_screen(repo, ids[0])
    assert sugg.get_suggestion(repo, event["id"][:12]).id == event["id"]
    with pytest.raises(sugg.SuggestionError, match="no suggestion"):
        sugg.get_suggestion(repo, "ev_nope")
    suggest_screen(repo, ids[1])
    with pytest.raises(sugg.SuggestionError, match="more than one"):
        sugg.get_suggestion(repo, "ev_")


# ------------------------------------------------------------------------- adopting (2.3)


def test_adopting_records_the_persons_own_opinion_and_links_it(
    world: tuple[Repo, list[str]],
) -> None:
    repo, ids = world
    suggested = suggest_screen(repo, ids[0], "include")
    before = _commits(repo)
    done = agent_ops.adopt(repo, suggested["id"][:14], by="ethan", rationale=WHY)
    repo = open_repo(repo.root)

    (screen_id,) = done.event_ids
    (screen,) = [e for e in screening_mod.all_screen_events(repo, STAGE) if e["id"] == screen_id]
    assert screen["actor"] == "ethan"  # the person's, not the agent's
    assert "agent" not in screen
    assert screen["body"]["decision"] == "include"
    assert screen["body"]["record"] == ids[0]

    adopted = sugg.get_suggestion(repo, suggested["id"])
    assert adopted.status == sugg.ADOPTED
    assert adopted.result == (screen_id,)
    assert adopted.resolution["by"] == "ethan"
    assert adopted.resolution["reason"] == WHY
    assert not sugg.pending(repo)

    assert len(_commits(repo)) == len(before) + 1  # one operation, one commit
    message = gitio.commit_message(repo.root, "HEAD")
    assert message.startswith(f"screen({STAGE}): screened 1 {STAGE} record(s)")
    assert WHY in message
    assert f"Strata-Suggestion: {suggested['id']}" in message
    assert f"Strata-Suggested-By: {AGENT}" in message
    assert "Strata-Actor: ethan" in message
    committed = gitio.run(["show", "--name-only", "--format=", "HEAD"], cwd=repo.root).stdout
    assert "events/suggestion/ethan.ndjson" in committed
    assert f"events/screen/{STAGE}.ethan.ndjson" in committed
    assert verify_repository(repo).ok


def test_a_suggestion_adopted_by_two_people_in_a_row_is_refused_the_second_time(
    world: tuple[Repo, list[str]],
) -> None:
    repo, ids = world
    suggested = suggest_screen(repo, ids[0])
    agent_ops.adopt(repo, suggested["id"], by="ethan", rationale=WHY)
    with pytest.raises(agent_ops.AdoptionError, match="already adopted"):
        agent_ops.adopt(open_repo(repo.root), suggested["id"], by="sam", rationale=WHY)


def test_adopting_needs_the_adopters_own_rationale(world: tuple[Repo, list[str]]) -> None:
    repo, ids = world
    suggested = suggest_screen(repo, ids[0])
    commits = _commits(repo)
    for text in ("", "   ", "ok"):
        with pytest.raises(ValueError):
            agent_ops.adopt(repo, suggested["id"], by="ethan", rationale=text)
    assert _commits(repo) == commits
    assert sugg.get_suggestion(repo, suggested["id"]).status == sugg.PENDING
    assert not screening_mod.all_screen_events(repo, STAGE)


def test_an_observer_cannot_adopt(world: tuple[Repo, list[str]]) -> None:
    from strata.core.actor import add_actor

    repo, ids = world
    add_actor(repo, handle="olive", name="Olive", role="observer")
    suggested = suggest_screen(repo, ids[0])
    with pytest.raises(agent_ops.AdoptionError, match="observer"):
        agent_ops.adopt(open_repo(repo.root), suggested["id"], by="olive", rationale=WHY)
    assert sugg.get_suggestion(repo, suggested["id"]).status == sugg.PENDING


def test_an_agent_cannot_adopt_its_own_suggestion(world: tuple[Repo, list[str]]) -> None:
    repo, ids = world
    suggested = suggest_screen(repo, ids[0])
    with pytest.raises(agent_ops.AdoptionError, match="is an AI agent"):
        agent_ops.adopt(repo, suggested["id"], by=AGENT, rationale=WHY)


def test_adopting_without_naming_a_person_in_a_review_of_several_says_to_use_by(
    world: tuple[Repo, list[str]],
) -> None:
    repo, ids = world
    suggested = suggest_screen(repo, ids[0])
    with pytest.raises(agent_ops.AdoptionError, match="--by HANDLE"):
        agent_ops.adopt(repo, suggested["id"], by=None, rationale=WHY)


def test_adopting_checks_the_suggestion_again_against_the_review_as_it_now_is(
    world: tuple[Repo, list[str]],
) -> None:
    """The criterion it cited was retired after it was made."""
    repo, ids = world
    suggested = suggest_screen(repo, ids[0], "exclude", criteria=["EXC-02"])
    criteria_mod.retire_criterion(repo, "EXC-02", actor="ethan", rationale="Duplicates EXC-01.")
    with pytest.raises(agent_ops.AdoptionError, match="can no longer be done.*EXC-02"):
        agent_ops.adopt(
            open_repo(repo.root), suggested["id"], by="ethan", rationale=WHY, confirm_moved=True
        )
    assert not screening_mod.all_screen_events(repo, STAGE)


def test_when_the_criteria_have_changed_the_person_is_told_what_and_must_confirm(
    world: tuple[Repo, list[str]],
) -> None:
    repo, ids = world
    suggested = suggest_screen(repo, ids[0], "include")
    criteria_mod.edit_criterion(
        repo,
        "EXC-01",
        direction="tightened",
        actor="ethan",
        rationale="Tightening the definition.",
        definition="Not an empirical study of any kind.",
    )
    repo = open_repo(repo.root)
    with pytest.raises(agent_ops.StateMoved) as moved:
        agent_ops.adopt(repo, suggested["id"], by="ethan", rationale=WHY)
    assert "criteria changed from v2 to v3 (EXC-01)" in str(moved.value)
    assert sugg.get_suggestion(repo, suggested["id"]).status == sugg.PENDING
    assert not screening_mod.all_screen_events(repo, STAGE)

    done = agent_ops.adopt(repo, suggested["id"], by="ethan", rationale=WHY, confirm_moved=True)
    assert len(done.event_ids) == 1
    (event,) = screening_mod.all_screen_events(open_repo(repo.root), STAGE)
    assert event["body"]["criteria_version"] == 3  # recorded against the criteria as they are now


def test_a_change_of_criteria_does_not_hold_up_a_suggestion_it_does_not_depend_on(
    world: tuple[Repo, list[str]],
) -> None:
    repo, _ = world
    sugg.make_suggestion(
        repo,
        context=context(),
        op="record-amend",
        args={"record": "rec_0000000000000001", "field": "title", "value": "A better title"},
        rationale="The title has a typo.",
    )
    criteria_mod.retire_criterion(repo, "EXC-02", actor="ethan", rationale="Duplicates EXC-01.")
    item = sugg.pending(repo)[0]
    assert agent_ops.what_moved(open_repo(repo.root), item) is None


def test_adopting_a_criteria_suggestion_makes_the_change_as_the_person(
    world: tuple[Repo, list[str]],
) -> None:
    repo, ids = world
    decide(repo, STAGE, ids, "include")
    sugg.make_suggestion(
        repo,
        context=context(),
        op="criteria-edit",
        args={
            "criterion": "EXC-01",
            "direction": "tightened",
            "definition": "Not an empirical study of any kind.",
        },
        rationale="The definition is too loose.",
    )
    (item,) = sugg.pending(repo)
    done = agent_ops.adopt(repo, item.id, by="ethan", rationale="Agreed, tightening it now.")
    repo = open_repo(repo.root)
    assert (
        criteria_mod.get_criterion(repo, "EXC-01")["definition"]
        == "Not an empirical study of any kind."
    )
    (change,) = [
        e for e in criteria_mod.all_criteria_change_events(repo) if e["id"] in done.event_ids
    ]
    assert change["actor"] == "ethan"
    assert "agent" not in change
    assert change["body"]["rationale"] == "Agreed, tightening it now."
    assert "Strata-Criterion: EXC-01" in gitio.commit_message(repo.root, "HEAD")
    assert verify_repository(repo).ok


# ------------------------------------------------------------------------ rejecting


def test_rejecting_keeps_the_suggestion_with_the_reason_and_stops_offering_it(
    world: tuple[Repo, list[str]],
) -> None:
    repo, ids = world
    suggested = suggest_screen(repo, ids[0])
    before = _commits(repo)
    rejected = agent_ops.reject(
        repo, suggested["id"], by="sam", reason="The abstract is off-topic."
    )
    assert rejected.status == sugg.REJECTED
    assert rejected.resolution["reason"] == "The abstract is off-topic."
    assert rejected.resolution["by"] == "sam"
    assert not sugg.pending(repo)
    assert [s.id for s in sugg.suggestions(repo)] == [suggested["id"]]  # still in the record
    assert len(_commits(repo)) == len(before) + 1
    assert not screening_mod.all_screen_events(repo, STAGE)  # and decided nothing
    with pytest.raises(agent_ops.AdoptionError, match="already rejected"):
        agent_ops.adopt(repo, suggested["id"], by="sam", rationale=WHY)


def test_rejecting_without_a_reason_is_refused_and_the_suggestion_stays_pending(
    world: tuple[Repo, list[str]],
) -> None:
    repo, ids = world
    suggested = suggest_screen(repo, ids[0])
    for reason in ("", "   "):
        with pytest.raises(agent_ops.AdoptionError, match="needs a reason"):
            agent_ops.reject(repo, suggested["id"], by="sam", reason=reason)
    assert len(sugg.pending(repo)) == 1


def test_an_unknown_suggestion_cannot_be_adopted_or_rejected(world: tuple[Repo, list[str]]) -> None:
    repo, _ = world
    with pytest.raises(agent_ops.AdoptionError, match="no suggestion"):
        agent_ops.adopt(repo, "ev_nope", by="ethan", rationale=WHY)
    with pytest.raises(agent_ops.AdoptionError, match="no suggestion"):
        agent_ops.reject(repo, "ev_nope", by="ethan", reason=WHY)
