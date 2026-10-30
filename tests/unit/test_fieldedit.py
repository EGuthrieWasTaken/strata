"""Reading what a person types into a record field, and writing a value back as text
(`strata.core.fieldedit`; openspec:cli#correcting-a-record)."""

from __future__ import annotations

import pytest

from strata.core.fieldedit import (
    EDITABLE_FIELDS,
    FixFieldError,
    format_authors,
    format_field_value,
    format_issued,
    parse_authors,
    parse_issued,
    parse_value,
)

_RECORD = {"title": "T", "issued": {"date-parts": [[2008, 3, 1]]}}


def test_authors_are_family_comma_given_separated_by_semicolons() -> None:
    assert parse_authors("Cepeda, Nicholas J.; Vul, Edward") == [
        {"family": "Cepeda", "given": "Nicholas J."},
        {"family": "Vul", "given": "Edward"},
    ]


def test_a_name_without_a_comma_is_kept_whole_and_a_family_alone_is_allowed() -> None:
    assert parse_authors("World Health Organization; Cepeda,") == [
        {"literal": "World Health Organization"},
        {"family": "Cepeda"},
    ]


def test_authors_may_be_given_as_json_and_nothing_gives_none() -> None:
    assert parse_authors('[{"family": " Vul ", "given": "E."}, {"literal": "WHO"}]') == [
        {"family": "Vul", "given": "E."},
        {"literal": "WHO"},
    ]
    assert parse_authors("  ") == []


@pytest.mark.parametrize("text", ["[1, 2]", '[{"name": "x"}]', "[{]", '[{"family": 3}]', "[{}]"])
def test_authors_given_as_json_must_be_author_objects(text: str) -> None:
    with pytest.raises(FixFieldError):
        parse_authors(text)


def test_an_author_with_no_family_name_before_the_comma_is_refused() -> None:
    with pytest.raises(FixFieldError, match="family name"):
        parse_authors(", Nicholas")


def test_authors_round_trip_through_text() -> None:
    authors = [
        {"family": "Cepeda", "given": "N."},
        {"family": "Vul"},
        {"literal": "World Health Organization"},
    ]
    assert parse_authors(format_authors(authors)) == authors


@pytest.mark.parametrize(
    ("text", "parts"),
    [("2008", [[2008]]), ("2008-03", [[2008, 3]]), ("2008-3-1", [[2008, 3, 1]])],
)
def test_a_date_is_a_year_a_month_or_a_day(text: str, parts: list[list[int]]) -> None:
    assert parse_issued(text) == {"date-parts": parts}


@pytest.mark.parametrize("text", ["", "08", "2008-13", "2008-02-30", "March 2008", "1200", "9999"])
def test_a_date_that_is_not_one_is_refused(text: str) -> None:
    with pytest.raises(FixFieldError):
        parse_issued(text)


def test_dates_are_written_back_as_they_are_read() -> None:
    for text in ("2008", "2008-03", "2008-03-01"):
        assert format_issued(parse_issued(text)) == text
    assert format_issued(None) == ""


def test_year_replaces_the_year_and_keeps_the_month_and_day() -> None:
    field, value = parse_value(_RECORD, "year", "2009")
    assert (field, value) == ("issued", {"date-parts": [[2009, 3, 1]]})


def test_issued_replaces_the_whole_date() -> None:
    assert parse_value(_RECORD, "issued", "2009") == ("issued", {"date-parts": [[2009]]})


@pytest.mark.parametrize("text", ["nineteen", "99", "20090", "1200"])
def test_a_year_must_be_a_plausible_four_digit_year(text: str) -> None:
    with pytest.raises(FixFieldError):
        parse_value(_RECORD, "year", text)


def test_identifiers_are_normalised_and_other_text_is_only_trimmed() -> None:
    assert parse_value(_RECORD, "DOI", " https://doi.org/10.1000/AbC. ") == ("DOI", "10.1000/abc")
    assert parse_value(_RECORD, "PMID", "pmid: 123456") == ("PMID", "123456")
    assert parse_value(_RECORD, "container-title", "  J. Things  ") == (
        "container-title",
        "J. Things",
    )


def test_an_identifier_that_will_not_normalise_is_kept_as_typed() -> None:
    assert parse_value(_RECORD, "DOI", "n/a") == ("DOI", "n/a")


def test_an_empty_value_removes_a_field_but_not_the_title() -> None:
    assert parse_value(_RECORD, "abstract", "  ") == ("abstract", None)
    assert parse_value(_RECORD, "author", "") == ("author", None)
    assert parse_value(_RECORD, "year", "") == ("issued", None)
    with pytest.raises(FixFieldError, match="title cannot be empty"):
        parse_value(_RECORD, "title", " ")


def test_a_field_that_is_not_metadata_names_the_ones_that_are() -> None:
    with pytest.raises(FixFieldError) as caught:
        parse_value(_RECORD, "id", "x")
    message = str(caught.value)
    assert "'id' cannot be corrected" in message
    assert all(name in message for name in EDITABLE_FIELDS)


def test_values_are_shown_as_text() -> None:
    assert format_field_value("title", "A title") == "A title"
    assert format_field_value("author", [{"family": "Vul", "given": "E."}]) == "Vul, E."
    assert format_field_value("issued", {"date-parts": [[2008, 3]]}) == "2008-03"
    assert format_field_value("abstract", None) is None
    assert format_field_value("author", []) is None
