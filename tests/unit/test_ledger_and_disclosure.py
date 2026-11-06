"""The AI ledger and the disclosure written from it: openspec:ai-participation#the-ai-ledger-and-audit
and #disclosure-in-generated-text."""

# ruff: noqa: E501
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest

from strata.core import agents as agents_mod
from strata.core import ledger as ledger_mod
from strata.core.events import agent_scope, append_new_events
from strata.core.manifest import load_manifest_doc, write_manifest
from strata.core.repo import Repo, open_repo
from strata.protocol import pool as pool_mod
from strata.protocol import screening as screening_mod
from strata.report import checklist, disclosure, sections
from strata.report import facts as facts_mod
from tests.unit._m3 import decide
from tests.unit._m6 import AGENT, MODEL, STAGE, context, suggest_world

WHY = "Reviewed the abstract against the criteria."


@pytest.fixture(scope="module")
def template(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, list[str]]:
    repo, ids = suggest_world(tmp_path_factory.mktemp("template"), records=6)
    return repo.root, ids


@pytest.fixture
def world(template: tuple[Path, list[str]], tmp_path: Path) -> tuple[Repo, list[str]]:
    source, ids = template
    target = tmp_path / "review"
    shutil.copytree(source, target)
    return open_repo(target), ids


def _config(repo: Repo, **sections_: dict[str, Any]) -> Repo:
    doc = load_manifest_doc(repo.root)
    for name, values in sections_.items():
        for key, value in values.items():
            doc[name][key] = value
    write_manifest(repo.root, doc)
    return open_repo(repo.root)


def _bulk_suggestions(repo: Repo, ids: list[str], made: int, adopted: int, rejected: int) -> None:
    """`made` screening suggestions by the agent, `adopted` of them adopted and `rejected` rejected
    by `ethan`, written as the events they would be (the operation is not what is under test)."""
    entries = []
    for n in range(made):
        entries.append(
            (
                "suggestion",
                AGENT,
                {
                    "op": "screen",
                    "args": {"stage": STAGE, "record": ids[n % len(ids)], "decision": "include"},
                    "rationale": "Meets the criteria.",
                    "criteria_version": 3,
                },
            )
        )
    with agent_scope(AGENT, context().envelope_value()):
        events = append_new_events(repo.path("events", "suggestion", f"{AGENT}.ndjson"), entries)
    resolutions = [
        (
            "suggestion-resolve",
            "ethan",
            {"suggestion": e["id"], "outcome": "adopted", "reason": WHY},
        )
        for e in events[:adopted]
    ] + [
        (
            "suggestion-resolve",
            "ethan",
            {"suggestion": e["id"], "outcome": "rejected", "reason": WHY},
        )
        for e in events[adopted : adopted + rejected]
    ]
    append_new_events(repo.path("events", "suggestion", "ethan.ndjson"), resolutions)


# ------------------------------------------------------------------------------- the ledger


def test_the_ledger_of_a_review_that_used_no_ai_is_empty_of_activity(
    world: tuple[Repo, list[str]],
) -> None:
    found = ledger_mod.compute_ledger(world[0])
    assert [a.actor for a in found.agents] == [AGENT]  # registered
    assert not found.used
    assert found.active_agents() == []
    assert found.agents[0].active_kinds == {} and found.agents[0].first_active is None


def test_a_review_without_agents_has_an_empty_ledger(tmp_path: Path) -> None:
    from tests.unit._m3 import init_review

    assert ledger_mod.compute_ledger(init_review(tmp_path)) == ledger_mod.Ledger()


def test_the_ledger_reports_known_figures_per_agent_and_kind(world: tuple[Repo, list[str]]) -> None:
    repo, ids = world
    _bulk_suggestions(repo, ids, made=10, adopted=6, rejected=3)  # one left waiting
    agent = ledger_mod.compute_ledger(repo).agents[0]
    k = agent.kinds["screening"]
    assert (k.suggested, k.adopted, k.rejected, k.pending, k.superseded) == (10, 6, 3, 1, 0)
    assert (k.counted, k.reviewing, k.changed_by_people) == (0, 0, 0)
    assert agent.invokers == ("sam",)
    assert agent.clients == ("claude-code 2.1.3",)
    assert agent.first_active == agent.last_active
    assert not agent.revoked and agent.model == MODEL


def test_counted_work_is_told_apart_from_suggestions_and_reviewer_slots_from_the_rest(
    world: tuple[Repo, list[str]],
) -> None:
    repo, ids = world
    repo = _config(repo, screening={"assignment": {STAGE: ["ethan", AGENT]}})
    with agents_mod.acting_as(context(invoked_by="ethan")):
        for record_id in ids[:3]:  # assigned: they fill the reviewer slot
            screening_mod.record_screen_decision(
                repo, stage="title-abstract", record_id=record_id, decision="include", actor=AGENT
            )
        screening_mod.record_screen_decision(
            repo, stage="full-text", record_id=ids[3], decision="include", actor=AGENT
        )  # a stage the assignment config does not name: assigned by default? no -> not counted
    pool_mod.regenerate_all(repo)
    k = ledger_mod.compute_ledger(repo).agents[0].kinds["screening"]
    assert k.counted == 4
    assert k.reviewing == 3
    assert ledger_mod.compute_ledger(repo).agents[0].invokers == ("ethan",)


def test_an_agent_opinion_a_person_adjudicated_is_counted_as_changed(
    world: tuple[Repo, list[str]],
) -> None:
    repo, ids = world
    repo = _config(repo, screening={"assignment": {STAGE: ["ethan", AGENT]}})
    decide(repo, STAGE, ids[:2], "include", actors=("ethan",))
    with agents_mod.acting_as(context()):
        for record_id in ids[:2]:
            screening_mod.record_screen_decision(
                repo,
                stage=STAGE,
                record_id=record_id,
                decision="exclude",
                actor=AGENT,
                cited=["EXC-01"],
            )
    from strata.protocol import adjudication as adjudication_mod

    adjudication_mod.record_adjudication(
        repo, stage=STAGE, record_id=ids[0], decision="include", actor="ethan", rationale=WHY
    )
    k = ledger_mod.compute_ledger(repo).agents[0].kinds["screening"]
    assert (k.counted, k.changed_by_people) == (2, 1)


def test_a_retrieval_outcome_a_person_later_set_differently_is_counted_as_changed(
    world: tuple[Repo, list[str]],
) -> None:
    from strata.protocol import retrieval as retrieval_mod

    repo, ids = world
    decide(repo, STAGE, ids[:1], "include")
    pool_mod.regenerate_all(repo)
    (report,) = retrieval_mod.sought_reports(open_repo(repo.root))
    with agents_mod.acting_as(context()):
        retrieval_mod.record_retrieval(
            repo, report=report, status="not-retrieved", actor=AGENT, reason="no-access"
        )
    assert ledger_mod.compute_ledger(repo).agents[0].kinds["retrieval"].changed_by_people == 0
    import time

    time.sleep(1.1)  # strictly later than the agent's event, whatever the clock's resolution
    retrieval_mod.record_retrieval(
        repo, report=report, status="not-retrieved", actor="ethan", reason="not-found"
    )
    assert ledger_mod.compute_ledger(repo).agents[0].kinds["retrieval"].changed_by_people == 1


def test_a_criteria_change_a_person_later_made_to_the_same_criterion_counts_as_changed(
    world: tuple[Repo, list[str]],
) -> None:
    import time

    from strata.protocol import criteria as criteria_mod

    repo, _ = world
    with agents_mod.acting_as(context()):
        criteria_mod.edit_criterion(
            repo, "EXC-01", direction="tightened", actor=AGENT,
            rationale="The narrower wording is clearer.", definition="Not an empirical study.",
        )  # fmt: skip
    kind = ledger_mod.compute_ledger(repo).agents[0].kinds["criteria"]
    assert (kind.counted, kind.changed_by_people) == (1, 0)
    time.sleep(1.1)  # strictly later than the agent's event, whatever the clock's resolution
    criteria_mod.edit_criterion(
        repo, "EXC-01", direction="loosened", actor="ethan",
        rationale="Put it back as it was worded.", definition="Not empirical work.",
    )  # fmt: skip
    kind = ledger_mod.compute_ledger(repo).agents[0].kinds["criteria"]
    assert (kind.counted, kind.changed_by_people) == (1, 1)


def test_the_ledger_still_reports_events_when_the_history_cannot_be_read(
    world: tuple[Repo, list[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    from strata.core import logcmd

    repo, ids = world
    with agents_mod.acting_as(context()):
        decide(repo, STAGE, ids[:1], "include", actors=(AGENT,))

    def unreadable(_repo: Repo) -> list[Any]:
        raise RuntimeError("no usable history")

    monkeypatch.setattr(logcmd, "domain_log", unreadable)
    kind = ledger_mod.compute_ledger(repo).agents[0].kinds["screening"]
    assert (kind.counted, kind.file_work) == (1, 0)


def test_a_suggestion_from_an_actor_the_manifest_no_longer_lists_is_left_out(
    world: tuple[Repo, list[str]],
) -> None:
    repo, ids = world
    _bulk_suggestions(repo, ids, made=2, adopted=0, rejected=0)
    assert ledger_mod.compute_ledger(repo).agents[0].kinds["screening"].suggested == 2
    doc = load_manifest_doc(repo.root)
    doc["actors"] = [a for a in doc["actors"] if a["handle"] != AGENT]
    write_manifest(repo.root, doc)
    assert ledger_mod.compute_ledger(open_repo(repo.root)) == ledger_mod.Ledger()


# ------------------------------------------------------------------------- the disclosure


def test_a_review_that_used_no_ai_keeps_the_wording_it_always_had(
    world: tuple[Repo, list[str]],
) -> None:
    repo, _ = world
    facts = facts_mod.collect(repo)
    assert not facts.ledger.used
    methods = sections.methods(facts)
    assert "no records were removed by other automation tools." in methods
    assert "AI" not in methods
    items = {item.id: item.content for item in checklist.build(facts)}
    assert "no machine-learning prioritisation was used" in items["8"]
    assert "AI" not in items["8"] + items["9"] + items["11"]
    assert disclosure.area_text(facts.ledger, disclosure.SELECTION, "selection") == ""


def test_suggestions_only_names_the_model_says_a_person_reviewed_them_and_gives_the_figures(
    world: tuple[Repo, list[str]],
) -> None:
    """Scenario: 1,200 screening suggestions, 1,050 adopted and 150 rejected."""
    repo, ids = world
    _bulk_suggestions(repo, ids, made=1200, adopted=1050, rejected=150)
    facts = facts_mod.collect(repo)
    methods = sections.methods(facts)
    assert "The AI model claude-opus-5-5" in methods
    assert "has not been verified" in methods
    assert (
        "in suggest mode made 1,200 screening suggestions, of which 1,050 adopted and 150 rejected by a person"
        in methods
    )
    assert "a person reviewed every suggestion before any took effect" in methods
    assert "run by sam" in methods
    assert (
        "no records were removed by automation tools other than the AI described below" in methods
    )
    assert (
        "Records were screened at title-abstract and full-text by two reviewers (ethan and sam)"
        in methods
    )
    # the people are still two: a model that only suggested is not a reviewer
    assert "AI model (" not in methods.split("### Selection process")[1].split(".")[0]


def test_a_single_reviewer_review_says_so_in_the_methods(world: tuple[Repo, list[str]]) -> None:
    repo, _ = world
    repo = _config(repo, screening={"mode": "single"})
    selection = sections.methods(facts_mod.collect(repo)).split("### Selection process")[1]
    assert "by one reviewer (" in selection.split(".")[0]
    assert "working independently" not in selection.split(".")[0]


def test_a_counted_reviewer_is_named_as_a_model_and_counted_apart_from_the_people(
    world: tuple[Repo, list[str]],
) -> None:
    """Scenarios: reviewer count in the Methods; checklist item 8 for a counted reviewer."""
    repo, ids = world
    repo = _config(repo, screening={"assignment": {STAGE: ["ethan", "sam", AGENT]}})
    with agents_mod.acting_as(context()):
        for record_id in ids[:3]:
            screening_mod.record_screen_decision(
                repo, stage=STAGE, record_id=record_id, decision="include", actor=AGENT
            )
    pool_mod.regenerate_all(repo)
    facts = facts_mod.collect(repo)
    methods = sections.methods(facts)
    assert (
        "by two people (ethan and sam) and one AI model (claude-opus-5-5) working independently"
        in methods
    )
    assert "3 of them as a reviewer whose opinion counted toward a record's resolution" in methods
    item8 = {item.id: item.content for item in checklist.build(facts)}["8"]
    assert "screened by two people (ethan and sam) and one AI model (claude-opus-5-5)" in item8
    assert "the AI model acted as a reviewer" in item8
    assert "no machine-learning prioritisation was used" not in item8
    assert "Automation: strata's deduplication, and the AI model(s) described" in item8


def test_people_are_never_listed_as_an_agent_and_an_agent_is_never_listed_as_a_reviewer(
    world: tuple[Repo, list[str]],
) -> None:
    facts = facts_mod.collect(world[0])
    assert facts.reviewers("lead", "screener") == ["ethan", "sam"]
    assert AGENT not in facts.reviewers()


def test_agreement_with_an_agent_is_labelled_in_the_text(world: tuple[Repo, list[str]]) -> None:
    repo, ids = world
    repo = _config(repo, screening={"assignment": {STAGE: ["ethan", "sam", AGENT]}})
    decide(repo, STAGE, ids[:2], "include")
    with agents_mod.acting_as(context()):
        for record_id in ids[:2]:
            screening_mod.record_screen_decision(
                repo, stage=STAGE, record_id=record_id, decision="include", actor=AGENT
            )
    pool_mod.regenerate_all(repo)
    methods = sections.methods(facts_mod.collect(open_repo(repo.root)))
    assert f"Agreement between {AGENT} (an AI model) and ethan at {STAGE}" in methods
    assert "Agreement between ethan and sam at" in methods


def test_areas_the_ai_did_not_touch_say_so_when_it_took_part_elsewhere(
    world: tuple[Repo, list[str]],
) -> None:
    repo, ids = world
    _bulk_suggestions(repo, ids, made=3, adopted=1, rejected=1)
    ledger = ledger_mod.compute_ledger(repo)
    assert disclosure.area_text(ledger, disclosure.COLLECTION, "data collection") == (
        "No AI model took part in data collection."
    )
    assert disclosure.area_text(ledger, disclosure.RISK_OF_BIAS, "risk of bias") == (
        "No AI model took part in risk of bias."
    )
    assert "claude-opus-5-5" in disclosure.area_text(ledger, disclosure.SELECTION, "selection")


def test_golden_paragraph_for_suggestions_and_counted_work(world: tuple[Repo, list[str]]) -> None:
    repo, ids = world
    _bulk_suggestions(repo, ids, made=12, adopted=8, rejected=3)
    assert disclosure.paragraph(ledger_mod.compute_ledger(repo), disclosure.SELECTION) == (
        "The AI model claude-opus-5-5 (registered as claude-opus; the model name is the model's own "
        "report and has not been verified), run by sam, took part (screening: in suggest mode made "
        "12 screening suggestions, of which 8 adopted and 3 rejected by a person, 1 not acted on; "
        "a person reviewed every suggestion before any took effect)."
    )


def test_numbers_and_counts_read_naturally() -> None:
    assert [disclosure.count_word(n) for n in (1, 2, 3, 7)] == ["one", "two", "three", "7"]
    assert disclosure.plural(1, "decision") == "1 decision"
    assert disclosure.plural(1200, "decision") == "1,200 decisions"
    assert disclosure.join(["a"]) == "a"
    assert disclosure.join(["a", "b", "c"]) == "a, b and c"
