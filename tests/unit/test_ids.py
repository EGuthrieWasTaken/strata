import pytest

from strata.core.ids import (
    assign_record_id,
    base32_crockford,
    canonical_key,
    new_import_id,
    normalise_author_family,
    normalise_doi,
    normalise_isbn,
    normalise_journal,
    normalise_pages,
    normalise_pmcid,
    normalise_pmid,
    normalise_title,
    normalise_year,
    record_id,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://doi.org/10.1111/j.1467-9280.2008.02209.x", "10.1111/j.1467-9280.2008.02209.x"),
        ("http://dx.doi.org/10.1111/ABC", "10.1111/abc"),
        ("DOI:10.1111/abc.", "10.1111/abc"),
        ("  10.1111/abc,  ", "10.1111/abc"),
        ("not a doi", None),
        ("", None),
        (None, None),
    ],
)
def test_normalise_doi(raw: str | None, expected: str | None) -> None:
    assert normalise_doi(raw) == expected


def test_normalise_title_strips_markup_and_entities() -> None:
    assert normalise_title("The <i>Spacing</i> &amp; Effect") == "the spacing effect"


def test_normalise_title_strips_combining_marks() -> None:
    assert normalise_title("Über") == "uber"


def test_normalise_title_empty() -> None:
    assert normalise_title(None) == ""
    assert normalise_title("") == ""


def test_normalise_author_family_strips_particle() -> None:
    stripped, unstripped = normalise_author_family("van Gogh")
    assert stripped == "gogh"
    assert unstripped == "van gogh"


def test_normalise_author_family_no_particle() -> None:
    stripped, unstripped = normalise_author_family("Cepeda")
    assert stripped == unstripped == "cepeda"


def test_normalise_author_family_solo_particle_word_not_stripped() -> None:
    # A single-token name equal to a particle is not "particle + name"; keep it.
    stripped, _ = normalise_author_family("Al")
    assert stripped == "al"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (2008, 2008),
        ("2008", 2008),
        ("2008-2009", 2008),
        ("Spring 1995", 1995),
        ("13", None),
        (None, None),
    ],
)
def test_normalise_year(raw: object, expected: int | None) -> None:
    assert normalise_year(raw) == expected


def test_normalise_pages_first_integer_run() -> None:
    assert normalise_pages("1095-1102") == "1095"
    assert normalise_pages(None) is None


def test_normalise_journal_expands_abbreviations() -> None:
    assert normalise_journal("J Psychol") == "journal psychology"


def test_canonical_key_priority_doi_over_pmid() -> None:
    record = {"DOI": "10.1111/abc", "PMID": "12345", "title": "x"}
    key, deterministic = canonical_key(record)
    assert key == "doi:10.1111/abc"
    assert deterministic is True


def test_canonical_key_pmid_fallback() -> None:
    record = {"PMID": "12345", "title": "x"}
    key, deterministic = canonical_key(record)
    assert key == "pmid:12345"
    assert deterministic is True


def test_canonical_key_signature_fallback() -> None:
    record = {
        "title": "Spacing effects in learning",
        "issued": {"date-parts": [[2008]]},
        "author": [{"family": "Cepeda"}],
    }
    key, deterministic = canonical_key(record)
    assert key.startswith("sig:spacing effects in learning|")
    assert deterministic is True


def test_canonical_key_ulid_fallback_is_nondeterministic() -> None:
    record: dict[str, object] = {}
    key, deterministic = canonical_key(record)
    assert key.startswith("ulid:")
    assert deterministic is False


def test_record_id_is_deterministic() -> None:
    key = "doi:10.1111/j.1467-9280.2008.02209.x"
    assert record_id(key) == record_id(key)
    assert record_id(key).startswith("rec_")
    assert len(record_id(key)) == len("rec_") + 16


def test_record_id_differs_for_different_keys() -> None:
    assert record_id("doi:10.1/a") != record_id("doi:10.1/b")


def test_base32_crockford_excludes_ambiguous_letters() -> None:
    encoded = base32_crockford(bytes(range(10)))
    assert set(encoded) <= set("0123456789ABCDEFGHJKMNPQRSTVWXYZ")
    assert not set(encoded) & set("ILOU")


def test_normalise_author_family_empty_input() -> None:
    assert normalise_author_family(None) == ("", "")
    assert normalise_author_family("") == ("", "")


def test_normalise_year_skips_out_of_range_match_before_valid_one() -> None:
    assert normalise_year("ref 9999, published 2020") == 2020


def test_normalise_journal_empty_input_returns_empty() -> None:
    assert normalise_journal(None) == ""
    assert normalise_journal("") == ""


def test_canonical_key_pmid_non_numeric_falls_through_to_pmcid() -> None:
    record = {"PMID": "not-a-number", "PMCID": "PMC777"}
    key, deterministic = canonical_key(record)
    assert key == "pmcid:PMC777"
    assert deterministic is True


def test_canonical_key_pmcid_branch() -> None:
    key, deterministic = canonical_key({"PMCID": "PMC00123"})
    assert key == "pmcid:PMC00123"
    assert deterministic is True


def test_canonical_key_arxiv_branch() -> None:
    key, deterministic = canonical_key({"arxiv": "arXiv:2301.12345"})
    assert key == "arxiv:2301.12345"
    assert deterministic is True


def test_canonical_key_arxiv_empty_after_prefix_strip_falls_through() -> None:
    key, deterministic = canonical_key({"arxiv": "arXiv:", "title": "T"})
    assert key.startswith("sig:")
    assert deterministic is True


def test_canonical_key_isbn_branch() -> None:
    key, deterministic = canonical_key({"ISBN": "978-0-13-468599-1"})
    assert key == "isbn:9780134685991"
    assert deterministic is True


def test_assign_record_id_returns_id_key_and_determinism_flag() -> None:
    rid, key, deterministic = assign_record_id({"DOI": "10.1000/abc"})
    assert rid == record_id(key)
    assert key == "doi:10.1000/abc"
    assert deterministic is True


def test_new_import_id_has_expected_prefix_and_length() -> None:
    import_id = new_import_id()
    assert import_id.startswith("imp_")
    assert len(import_id) == len("imp_") + 26


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("19076480", "19076480"), ("PMID: 19076480", "19076480"), (None, None), ("no digits", None)],
)
def test_normalise_pmid(raw: str | None, expected: str | None) -> None:
    assert normalise_pmid(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("PMC123456", "PMC123456"), ("123456", "PMC123456"), (None, None), ("none here", None)],
)
def test_normalise_pmcid(raw: str | None, expected: str | None) -> None:
    assert normalise_pmcid(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("978-0-13-468599-1", "9780134685991"), (None, None), ("none here", None)],
)
def test_normalise_isbn(raw: str | None, expected: str | None) -> None:
    assert normalise_isbn(raw) == expected
