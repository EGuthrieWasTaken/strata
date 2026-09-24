"""Property tests for the fold, per docs/spec/14-testing.md §2.

P1 fold determinism, P2 fold idempotence, P9 merge convergence, P13 undo
inverts.
"""

from __future__ import annotations

import random
import string

import pytest
from hypothesis import given
from hypothesis import strategies as st

from strata.core.fold import apply_undo, fold_last_write_wins


@st.composite
def event_lists(draw: st.DrawFn) -> list[dict]:
    n = draw(st.integers(min_value=1, max_value=30))
    keys = draw(
        st.lists(
            st.text(alphabet=string.ascii_lowercase, min_size=1, max_size=3),
            min_size=1,
            max_size=5,
            unique=True,
        )
    )
    # Second-precision timestamps in a small range, so ts collisions (and
    # hence id tie-breaking) are exercised.
    seconds = draw(st.lists(st.integers(min_value=0, max_value=5), min_size=n, max_size=n))
    key_choices = draw(st.lists(st.sampled_from(keys), min_size=n, max_size=n))
    events = []
    for i in range(n):
        event_id = f"ev_{i:04d}"
        events.append(
            {
                "ev": "note",
                "id": event_id,
                "ts": f"2026-01-01T00:00:{seconds[i]:02d}Z",
                "actor": "ethan",
                "seq": i + 1,
                "body": {"key": key_choices[i], "value": i},
                "tool": "test",
                "digest": f"sha256:{event_id}",
            }
        )
    return events


@pytest.mark.req("P1")
@given(event_lists())
def test_p1_fold_determinism(events: list[dict]) -> None:
    """Folding a shuffled event log yields the same state as folding it in any other order."""
    shuffled = events[:]
    random.shuffle(shuffled)
    a = fold_last_write_wins(events, key_fn=lambda e: e["body"]["key"])
    b = fold_last_write_wins(shuffled, key_fn=lambda e: e["body"]["key"])
    assert a == b


@pytest.mark.req("P2")
@given(event_lists(), st.integers(min_value=0, max_value=5))
def test_p2_fold_idempotence(events: list[dict], duplicate_times: int) -> None:
    """Duplicating any subset of events does not change the folded state."""
    baseline = fold_last_write_wins(events, key_fn=lambda e: e["body"]["key"])
    duplicated = events + events[: max(0, len(events) // 2)] * duplicate_times
    result = fold_last_write_wins(duplicated, key_fn=lambda e: e["body"]["key"])
    assert baseline == result


@pytest.mark.req("P9")
@given(event_lists())
def test_p9_merge_convergence(events: list[dict]) -> None:
    """Applying two disjoint event sets in either order yields the same state."""
    if len(events) < 2:
        return
    midpoint = len(events) // 2
    left, right = events[:midpoint], events[midpoint:]
    a = fold_last_write_wins(left + right, key_fn=lambda e: e["body"]["key"])
    b = fold_last_write_wins(right + left, key_fn=lambda e: e["body"]["key"])
    assert a == b


@pytest.mark.req("P13")
@given(event_lists())
def test_p13_undo_inverts(events: list[dict]) -> None:
    """A decision followed by its undo folds to the pre-decision state."""
    pre_state = fold_last_write_wins(events[:-1], key_fn=lambda e: e["body"]["key"])
    last = events[-1]
    with_last = events[:]
    undone = apply_undo(with_last, last["id"])
    post_undo_state = fold_last_write_wins(undone, key_fn=lambda e: e["body"]["key"])
    assert post_undo_state == pre_state
