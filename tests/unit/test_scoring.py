"""Unit tests for strata.dedup.scoring, per openspec:deduplication#scoring."""

from __future__ import annotations

from strata.dedup.scoring import (
    _jaccard,
    _levenshtein_distance,
    _levenshtein_ratio,
    author_sim,
    journal_sim,
    locator_sim,
    score_pair,
    title_sim,
    year_sim,
)

_CEPEDA_A = {
    "title": "Spacing effects in learning: A temporal ridgeline of optimal retention",
    "author": [{"family": "Cepeda", "given": "Nicholas J."}, {"family": "Vul", "given": "Edward"}],
    "issued": {"date-parts": [[2008]]},
    "container-title": "Psychological Science",
    "volume": "19",
    "page": "1095-1102",
    "DOI": "10.1111/j.1467-9280.2008.02209.x",
}

_CEPEDA_B_DOI_CONFLICT = {
    "title": "Spacing effects in learning. A temporal ridgeline of optimal retention",
    "author": [{"family": "Cepeda"}, {"family": "Vul"}],
    "issued": {"date-parts": [[2009]]},
    "container-title": "Psychol Sci",
    "volume": "19",
    "page": "1095",
    "DOI": "10.1111/j.1467-9280.2008.02209.x-2",
}


def test_title_sim_identical() -> None:
    assert title_sim({"title": "A Title"}, {"title": "A Title"}) == 1.0


def test_title_sim_reordered_tokens_scores_high_via_jaccard() -> None:
    assert title_sim({"title": "Learning and Memory"}, {"title": "Memory and Learning"}) == 1.0


def test_title_sim_both_missing_is_zero() -> None:
    assert title_sim({}, {}) == 0.0


def test_title_sim_one_missing() -> None:
    assert title_sim({"title": "Something"}, {}) == 0.0


def test_title_sim_appended_subtitle_scores_high() -> None:
    sim = title_sim(
        {"title": "Spacing effects in learning"},
        {"title": "Spacing effects in learning a randomised trial"},
    )
    assert sim > 0.5


def test_author_sim_full_overlap() -> None:
    a = {"author": [{"family": "Doe"}, {"family": "Roe"}]}
    b = {"author": [{"family": "Roe"}, {"family": "Doe"}]}
    assert author_sim(a, b) == 1.0


def test_author_sim_no_overlap() -> None:
    a = {"author": [{"family": "Doe"}]}
    b = {"author": [{"family": "Smith"}]}
    assert author_sim(a, b) == 0.0


def test_author_sim_halved_when_one_side_has_single_author() -> None:
    a = {"author": [{"family": "Doe"}]}
    b = {"author": [{"family": "Doe"}, {"family": "Roe"}]}
    # Jaccard({doe}, {doe, roe}) = 1/2; halved because `a` has only one author.
    assert author_sim(a, b) == 0.25


def test_author_sim_not_halved_when_both_have_multiple() -> None:
    a = {"author": [{"family": "Doe"}, {"family": "Roe"}]}
    b = {"author": [{"family": "Doe"}, {"family": "Smith"}]}
    assert author_sim(a, b) == 1 / 3


def test_author_sim_no_authors_either_side_is_zero() -> None:
    assert author_sim({}, {}) == 0.0


def test_author_sim_skips_author_entry_with_no_name() -> None:
    a = {"author": [{"family": "Doe"}, {}]}
    b = {"author": [{"family": "Doe"}]}
    assert author_sim(a, b) == 0.5  # Jaccard({doe}, {doe}) = 1.0, halved (b has one author)


def test_author_sim_skips_name_that_normalises_to_empty() -> None:
    a = {"author": [{"family": "Doe"}, {"family": "---"}]}
    b = {"author": [{"family": "Doe"}]}
    assert author_sim(a, b) == 0.5


def test_author_sim_corporate_author_literal() -> None:
    a = {"author": [{"literal": "World Health Organization"}]}
    b = {"author": [{"literal": "World Health Organization"}]}
    assert author_sim(a, b) == 0.5  # halved: one "author" listed on each side


def _yr(year: int) -> dict:
    return {"issued": {"date-parts": [[year]]}}


def test_year_sim_equal() -> None:
    assert year_sim(_yr(2020), _yr(2020)) == 1.0


def test_year_sim_off_by_one() -> None:
    assert year_sim(_yr(2020), _yr(2021)) == 0.7


def test_year_sim_off_by_more_than_one() -> None:
    assert year_sim(_yr(2020), _yr(2025)) == 0.0


def test_year_sim_missing_on_either_side() -> None:
    assert year_sim({}, _yr(2020)) == 0.0
    assert year_sim(_yr(2020), {}) == 0.0


def test_journal_sim_identical() -> None:
    a = {"container-title": "Psychological Science"}
    b = {"container-title": "Psychological Science"}
    assert journal_sim(a, b) == 1.0


def test_journal_sim_abbreviation_expanded() -> None:
    a = {"container-title": "Psychol Sci"}
    b = {"container-title": "Psychology Science"}
    assert journal_sim(a, b) == 1.0


def test_journal_sim_both_missing_is_zero() -> None:
    assert journal_sim({}, {}) == 0.0


def test_journal_sim_one_missing() -> None:
    a = {"container-title": "Psychological Science"}
    assert journal_sim(a, {}) == 0.0
    assert journal_sim({}, a) == 0.0


def test_levenshtein_distance_basic_cases() -> None:
    assert _levenshtein_distance("", "") == 0
    assert _levenshtein_distance("abc", "abc") == 0
    assert _levenshtein_distance("", "abc") == 3
    assert _levenshtein_distance("abc", "") == 3
    assert _levenshtein_distance("kitten", "sitting") == 3


def test_levenshtein_distance_symmetric() -> None:
    assert _levenshtein_distance("kitten", "sitting") == _levenshtein_distance("sitting", "kitten")


def test_levenshtein_ratio_both_empty_avoids_division_by_zero() -> None:
    assert _levenshtein_ratio("", "") == 0.0


def test_levenshtein_ratio_one_empty() -> None:
    assert _levenshtein_ratio("", "abc") == 0.0
    assert _levenshtein_ratio("abc", "") == 0.0


def test_jaccard_disjoint_and_empty() -> None:
    assert _jaccard(set(), set()) == 0.0
    assert _jaccard({"a"}, {"b"}) == 0.0
    assert _jaccard({"a"}, {"a"}) == 1.0


def test_locator_sim_both_match() -> None:
    a = {"volume": "19", "page": "1095-1102"}
    b = {"volume": "19", "page": "1095"}
    assert locator_sim(a, b) == 1.0


def test_locator_sim_one_matches() -> None:
    a = {"volume": "19", "page": "1095"}
    b = {"volume": "19", "page": "2000"}
    assert locator_sim(a, b) == 0.5


def test_locator_sim_neither_matches() -> None:
    a = {"volume": "19", "page": "1095"}
    b = {"volume": "20", "page": "2000"}
    assert locator_sim(a, b) == 0.0


def test_locator_sim_both_missing_is_zero() -> None:
    assert locator_sim({}, {}) == 0.0


def test_score_pair_doi_match_is_perfect() -> None:
    a = {"DOI": "10.1000/x", "title": "Completely different title"}
    b = {"DOI": "10.1000/X.", "title": "Something else entirely"}
    result = score_pair(a, b)
    assert result.score == 1.0
    assert result.doi_veto is False


def test_score_pair_doi_mismatch_vetoes_to_zero() -> None:
    result = score_pair(_CEPEDA_A, _CEPEDA_B_DOI_CONFLICT)
    assert result.score == 0.0
    assert result.doi_veto is True


def test_score_pair_doi_conflict_non_doi_score_is_high() -> None:
    """openspec:deduplication#scoring: a DOI-vetoed pair scoring high on everything else is a
    `doi-conflict`."""
    result = score_pair(_CEPEDA_A, _CEPEDA_B_DOI_CONFLICT)
    assert result.non_doi_score >= 0.80  # would clear the default review_threshold


def test_score_pair_no_doi_uses_weighted_features() -> None:
    a = {"title": "A Title", "issued": {"date-parts": [[2020]]}}
    b = {"title": "A Title", "issued": {"date-parts": [[2020]]}}
    result = score_pair(a, b)
    assert result.doi_veto is False
    assert result.score == result.non_doi_score
    assert result.score > 0


def test_score_pair_doi_on_only_one_side_uses_weighted_features() -> None:
    a = {"DOI": "10.1000/x", "title": "A Title"}
    b = {"title": "A Title"}
    result = score_pair(a, b)
    assert result.doi_veto is False
    assert result.features["title"] == 1.0


def test_score_pair_is_symmetric_for_a_known_pair() -> None:
    forward = score_pair(_CEPEDA_A, _CEPEDA_B_DOI_CONFLICT)
    backward = score_pair(_CEPEDA_B_DOI_CONFLICT, _CEPEDA_A)
    assert forward.score == backward.score
    assert forward.doi_veto == backward.doi_veto
    assert forward.features == backward.features
