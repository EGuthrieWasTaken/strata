"""Property tests for the fold, per openspec:test-suite#property-invariants.

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


# --- M3: retrieval and study events join the P1 / P2 / P9 generators ---------------------------

from strata.core.fold import fold_retrieval, fold_studies  # noqa: E402
from strata.core.ids import singleton_study_id  # noqa: E402

_REPORTS = [f"rpt_{c * 16}" for c in "abcd"]
_STUDIES = [f"std_{c * 16}" for c in "1234"]
_STATUSES = ["sought", "ill-requested", "retrieved", "not-retrieved"]


def _stamped(i: int, ev: str, body: dict, second: int, actor: str) -> dict:
    return {
        "ev": ev,
        "id": f"ev_{i:04d}",
        "ts": f"2026-01-01T00:00:{second:02d}Z",
        "actor": actor,
        "seq": i + 1,
        "body": body,
        "tool": "test",
        "digest": f"sha256:{i}",
    }


@st.composite
def retrieval_event_lists(draw: st.DrawFn) -> list[dict]:
    n = draw(st.integers(min_value=1, max_value=25))
    return [
        _stamped(
            i,
            "retrieval",
            {"report": draw(st.sampled_from(_REPORTS)), "status": draw(st.sampled_from(_STATUSES))},
            draw(st.integers(min_value=0, max_value=5)),  # collisions exercise the id tie-break
            draw(st.sampled_from(["ethan", "sam"])),
        )
        for i in range(n)
    ]


@st.composite
def study_event_lists(draw: st.DrawFn) -> list[dict]:
    n = draw(st.integers(min_value=1, max_value=20))
    events = []
    for i in range(n):
        second = draw(st.integers(min_value=0, max_value=5))
        if draw(st.booleans()):
            reports = draw(st.lists(st.sampled_from(_REPORTS), min_size=1, max_size=3, unique=True))
            body = {"study": draw(st.sampled_from(_STUDIES)), "reports": reports, "rationale": "r"}
            events.append(_stamped(i, "study-group", body, second, "ethan"))
        else:
            studies = draw(st.lists(st.sampled_from(_STUDIES), min_size=2, max_size=3, unique=True))
            body = {"report": draw(st.sampled_from(_REPORTS)), "studies": studies, "rationale": "r"}
            events.append(_stamped(i, "study-split", body, second, "sam"))
    return events


def _studies(events: list[dict]):  # type: ignore[no-untyped-def]
    return fold_studies(_REPORTS, events, singleton_study_id)


@pytest.mark.req("P1")
@given(retrieval_event_lists(), st.randoms())
def test_p1_retrieval_fold_determinism(events: list[dict], rng: random.Random) -> None:
    shuffled = events[:]
    rng.shuffle(shuffled)
    assert fold_retrieval(shuffled) == fold_retrieval(events)


@pytest.mark.req("P1")
@given(study_event_lists(), st.randoms())
def test_p1_study_fold_determinism(events: list[dict], rng: random.Random) -> None:
    shuffled = events[:]
    rng.shuffle(shuffled)
    assert _studies(shuffled) == _studies(events)


@pytest.mark.req("P2")
@given(retrieval_event_lists(), study_event_lists())
def test_p2_retrieval_and_study_idempotence(r_events: list[dict], s_events: list[dict]) -> None:
    assert fold_retrieval(r_events + r_events[::2]) == fold_retrieval(r_events)
    assert _studies(s_events + s_events[::2]) == _studies(s_events)


@pytest.mark.req("P9")
@given(retrieval_event_lists(), study_event_lists())
def test_p9_retrieval_and_study_merge_convergence(
    r_events: list[dict], s_events: list[dict]
) -> None:
    r_mid, s_mid = len(r_events) // 2, len(s_events) // 2
    assert fold_retrieval(r_events[:r_mid] + r_events[r_mid:]) == fold_retrieval(
        r_events[r_mid:] + r_events[:r_mid]
    )
    assert _studies(s_events[:s_mid] + s_events[s_mid:]) == _studies(
        s_events[s_mid:] + s_events[:s_mid]
    )


@given(study_event_lists())
def test_every_report_is_always_in_at_least_one_study(events: list[dict]) -> None:
    """Whatever is grouped or split, no included report is ever orphaned from every study."""
    result = _studies(events)
    for report in _REPORTS:
        assert result.studies_of[report]
        for study in result.studies_of[report]:
            assert report in result.members[study]
