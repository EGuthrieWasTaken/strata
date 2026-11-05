"""Suggestions respect blinding: openspec:ai-suggestions#suggestions-respect-blinding."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from strata.core import agent_ops
from strata.core.actor import add_actor
from strata.core.manifest import load_manifest_doc, write_manifest
from strata.core.provenance import build_provenance
from strata.core.repo import Repo, open_repo
from strata.protocol import irr as irr_mod
from strata.protocol import pool as pool_mod
from strata.protocol import suggestions as sugg
from tests.unit._m3 import decide
from tests.unit._m6 import STAGE, context, suggest_screen, suggest_world

WHY = "Agree: the abstract meets the population criterion."


@pytest.fixture(scope="module")
def template(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, list[str]]:
    repo, ids = suggest_world(tmp_path_factory.mktemp("template"), people=("sam", "rita"))
    # `rita` is on the review but not assigned to these records.
    doc = load_manifest_doc(repo.root)
    doc["screening"]["assignment"] = {STAGE: ["ethan", "sam"]}
    write_manifest(repo.root, doc)
    return repo.root, ids


@pytest.fixture
def world(template: tuple[Path, list[str]], tmp_path: Path) -> tuple[Repo, list[str]]:
    source, ids = template
    target = tmp_path / "review"
    shutil.copytree(source, target)
    return open_repo(target), ids


def _configure(repo: Repo, **ai_and_screening: object) -> Repo:
    doc = load_manifest_doc(repo.root)
    for dotted, value in ai_and_screening.items():
        table, key = dotted.split("__")
        doc[table][key] = value
    write_manifest(repo.root, doc)
    return open_repo(repo.root)


def _ids(items: list[sugg.Suggestion]) -> list[str]:
    return [s.id for s in items]


def test_by_default_a_suggestion_is_hidden_until_the_reviewer_has_decided(
    world: tuple[Repo, list[str]],
) -> None:
    repo, ids = world
    event = suggest_screen(repo, ids[0])
    assert _ids(agent_ops.visible_pending(repo, "ethan")) == []
    assert _ids(agent_ops.visible_pending(repo, "sam")) == []
    assert _ids(agent_ops.visible_pending(repo)) == []  # the view that is safe to show anyone
    assert len(sugg.pending(repo)) == 1  # it exists; it is just not shown

    decide(repo, STAGE, ids[:1], "include", actors=("ethan",))
    assert _ids(agent_ops.visible_pending(repo, "ethan")) == [event["id"]]
    assert _ids(agent_ops.visible_pending(repo, "sam")) == []  # sam has not decided
    assert _ids(agent_ops.visible_pending(repo)) == []

    decide(repo, STAGE, ids[:1], "include", actors=("sam",))
    assert _ids(agent_ops.visible_pending(repo)) == [event["id"]]


def test_a_suggestion_about_another_record_is_not_hidden_by_deciding_this_one(
    world: tuple[Repo, list[str]],
) -> None:
    repo, ids = world
    suggest_screen(repo, ids[1])
    decide(repo, STAGE, ids[:1], "include", actors=("ethan",))
    assert agent_ops.visible_pending(repo, "ethan") == []


def test_someone_not_assigned_to_the_record_is_not_blinded_to_it(
    world: tuple[Repo, list[str]],
) -> None:
    repo, ids = world
    event = suggest_screen(repo, ids[0])
    assert _ids(agent_ops.visible_pending(repo, "rita")) == [event["id"]]


def test_a_suggestion_that_is_not_about_a_record_is_always_shown(
    world: tuple[Repo, list[str]],
) -> None:
    repo, _ = world
    event = sugg.make_suggestion(
        repo,
        context=context(),
        op="criteria-retire",
        args={"criterion": "EXC-02"},
        rationale="Duplicates EXC-01.",
    )
    assert _ids(agent_ops.visible_pending(repo, "ethan")) == [event["id"]]
    assert _ids(agent_ops.visible_pending(repo)) == [event["id"]]


@pytest.mark.parametrize(
    "setting",
    [{"ai__show_suggestions": "always"}, {"screening__blind_reviewers": False}],
)
def test_suggestions_are_shown_at_once_when_the_review_chooses_to(
    world: tuple[Repo, list[str]], setting: dict[str, object]
) -> None:
    repo, ids = world
    event = suggest_screen(repo, ids[0])
    repo = _configure(repo, **setting)
    assert not agent_ops.is_blinded(repo)
    assert _ids(agent_ops.visible_pending(repo, "ethan")) == [event["id"]]
    assert _ids(agent_ops.visible_pending(repo)) == [event["id"]]


def test_the_default_is_blinded(world: tuple[Repo, list[str]]) -> None:
    assert agent_ops.is_blinded(world[0])


def test_provenance_does_not_reveal_a_suggestion_before_the_record_is_decided(
    world: tuple[Repo, list[str]],
) -> None:
    repo, ids = world
    suggested = suggest_screen(repo, ids[0])
    assert [e.kind for e in build_provenance(repo, ids[0]) if e.kind.startswith("sugg")] == []
    decide(repo, STAGE, ids[:1], "include", actors=("ethan",))
    assert [e.kind for e in build_provenance(repo, ids[0]) if e.kind.startswith("sugg")] == []

    decide(repo, STAGE, ids[:1], "include", actors=("sam",))
    repo = open_repo(repo.root)
    kinds = [e.kind for e in build_provenance(repo, ids[0])]
    assert kinds.count("screen") == 2
    entry = next(e for e in build_provenance(repo, ids[0]) if e.kind == "suggestion")
    assert entry.detail["id"] == suggested["id"]
    assert entry.actor == "claude-opus"
    assert entry.agent["model"] == "claude-opus-5-5"


def test_provenance_shows_decisions_only_once_the_record_is_resolved(
    world: tuple[Repo, list[str]],
) -> None:
    repo, ids = world
    decide(repo, STAGE, ids[:1], "include", actors=("ethan",))
    assert [e.kind for e in build_provenance(repo, ids[0]) if e.kind == "screen"] == []


# ------------------------------------------------------- informed opinions and agreement


def _pair(repo: Repo) -> irr_mod.PairIrr:
    return irr_mod.compute_pair_irr(repo, STAGE, "ethan", "sam")


def test_by_default_a_first_opinion_is_independent_even_with_a_suggestion_waiting(
    world: tuple[Repo, list[str]],
) -> None:
    repo, ids = world
    decide(repo, STAGE, ids, "include")
    baseline = _pair(repo)
    suggest_screen(repo, ids[0])
    assert sugg.informed_opinions(repo, STAGE) == frozenset()
    assert _pair(repo) == baseline
    assert (baseline.n, baseline.excluded_informed) == (len(ids), 0)


def test_with_suggestions_always_shown_an_opinion_made_after_one_is_informed(
    world: tuple[Repo, list[str]],
) -> None:
    repo, ids = world
    repo = _configure(repo, ai__show_suggestions="always")
    suggest_screen(repo, ids[0])
    decide(repo, STAGE, ids, "include")
    repo = open_repo(repo.root)
    pair = _pair(repo)
    assert pair.excluded_informed == 1
    assert pair.n == len(ids) - 1  # the record they could have been steered on is left out
    payload = irr_mod.pair_payload(pair)
    assert payload["excluded_informed"] == 1


def test_adopting_a_suggestion_before_deciding_marks_the_opinion_informed(
    world: tuple[Repo, list[str]],
) -> None:
    """AI-first reviews: `ada` adopts before she has an opinion of her own."""
    repo, ids = world
    repo = _configure(repo, ai__show_suggestions="always")
    suggested = suggest_screen(repo, ids[0], "include")
    done = agent_ops.adopt(repo, suggested["id"], by="ethan", rationale=WHY)
    decide(repo, STAGE, ids[:1], "include", actors=("sam",))
    repo = open_repo(repo.root)
    assert set(done.event_ids) <= sugg.informed_opinions(repo, STAGE)
    pair = _pair(repo)
    assert (pair.n, pair.excluded_informed) == (0, 1)


def test_an_opinion_before_the_suggestion_was_made_stays_independent(
    world: tuple[Repo, list[str]],
) -> None:
    repo, ids = world
    repo = _configure(repo, ai__show_suggestions="always")
    decide(repo, STAGE, ids[:1], "include")
    # Make the suggestion strictly later than the opinions, whatever the clock's resolution.
    import time

    time.sleep(1.1)
    suggest_screen(repo, ids[0])
    assert sugg.informed_opinions(open_repo(repo.root), STAGE) == frozenset()


def test_the_agreement_file_stays_byte_identical_without_suggestions(
    world: tuple[Repo, list[str]],
) -> None:
    repo, ids = world
    decide(repo, STAGE, ids, "include")
    pool_mod.regenerate_all(repo)
    text = repo.path("derived", "irr.json").read_text(encoding="utf-8")
    assert "excluded_informed" not in text
    assert json.loads(text)[STAGE][0]["n"] == len(ids)


def test_a_person_on_the_review_who_is_an_observer_adds_nothing(
    world: tuple[Repo, list[str]],
) -> None:
    repo, ids = world
    add_actor(repo, handle="olive", name="Olive", role="observer")
    suggest_screen(repo, ids[0])
    assert agent_ops.visible_pending(open_repo(repo.root)) == []
