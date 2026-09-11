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
