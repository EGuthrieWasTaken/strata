from strata.core.fold import (
    CONFLICT,
    EXCLUDE,
    INCLUDE,
    PARTIAL,
    UNSCREENED,
    dedup_events,
    fold_first_write,
    fold_last_write_wins,
    resolve_screening,
    sort_events,
)


def _event(event_id: str, ts: str, actor: str, decision: str) -> dict:
    return {
        "ev": "screen",
        "id": event_id,
        "ts": ts,
        "actor": actor,
        "seq": 1,
        "body": {"decision": decision},
        "tool": "test",
        "digest": f"sha256:{event_id}",
    }


def test_sort_events_by_ts_then_id() -> None:
    e1 = _event("ev_b", "2026-01-01T00:00:01Z", "ethan", "include")
    e2 = _event("ev_a", "2026-01-01T00:00:01Z", "ethan", "exclude")
    e3 = _event("ev_c", "2026-01-01T00:00:00Z", "ethan", "include")
    ordered = sort_events([e1, e2, e3])
    assert [e["id"] for e in ordered] == ["ev_c", "ev_a", "ev_b"]


def test_dedup_events_keeps_first_occurrence() -> None:
    e1 = _event("ev_a", "2026-01-01T00:00:00Z", "ethan", "include")
    e1_dup = _event("ev_a", "2026-01-01T00:00:00Z", "ethan", "DIFFERENT")
    out = dedup_events([e1, e1_dup])
    assert len(out) == 1
    assert out[0]["body"]["decision"] == "include"


def test_fold_last_write_wins_by_key() -> None:
    e1 = _event("ev_a", "2026-01-01T00:00:00Z", "ethan", "include")
    e2 = _event("ev_b", "2026-01-01T00:00:01Z", "ethan", "exclude")
    state = fold_last_write_wins([e1, e2], key_fn=lambda e: e["actor"])
    assert state["ethan"]["body"]["decision"] == "exclude"


def test_fold_first_write_by_key() -> None:
    e1 = _event("ev_a", "2026-01-01T00:00:00Z", "ethan", "include")
    e2 = _event("ev_b", "2026-01-01T00:00:01Z", "ethan", "exclude")
    state = fold_first_write([e1, e2], key_fn=lambda e: e["actor"])
    assert state["ethan"]["body"]["decision"] == "include"


def test_resolve_screening_unscreened_with_no_opinions() -> None:
    result = resolve_screening(assigned=frozenset({"ethan", "sam"}), screen_events=[])
    assert result.status == UNSCREENED


def test_resolve_screening_partial() -> None:
    e1 = _event("ev_a", "2026-01-01T00:00:00Z", "ethan", "include")
    result = resolve_screening(assigned=frozenset({"ethan", "sam"}), screen_events=[e1])
    assert result.status == PARTIAL


def test_resolve_screening_agreement_resolves() -> None:
    e1 = _event("ev_a", "2026-01-01T00:00:00Z", "ethan", "include")
    e2 = _event("ev_b", "2026-01-01T00:00:01Z", "sam", "include")
    result = resolve_screening(assigned=frozenset({"ethan", "sam"}), screen_events=[e1, e2])
    assert result.status == INCLUDE


def test_resolve_screening_disagreement_is_conflict() -> None:
    e1 = _event("ev_a", "2026-01-01T00:00:00Z", "ethan", "include")
    e2 = _event("ev_b", "2026-01-01T00:00:01Z", "sam", "exclude")
    result = resolve_screening(assigned=frozenset({"ethan", "sam"}), screen_events=[e1, e2])
    assert result.status == CONFLICT


def test_resolve_screening_maybe_is_always_conflict() -> None:
    e1 = _event("ev_a", "2026-01-01T00:00:00Z", "ethan", "maybe")
    e2 = _event("ev_b", "2026-01-01T00:00:01Z", "sam", "include")
    result = resolve_screening(assigned=frozenset({"ethan", "sam"}), screen_events=[e1, e2])
    assert result.status == CONFLICT


def test_resolve_screening_adjudication_overrides() -> None:
    e1 = _event("ev_a", "2026-01-01T00:00:00Z", "ethan", "include")
    e2 = _event("ev_b", "2026-01-01T00:00:01Z", "sam", "exclude")
    adjudication = _event("ev_c", "2026-01-01T00:00:02Z", "ethan", "include")
    result = resolve_screening(
        assigned=frozenset({"ethan", "sam"}),
        screen_events=[e1, e2],
        adjudicate_events=[adjudication],
    )
    assert result.status == INCLUDE


def test_resolve_screening_reviewer_changes_mind() -> None:
    e1 = _event("ev_a", "2026-01-01T00:00:00Z", "ethan", "include")
    e2 = _event("ev_b", "2026-01-01T00:00:01Z", "ethan", "exclude")
    result = resolve_screening(assigned=frozenset({"ethan"}), screen_events=[e1, e2])
    assert result.status == EXCLUDE
    assert result.opinions["ethan"]["id"] == "ev_b"
    assert result.first_opinions["ethan"]["id"] == "ev_a"


# --- only assigned actors' opinions resolve a record (openspec:event-log) -----------------------


def test_an_unassigned_actors_opinion_does_not_make_a_partial_record_resolve() -> None:
    """Scenario: unassigned actor records an opinion."""
    ethan = _event("ev_a", "2026-01-01T00:00:00Z", "ethan", "include")
    outsider = _event("ev_b", "2026-01-01T00:00:01Z", "rita", "include")
    result = resolve_screening(
        assigned=frozenset({"ethan", "sam"}), screen_events=[ethan, outsider]
    )
    assert result.status == PARTIAL


def test_an_unassigned_actors_opinion_is_kept_but_apart_from_the_counted_ones() -> None:
    ethan = _event("ev_a", "2026-01-01T00:00:00Z", "ethan", "include")
    outsider = _event("ev_b", "2026-01-01T00:00:01Z", "rita", "exclude")
    result = resolve_screening(
        assigned=frozenset({"ethan", "sam"}), screen_events=[ethan, outsider]
    )
    assert set(result.opinions) == {"ethan"}
    assert set(result.first_opinions) == {"ethan"}
    assert result.unassigned == {"rita": outsider}


def test_the_latest_opinion_of_an_unassigned_actor_is_the_one_kept() -> None:
    first = _event("ev_a", "2026-01-01T00:00:00Z", "rita", "include")
    second = _event("ev_b", "2026-01-01T00:00:01Z", "rita", "exclude")
    result = resolve_screening(assigned=frozenset({"ethan"}), screen_events=[first, second])
    assert result.unassigned["rita"]["id"] == "ev_b"


def test_an_unassigned_dissent_does_not_make_a_conflict() -> None:
    ethan = _event("ev_a", "2026-01-01T00:00:00Z", "ethan", "include")
    sam = _event("ev_b", "2026-01-01T00:00:01Z", "sam", "include")
    outsider = _event("ev_c", "2026-01-01T00:00:02Z", "rita", "exclude")
    result = resolve_screening(
        assigned=frozenset({"ethan", "sam"}), screen_events=[ethan, sam, outsider]
    )
    assert result.status == INCLUDE


def test_an_unassigned_agent_is_ignored_like_any_other_unassigned_actor() -> None:
    """Scenario: unassigned agent. `ada` and the agent record `include`; the record awaits `sam`."""
    ada = _event("ev_a", "2026-01-01T00:00:00Z", "ada", "include")
    agent = _event("ev_b", "2026-01-01T00:00:01Z", "claude-opus", "include")
    agent["agent"] = {"model": "claude-opus-5-5", "invoked_by": "ada"}
    result = resolve_screening(assigned=frozenset({"ada", "sam"}), screen_events=[ada, agent])
    assert result.status == PARTIAL
    assert "claude-opus" in result.unassigned


def test_an_assigned_agent_is_the_second_reviewer() -> None:
    """Scenario: assigned agent as second reviewer."""
    ada = _event("ev_a", "2026-01-01T00:00:00Z", "ada", "include")
    agent = _event("ev_b", "2026-01-01T00:00:01Z", "claude-opus", "include")
    result = resolve_screening(
        assigned=frozenset({"ada", "claude-opus"}), screen_events=[ada, agent]
    )
    assert result.status == INCLUDE
    assert result.unassigned == {}


def test_an_assigned_agent_that_disagrees_with_a_person_is_a_conflict() -> None:
    """Scenario: agent and person disagree; the record goes to an adjudicator."""
    agent = _event("ev_a", "2026-01-01T00:00:00Z", "claude-opus", "include")
    ada = _event("ev_b", "2026-01-01T00:00:01Z", "ada", "exclude")
    result = resolve_screening(
        assigned=frozenset({"ada", "claude-opus"}), screen_events=[agent, ada]
    )
    assert result.status == CONFLICT


def test_an_adjudication_still_decides_whoever_was_unassigned() -> None:
    ethan = _event("ev_a", "2026-01-01T00:00:00Z", "ethan", "include")
    outsider = _event("ev_b", "2026-01-01T00:00:01Z", "rita", "exclude")
    adjudication = _event("ev_c", "2026-01-01T00:00:02Z", "ethan", "exclude")
    result = resolve_screening(
        assigned=frozenset({"ethan", "sam"}),
        screen_events=[ethan, outsider],
        adjudicate_events=[adjudication],
    )
    assert result.status == EXCLUDE


def test_with_nobody_assigned_nothing_counts() -> None:
    result = resolve_screening(
        assigned=frozenset(),
        screen_events=[_event("ev_a", "2026-01-01T00:00:00Z", "rita", "include")],
    )
    assert result.status == UNSCREENED
    assert set(result.unassigned) == {"rita"}


def test_the_old_rule_survives_only_to_say_what_changed() -> None:
    """`count_unassigned=True` is the pre-specification behaviour `strata verify` compares with."""
    ethan = _event("ev_a", "2026-01-01T00:00:00Z", "ethan", "include")
    outsider = _event("ev_b", "2026-01-01T00:00:01Z", "rita", "include")
    assigned = frozenset({"ethan", "sam"})
    old = resolve_screening(
        assigned=assigned, screen_events=[ethan, outsider], count_unassigned=True
    )
    new = resolve_screening(assigned=assigned, screen_events=[ethan, outsider])
    assert (old.status, new.status) == (INCLUDE, PARTIAL)
    assert set(old.opinions) == {"ethan", "rita"}
    assert old.unassigned == {}
