"""Property test for canonical serialisation, per openspec:test-suite#property-invariants.

P3: `parse(canon(x)) == x` for every schema. `canonical_json` is a
hand-written recursive serialiser (openspec:canonical-serialisation), not
a thin wrapper over `json.dumps`, so this genuinely exercises its own
recursion and per-type formatting rather than restating a stdlib guarantee.
"""

from __future__ import annotations

import json

import pytest
from hypothesis import given
from hypothesis import strategies as st

from strata.core.canon import canonical_json

# Only values `canonical_json` actually accepts (openspec:canonical-serialisation#ndjson-rules: no
# NaN/
# Infinity) and only `list`/`dict` containers -- a `tuple` would round-trip
# through JSON as a `list`, which is a real, known asymmetry of JSON itself,
# not something P3 is about.
_json_scalars = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-(10**15), max_value=10**15),
    st.floats(allow_nan=False, allow_infinity=False, width=64),
    st.text(max_size=30),
)


@st.composite
def json_values(draw: st.DrawFn, depth: int = 0) -> object:
    if depth >= 3:
        return draw(_json_scalars)
    return draw(
        st.one_of(
            _json_scalars,
            st.lists(json_values(depth=depth + 1), max_size=5),
            st.dictionaries(
                st.text(min_size=1, max_size=10), json_values(depth=depth + 1), max_size=5
            ),
        )
    )


@pytest.mark.req("P3")
@given(json_values())
def test_p3_serialisation_round_trip(value: object) -> None:
    assert json.loads(canonical_json(value)) == value


@pytest.mark.req("P3")
@given(
    st.fixed_dictionaries(
        {
            "id": st.text(
                alphabet=st.characters(min_codepoint=97, max_codepoint=122), min_size=1, max_size=20
            ),
            "type": st.just("article-journal"),
            "title": st.text(max_size=50),
            "strata": st.fixed_dictionaries(
                {
                    "canonical_key": st.text(min_size=1, max_size=30),
                    "canonical": st.booleans(),
                    "sources": st.lists(
                        st.fixed_dictionaries({"import": st.text(min_size=1, max_size=20)}),
                        max_size=3,
                    ),
                }
            ),
        }
    )
)
def test_p3_serialisation_round_trip_record_shaped(record: dict[str, object]) -> None:
    """The same property, over a record-schema-shaped document specifically --
    P3's "for every schema" wording (openspec:test-suite#property-invariants), not just arbitrary
    JSON."""
    assert json.loads(canonical_json(record)) == record
