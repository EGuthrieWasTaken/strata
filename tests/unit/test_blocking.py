"""Unit tests for strata.dedup.blocking, per openspec:deduplication#blocking."""

from __future__ import annotations

from strata.dedup.blocking import (
    MAX_BLOCK_SIZE,
    compute_block_keys,
    find_candidate_pairs,
    lsh_bands,
    minhash_signature,
)

_CEPEDA = {
    "title": "Spacing effects in learning: A temporal ridgeline of optimal retention",
    "author": [{"family": "Cepeda"}],
    "issued": {"date-parts": [[2008]]},
    "container-title": "Psychological Science",
    "volume": "19",
    "page": "1095-1102",
    "DOI": "10.1111/j.1467-9280.2008.02209.x",
}


def test_compute_block_keys_doi() -> None:
    keys = compute_block_keys(_CEPEDA)
    assert keys.simple["doi"] == "10.1111/j.1467-9280.2008.02209.x"


def test_compute_block_keys_pmid() -> None:
    keys = compute_block_keys({"PMID": "19076480"})
    assert keys.simple["pmid"] == "19076480"


def test_compute_block_keys_title_prefix() -> None:
    record = {"title": "Spacing effects in learning", "issued": {"date-parts": [[2008]]}}
    keys = compute_block_keys(record)
    assert keys.simple["title-prefix"] == "spacing effe|2008"


def test_compute_block_keys_title_prefix_without_year() -> None:
    keys = compute_block_keys({"title": "Spacing effects in learning"})
    assert keys.simple["title-prefix"] == "spacing effe|"


def test_compute_block_keys_author_year_vol() -> None:
    keys = compute_block_keys(_CEPEDA)
    assert keys.simple["author-year-vol"] == "cepeda|2008|19"


def test_compute_block_keys_author_year_vol_missing_volume_omitted() -> None:
    record = {"author": [{"family": "Cepeda"}], "issued": {"date-parts": [[2008]]}}
    keys = compute_block_keys(record)
    assert "author-year-vol" not in keys.simple


def test_compute_block_keys_first_page() -> None:
    keys = compute_block_keys(_CEPEDA)
    assert keys.simple["first-page"] == "psychological science|19|1095"


def test_compute_block_keys_first_page_missing_page_omitted() -> None:
    record = {"container-title": "A Journal", "volume": "19"}
    keys = compute_block_keys(record)
    assert "first-page" not in keys.simple


def test_compute_block_keys_empty_record_has_no_simple_keys_or_bands() -> None:
    keys = compute_block_keys({})
    assert keys.simple == {}
    assert keys.title_lsh_bands == []


def test_compute_block_keys_title_lsh_bands_present_when_title_given() -> None:
    keys = compute_block_keys({"title": "Some title long enough for shingles"})
    assert len(keys.title_lsh_bands) == 32


def test_minhash_signature_empty_text_is_none() -> None:
    assert minhash_signature("") is None


def test_minhash_signature_deterministic_across_calls() -> None:
    text = "spacing effects in learning"
    assert minhash_signature(text) == minhash_signature(text)


def test_minhash_signature_length() -> None:
    signature = minhash_signature("spacing effects in learning")
    assert signature is not None
    assert len(signature) == 128


def test_minhash_signature_short_text_uses_whole_string_as_one_shingle() -> None:
    # Shorter than the 3-character shingle size.
    assert minhash_signature("ab") is not None


def test_minhash_signature_different_text_differs() -> None:
    assert minhash_signature("a completely different string") != minhash_signature(
        "spacing effects in learning"
    )


def test_lsh_bands_count_and_determinism() -> None:
    signature = minhash_signature("spacing effects in learning")
    assert signature is not None
    bands = lsh_bands(signature)
    assert len(bands) == 32
    assert bands == lsh_bands(signature)


def test_find_candidate_pairs_shared_doi() -> None:
    other = {**_CEPEDA, "title": "A totally different title"}
    result = find_candidate_pairs({"a": _CEPEDA, "b": other})
    assert result.pairs == frozenset({("a", "b")})
    assert result.warnings == []


def test_find_candidate_pairs_no_shared_keys_yields_no_pair() -> None:
    a = {"title": "Alpha paper about frogs", "issued": {"date-parts": [[1990]]}}
    b = {
        "title": "A completely unrelated study of jazz history",
        "issued": {"date-parts": [[2015]]},
    }
    result = find_candidate_pairs({"alpha": a, "beta": b})
    assert result.pairs == frozenset()


def test_find_candidate_pairs_similar_titles_via_lsh() -> None:
    a = {"title": "Spacing effects in learning: A temporal ridgeline of optimal retention"}
    b = {"title": "Spacing effects in leaming: A temporal ridgeline of 0ptimal retention"}
    result = find_candidate_pairs({"a": a, "b": b})
    assert result.pairs == frozenset({("a", "b")})


def test_find_candidate_pairs_empty_input() -> None:
    result = find_candidate_pairs({})
    assert result.pairs == frozenset()
    assert result.warnings == []


def test_find_candidate_pairs_three_way_transitive_sharing() -> None:
    records = {
        "a": {"DOI": "10.1000/x"},
        "b": {"DOI": "10.1000/x"},
        "c": {"DOI": "10.1000/x"},
    }
    result = find_candidate_pairs(records)
    assert result.pairs == frozenset({("a", "b"), ("a", "c"), ("b", "c")})


def test_find_candidate_pairs_splits_oversized_block_by_year_and_warns() -> None:
    # All share the same DOI (a pathological case, e.g. a parse bug), split into
    # two year-buckets once the block exceeds MAX_BLOCK_SIZE.
    records = {}
    half = MAX_BLOCK_SIZE // 2 + 1
    for i in range(half):
        records[f"y2020-{i}"] = {"DOI": "10.1000/same", "issued": {"date-parts": [[2020]]}}
    for i in range(half):
        records[f"y2021-{i}"] = {"DOI": "10.1000/same", "issued": {"date-parts": [[2021]]}}

    result = find_candidate_pairs(records)
    assert len(result.warnings) == 1
    assert "over the" in result.warnings[0]
    # No cross-year pairs: the oversized block was split by year first.
    for a, b in result.pairs:
        assert a.split("-")[0] == b.split("-")[0]
