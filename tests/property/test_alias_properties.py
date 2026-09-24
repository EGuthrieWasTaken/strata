"""Property test for alias resolution, per docs/spec/14-testing.md §2.

P7: any sequence of merges yields a resolvable, acyclic alias graph.
"""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from strata.core.aliases import append_alias, resolve
from strata.core.repo import Repo


@st.composite
def merge_sequences(draw: st.DrawFn) -> tuple[list[str], list[tuple[str, str]]]:
    """A sequence of `(canonical, absorbed)` pairs shaped like real dedup merges.

    Mirrors `dedup.engine.run_dedup`'s actual invariant: only a currently
    *live* (not-yet-absorbed) id can be chosen as either side of a merge, and
    once absorbed an id is permanently retired -- it can never again be
    absorbed, nor become a canonical for something else. That invariant is
    exactly what makes the resulting alias graph a forest (each node has at
    most one outgoing edge, created exactly once) instead of something that
    could cycle -- this generator cannot produce a cyclic sequence by
    construction, which is the point: real merges never do either.
    """
    n = draw(st.integers(min_value=2, max_value=12))
    ids = [f"rec_{i:04d}" for i in range(n)]
    live = list(draw(st.permutations(ids)))

    merges: list[tuple[str, str]] = []
    max_merges = n - 1
    num_merges = draw(st.integers(min_value=0, max_value=max_merges))
    for _ in range(num_merges):
        if len(live) < 2:
            break
        canonical_pos = draw(st.integers(min_value=0, max_value=len(live) - 1))
        canonical = live[canonical_pos]
        remaining = [x for x in live if x != canonical]
        absorbed_pos = draw(st.integers(min_value=0, max_value=len(remaining) - 1))
        absorbed = remaining[absorbed_pos]
        merges.append((canonical, absorbed))
        live = [x for x in live if x != absorbed]

    return ids, merges


@pytest.mark.req("P7")
@given(merge_sequences())
def test_p7_alias_resolution_terminates_and_lands_on_a_live_id(
    tmp_path_factory: pytest.TempPathFactory, data: tuple[list[str], list[tuple[str, str]]]
) -> None:
    ids, merges = data
    # A fresh directory per hypothesis example, not the once-per-test `tmp_path`
    # fixture: aliases.ndjson is append-only on disk, so reusing one directory
    # across examples would leak state between them.
    repo = Repo(root=tmp_path_factory.mktemp("p7"), config={})

    for index, (canonical, absorbed) in enumerate(merges):
        append_alias(repo, alias=absorbed, canonical=canonical, reason="dedup", event=f"ev_{index}")

    absorbed_ids = {absorbed for _, absorbed in merges}
    for record_id in ids:
        # Termination is implied by returning at all -- resolve() has its own
        # cycle guard, but this generator never produces a cycle in the first
        # place, so a hang here would mean the guard was needed and failed.
        result = resolve(repo, record_id)
        # "Resolvable": every id lands on something that was never itself
        # absorbed by a later merge -- a genuine fixed point of the graph.
        assert result not in absorbed_ids
