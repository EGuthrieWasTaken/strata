"""Property tests for deduplication scoring, per docs/spec/14-testing.md §2.

P8: dedup symmetry -- `score(a, b) == score(b, a)`.
"""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from strata.dedup.scoring import score_pair

_names = st.text(alphabet=st.characters(min_codepoint=32, max_codepoint=126), max_size=15)

_authors = st.lists(
    st.fixed_dictionaries({"family": _names, "given": _names}),
    max_size=4,
)

_years = st.lists(st.integers(1400, 2100), min_size=1, max_size=1)
_issued = st.fixed_dictionaries({"date-parts": st.lists(_years, max_size=1)})

_records = st.fixed_dictionaries(
    {},
    optional={
        "title": _names,
        "author": _authors,
        "issued": _issued,
        "container-title": _names,
        "volume": st.text(alphabet="0123456789", max_size=4),
        "page": st.text(alphabet="0123456789-", max_size=8),
        "DOI": st.one_of(st.none(), st.text(alphabet="0123456789./abc-", max_size=30)),
    },
)


@pytest.mark.req("P8")
@given(_records, _records)
def test_p8_score_is_symmetric(record_a: dict, record_b: dict) -> None:
    """`score(a, b) == score(b, a)`, including the DOI-veto flag and per-feature breakdown."""
    forward = score_pair(record_a, record_b)
    backward = score_pair(record_b, record_a)
    assert forward.score == backward.score
    assert forward.doi_veto == backward.doi_veto
    assert forward.features == backward.features
