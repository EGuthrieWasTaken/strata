"""Suggestions take no part in any fold, count or view: openspec:event-log#suggestion-events.

P1/P2 flavoured: adding any number of suggestion events, in any state of resolution, leaves the
folded state and every file under `derived/` exactly as it was.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from strata.core.repo import Repo, open_repo
from strata.protocol import pool as pool_mod
from strata.protocol import screening as screening_mod
from strata.protocol import suggestions as sugg
from tests.unit._m3 import decide
from tests.unit._m6 import STAGE, context, derived_bytes, suggest_world

_DECISIONS = ["include", "exclude"]


@pytest.fixture(scope="module")
def template(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, list[str]]:
    repo, ids = suggest_world(tmp_path_factory.mktemp("template"))
    decide(repo, STAGE, ids[:2], "include")
    pool_mod.regenerate_all(repo)
    return repo.root, ids


def _states(repo: Repo) -> dict[str, tuple[str, tuple[str, ...]]]:
    return {
        record: (state.status, tuple(sorted(state.opinions)))
        for record, state in screening_mod.stage_states(repo, STAGE).items()
    }


_suggestion_plans = st.lists(
    st.tuples(
        st.integers(min_value=0, max_value=3),  # which record
        st.sampled_from(_DECISIONS),
        st.sampled_from(["pending", "rejected", "adopted-in-the-log-only"]),
    ),
    max_size=10,
)


@pytest.mark.req("P1")
@pytest.mark.req("P2")
@settings(max_examples=25, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(_suggestion_plans)
def test_any_number_of_suggestion_events_leave_the_state_and_every_derived_file_alone(
    template: tuple[Path, list[str]],
    tmp_path_factory: pytest.TempPathFactory,
    plan: list[tuple[int, str, str]],
) -> None:
    source, ids = template
    target = tmp_path_factory.mktemp("example") / "review"
    shutil.copytree(source, target, ignore=shutil.ignore_patterns(".git"))
    repo = open_repo(target)
    states, derived = _states(repo), derived_bytes(repo)

    for index, decision, fate in plan:
        event = sugg.make_suggestion(
            repo,
            context=context(),
            op="screen",
            args={
                "stage": STAGE,
                "record": ids[index],
                "decision": decision,
                **({"criteria": ["EXC-01"]} if decision == "exclude" else {}),
            },
            rationale="A reason.",
        )
        if fate == "rejected":
            sugg.resolve(
                repo, suggestion_id=event["id"], outcome="rejected", actor="sam", reason="No."
            )
        elif fate == "adopted-in-the-log-only":
            # A resolution that names events, written without the operation having run: even a
            # (nonsensical) log like this must not move anything.
            sugg.resolve(
                repo,
                suggestion_id=event["id"],
                outcome="adopted",
                actor="sam",
                reason="Yes.",
                result=[event["id"]],
            )

    pool_mod.regenerate_all(repo)
    assert _states(repo) == states
    assert derived_bytes(repo) == derived
