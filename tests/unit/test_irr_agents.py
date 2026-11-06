"""Agreement involving an agent is labelled and kept apart:
openspec:ai-participation#people-and-agents-are-counted-apart."""

from __future__ import annotations

import json
from pathlib import Path

from strata.core import agents as agents_mod
from strata.core.events import agent_scope
from strata.core.repo import Repo, open_repo
from strata.protocol import irr as irr_mod
from strata.protocol import pool as pool_mod
from strata.protocol.screening import record_screen_decision
from tests.unit._m3 import add_records, init_review
from tests.unit._m6 import AGENT, MODEL, ai_review

STAGE = "title-abstract"
#: What each screener decides on records 1..4 (ethan and sam agree on three of four).
ETHAN = ["include", "include", "exclude", "exclude"]
SAM = ["include", "include", "exclude", "include"]
AGENT_DECISIONS = ["include", "exclude", "exclude", "include"]


def _screen(repo: Repo, actor: str, ids: list[str], decisions: list[str]) -> None:
    for record_id, decision in zip(ids, decisions, strict=True):
        record_screen_decision(
            repo,
            stage=STAGE,
            record_id=record_id,
            decision=decision,  # type: ignore[arg-type]
            actor=actor,
            cited=["EXC-01"] if decision == "exclude" else None,
        )


def _criteria(repo: Repo) -> None:
    from strata.protocol.criteria import add_criterion

    add_criterion(
        repo,
        kind="exclusion",
        label="Not empirical",
        definition="Not an empirical study.",
        applies_at=[STAGE, "full-text"],
        actor="ethan",
        rationale="Establishing the protocol.",
        criterion_id="EXC-01",
    )


def _by_pair(repo: Repo) -> dict[tuple[str, str], irr_mod.PairIrr]:
    return {(p.actor_a, p.actor_b): p for p in irr_mod.compute_stage_irr(repo, STAGE)}


def _with_agent(tmp_path: Path) -> tuple[Repo, list[str]]:
    repo = ai_review(tmp_path, policy={"screening": "count"})
    _criteria(repo)
    ids = add_records(repo, 4)
    _screen(repo, "ethan", ids, ETHAN)
    _screen(repo, "sam", ids, SAM)
    with agent_scope(
        AGENT, agents_mod.AgentContext(actor=AGENT, model=MODEL, invoked_by="sam").envelope_value()
    ):
        _screen(repo, AGENT, ids, AGENT_DECISIONS)
    pool_mod.regenerate_all(repo)
    return open_repo(repo.root), ids


def test_three_screeners_one_an_agent_give_three_pairs_two_labelled(tmp_path: Path) -> None:
    repo, _ = _with_agent(tmp_path)
    pairs = _by_pair(repo)
    assert list(pairs) == [(AGENT, "ethan"), (AGENT, "sam"), ("ethan", "sam")]
    assert pairs[(AGENT, "ethan")].involves_agent
    assert pairs[(AGENT, "sam")].involves_agent
    assert not pairs[("ethan", "sam")].involves_agent


def test_derived_irr_json_marks_only_the_pairs_that_involve_an_agent(tmp_path: Path) -> None:
    repo, _ = _with_agent(tmp_path)
    payload = json.loads(repo.path("derived", "irr.json").read_text(encoding="utf-8"))
    rows = {(r["actor_a"], r["actor_b"]): r for r in payload[STAGE]}
    assert rows[(AGENT, "ethan")]["involves_agent"] is True
    assert rows[(AGENT, "sam")]["involves_agent"] is True
    assert "involves_agent" not in rows[("ethan", "sam")]


def test_person_to_person_figures_are_unchanged_by_an_agent_taking_part(tmp_path: Path) -> None:
    with_agent, _ = _with_agent(tmp_path / "with")
    without = init_review(tmp_path / "without")
    _criteria(without)
    ids = add_records(without, 4)
    _screen(without, "ethan", ids, ETHAN)
    _screen(without, "sam", ids, SAM)
    pool_mod.regenerate_all(without)

    person_pair = _by_pair(with_agent)[("ethan", "sam")]
    alone = _by_pair(open_repo(without.root))[("ethan", "sam")]
    assert person_pair == alone
    assert (person_pair.n, person_pair.table["a_include_b_exclude"]) == (4, 0)


def test_a_review_without_agents_writes_the_bytes_it_always_wrote(tmp_path: Path) -> None:
    repo = init_review(tmp_path)
    _criteria(repo)
    ids = add_records(repo, 4)
    _screen(repo, "ethan", ids, ETHAN)
    _screen(repo, "sam", ids, SAM)
    pool_mod.regenerate_all(repo)
    text = repo.path("derived", "irr.json").read_text(encoding="utf-8")
    assert "involves_agent" not in text
    assert json.loads(text)[STAGE][0] == {
        "actor_a": "ethan",
        "actor_b": "sam",
        "n": 4,
        "excluded_maybe": 0,
        "table": {
            "both_include": 2,
            "a_include_b_exclude": 0,
            "a_exclude_b_include": 1,
            "both_exclude": 1,
        },
        "raw_agreement": 0.75,
        "kappa": 0.5,
        "pabak": 0.5,
    }
