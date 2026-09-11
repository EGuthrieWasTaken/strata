"""Property tests for identity and normalisation, per docs/spec/14-testing.md §2.

P4 canonical stability, P5 id determinism, P6 normalisation idempotence.
"""

from __future__ import annotations

from hypothesis import assume, given
from hypothesis import strategies as st

from strata.core.canon import canonical_json
from strata.core.ids import canonical_key, normalise_title, record_id

_json_scalars = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-(10**6), max_value=10**6),
    st.text(max_size=20),
)


@st.composite
def json_values(draw: st.DrawFn, depth: int = 0) -> object:
    if depth >= 3:
        return draw(_json_scalars)
    return draw(
        st.one_of(
            _json_scalars,
            st.lists(json_values(depth=depth + 1), max_size=4),
            st.dictionaries(
                st.text(min_size=1, max_size=10), json_values(depth=depth + 1), max_size=4
            ),
        )
    )


@given(json_values())
def test_p4_canonical_stability(value: object) -> None:
    """`canon(x)` is byte-identical across repeated invocations."""
    assert canonical_json(value) == canonical_json(value)


@given(st.text(min_size=1, max_size=50))
def test_p5_id_determinism(title: str) -> None:
    """The same input record yields the same id regardless of how many times it's computed.

    Excludes the priority-7 (fresh ULID) fallback, which is the one
    deliberately non-deterministic branch (docs/spec 01-domain-model.md §3.1)
    — it is reached here only when `title` normalises to nothing at all.
    """
    assume(normalise_title(title))
    record = {"title": title, "issued": {"date-parts": [[2020]]}}
    key1, _ = canonical_key(record)
    key2, _ = canonical_key(record)
    assert key1 == key2
    assert record_id(key1) == record_id(key2)


@given(st.text(max_size=100))
def test_p6_normalisation_idempotence(text: str) -> None:
    """`normalise(normalise(s)) == normalise(s)`."""
    once = normalise_title(text)
    twice = normalise_title(once)
    assert once == twice
