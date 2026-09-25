import json
from pathlib import Path

import pytest

from strata.core.actor import add_actor
from strata.core.events import read_events
from strata.core.init import init_repository
from strata.core.repo import open_repo
from strata.protocol.adjudication import (
    AdjudicationError,
    conflict_queue,
    is_adjudicator,
    record_adjudication,
    record_discussion,
)
from strata.protocol.criteria import add_criterion
from strata.protocol.screening import record_screen_decision, resolve_record_state


def _init(tmp_path: Path):  # type: ignore[no-untyped-def]
    root = tmp_path / "review"
    init_repository(root, title="T", actor_handle="ethan", actor_name="Ethan")
    repo = open_repo(root)
    add_actor(repo, handle="sam", name="Sam", role="screener")
    return open_repo(root)


def _add_records(repo, ids: list[str]) -> None:  # type: ignore[no-untyped-def]
    records_path = repo.path("records", "records.ndjson")
    records_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        json.dumps(
            {
                "id": rid,
                "type": "article-journal",
                "title": f"Title for {rid}",
                "strata": {"canonical_key": f"sig:{rid}", "canonical": True, "sources": []},
            }
        )
        for rid in ids
    ]
    records_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _make_conflict(repo, record_id: str) -> None:  # type: ignore[no-untyped-def]
    record_screen_decision(
        repo, stage="title-abstract", record_id=record_id, decision="include", actor="ethan"
    )
    record_screen_decision(
        repo, stage="title-abstract", record_id=record_id, decision="maybe", actor="sam"
    )


def test_is_adjudicator_default_lead(tmp_path: Path) -> None:
    repo = _init(tmp_path)
    assert is_adjudicator(repo, "ethan") is True  # lead, and default adjudicators list
    assert is_adjudicator(repo, "sam") is False


def test_is_adjudicator_via_role(tmp_path: Path) -> None:
    repo = _init(tmp_path)
    add_actor(repo, handle="pat", name="Pat", role="adjudicator")
    repo = open_repo(repo.root)
    assert is_adjudicator(repo, "pat") is True


def test_conflict_queue_finds_disagreements(tmp_path: Path) -> None:
    repo = _init(tmp_path)
    _add_records(repo, ["rec_0000000000000001", "rec_0000000000000002"])
    _make_conflict(repo, "rec_0000000000000001")
    record_screen_decision(
        repo,
        stage="title-abstract",
        record_id="rec_0000000000000002",
        decision="include",
        actor="ethan",
    )
    record_screen_decision(
        repo,
        stage="title-abstract",
        record_id="rec_0000000000000002",
        decision="include",
        actor="sam",
    )
    assert conflict_queue(repo, "title-abstract") == ["rec_0000000000000001"]


def test_conflict_queue_rejects_unknown_stage(tmp_path: Path) -> None:
    repo = _init(tmp_path)
    with pytest.raises(AdjudicationError, match="unknown stage"):
        conflict_queue(repo, "bogus")


def test_record_adjudication_requires_authorization(tmp_path: Path) -> None:
    repo = _init(tmp_path)
    _add_records(repo, ["rec_0000000000000001"])
    _make_conflict(repo, "rec_0000000000000001")
    with pytest.raises(AdjudicationError, match="not an adjudicator"):
        record_adjudication(
            repo,
            stage="title-abstract",
            record_id="rec_0000000000000001",
            decision="include",
            actor="sam",
            rationale="Looks like an eligible study on balance.",
        )


def test_record_adjudication_requires_rationale(tmp_path: Path) -> None:
    repo = _init(tmp_path)
    _add_records(repo, ["rec_0000000000000001"])
    _make_conflict(repo, "rec_0000000000000001")
    with pytest.raises(AdjudicationError, match="rationale"):
        record_adjudication(
            repo,
            stage="title-abstract",
            record_id="rec_0000000000000001",
            decision="include",
            actor="ethan",
            rationale="   ",
        )


def test_record_adjudication_rejects_unknown_stage_and_decision(tmp_path: Path) -> None:
    repo = _init(tmp_path)
    _add_records(repo, ["rec_0000000000000001"])
    _make_conflict(repo, "rec_0000000000000001")
    with pytest.raises(AdjudicationError, match="unknown stage"):
        record_adjudication(
            repo,
            stage="bogus",
            record_id="rec_0000000000000001",
            decision="include",
            actor="ethan",
            rationale="A perfectly good rationale here.",
        )
    with pytest.raises(AdjudicationError, match="decision must be one of"):
        record_adjudication(
            repo,
            stage="title-abstract",
            record_id="rec_0000000000000001",
            decision="maybe",  # type: ignore[arg-type]
            actor="ethan",
            rationale="A perfectly good rationale here.",
        )


def test_record_adjudication_rejects_unknown_record(tmp_path: Path) -> None:
    repo = _init(tmp_path)
    with pytest.raises(AdjudicationError, match="no record"):
        record_adjudication(
            repo,
            stage="title-abstract",
            record_id="rec_doesnotexist0000",
            decision="include",
            actor="ethan",
            rationale="A perfectly good rationale here.",
        )


def test_record_adjudication_rejects_not_actually_conflicting(tmp_path: Path) -> None:
    repo = _init(tmp_path)
    _add_records(repo, ["rec_0000000000000001"])
    record_screen_decision(
        repo,
        stage="title-abstract",
        record_id="rec_0000000000000001",
        decision="include",
        actor="ethan",
    )
    with pytest.raises(AdjudicationError, match="not in conflict"):
        record_adjudication(
            repo,
            stage="title-abstract",
            record_id="rec_0000000000000001",
            decision="include",
            actor="ethan",
            rationale="A perfectly good rationale here.",
        )


def test_record_adjudication_rejects_inactive_criterion(tmp_path: Path) -> None:
    repo = _init(tmp_path)
    _add_records(repo, ["rec_0000000000000001"])
    _make_conflict(repo, "rec_0000000000000001")
    with pytest.raises(AdjudicationError, match="not an active criterion"):
        record_adjudication(
            repo,
            stage="title-abstract",
            record_id="rec_0000000000000001",
            decision="exclude",
            actor="ethan",
            rationale="A perfectly good rationale here.",
            cited=["EXC-99"],
        )


def test_record_adjudication_full_text_exclude_requires_citation(tmp_path: Path) -> None:
    repo = _init(tmp_path)
    _add_records(repo, ["rec_0000000000000001"])
    record_screen_decision(
        repo, stage="full-text", record_id="rec_0000000000000001", decision="include", actor="ethan"
    )
    record_screen_decision(
        repo, stage="full-text", record_id="rec_0000000000000001", decision="maybe", actor="sam"
    )
    with pytest.raises(AdjudicationError, match="always requires at least one"):
        record_adjudication(
            repo,
            stage="full-text",
            record_id="rec_0000000000000001",
            decision="exclude",
            actor="ethan",
            rationale="A perfectly good rationale here.",
        )


def test_record_adjudication_success_supersedes_opinions_and_stamps_version(
    tmp_path: Path,
) -> None:
    repo = _init(tmp_path)
    _add_records(repo, ["rec_0000000000000001"])
    add_criterion(
        repo,
        kind="exclusion",
        label="Wrong population",
        definition="Not the target population.",
        applies_at=["title-abstract"],
        actor="ethan",
        rationale="Establishing the initial protocol criteria.",
        criterion_id="EXC-04",
    )
    record_screen_decision(
        repo,
        stage="title-abstract",
        record_id="rec_0000000000000001",
        decision="include",
        actor="ethan",
        note="looks like an RCT with a delayed test",
    )
    record_screen_decision(
        repo,
        stage="title-abstract",
        record_id="rec_0000000000000001",
        decision="exclude",
        actor="sam",
        cited=["EXC-04"],
        note="medical residents, not undergraduates",
    )

    envelope = record_adjudication(
        repo,
        stage="title-abstract",
        record_id="rec_0000000000000001",
        decision="exclude",
        actor="ethan",
        rationale="Sam is right -- this is the wrong population for our question.",
        cited=["EXC-04"],
    )
    assert envelope["ev"] == "adjudicate"
    body = envelope["body"]
    assert body["decision"] == "exclude"
    assert body["criteria"] == ["EXC-04"]
    assert body["criteria_version"] == 1
    assert "criteria_digest" in body
    assert len(body["supersedes"]) == 2
    assert body["own_conflict"] is True  # ethan adjudicating a conflict ethan opined on

    state = resolve_record_state(repo, "title-abstract", "rec_0000000000000001")
    assert state.status == "exclude"
    assert state.adjudication is not None
    # IRR still reflects the original disagreement -- opinions are not erased.
    assert len(state.opinions) == 2


def test_record_adjudication_own_conflict_false_when_third_party(tmp_path: Path) -> None:
    repo = _init(tmp_path)
    add_actor(repo, handle="pat", name="Pat", role="adjudicator")
    repo = open_repo(repo.root)
    _add_records(repo, ["rec_0000000000000001"])
    _make_conflict(repo, "rec_0000000000000001")

    envelope = record_adjudication(
        repo,
        stage="title-abstract",
        record_id="rec_0000000000000001",
        decision="include",
        actor="pat",
        rationale="Pat, uninvolved in the original screening, resolves this.",
    )
    assert envelope["body"]["own_conflict"] is False


def test_record_discussion_leaves_conflict_open(tmp_path: Path) -> None:
    repo = _init(tmp_path)
    _add_records(repo, ["rec_0000000000000001"])
    _make_conflict(repo, "rec_0000000000000001")

    record_discussion(
        repo,
        stage="title-abstract",
        record_id="rec_0000000000000001",
        actor="ethan",
        text="Let's discuss at the Tuesday meeting.",
    )
    state = resolve_record_state(repo, "title-abstract", "rec_0000000000000001")
    assert state.status == "conflict"

    events = read_events(repo.path("events", "note", "ethan.ndjson"))
    assert len(events) == 1
    assert events[0]["body"]["subject"] == "adjudication-discuss"
