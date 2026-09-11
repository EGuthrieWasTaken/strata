import pytest

from strata.core.ids import (
    base32_crockford,
    canonical_key,
    normalise_author_family,
    normalise_doi,
    normalise_journal,
    normalise_pages,
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
