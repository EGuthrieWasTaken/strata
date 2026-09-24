"""Unit tests for strata.ingest.parsers.csv_tsv."""

from __future__ import annotations

import pytest

from strata.ingest.parsers.csv_tsv import ColumnMappingError, parse, read_header

_MAPPING = {
    "title": "Title",
    "author": "Authors",
    "year": "Year",
    "container-title": "Journal",
    "volume": "Volume",
    "issue": "Issue",
    "DOI": "DOI",
    "abstract": "Abstract",
    "keyword": "Keywords",
}


def test_parse_basic_csv() -> None:
    text = (
        "Title,Authors,Year,Journal,Volume,Issue,DOI,Abstract,Keywords\r\n"
        'A Title,"Doe, Jane; Roe, Richard",2020,A Journal,19,11,10.1000/x,'
        "An abstract.,spacing;learning\r\n"
    )
    result = parse(text, delimiter=",", mapping=_MAPPING)
    assert result.rejected == []
    assert len(result.records) == 1
    record = result.records[0]
    assert record["title"] == "A Title"
    assert record["author"] == [
        {"family": "Doe", "given": "Jane"},
        {"family": "Roe", "given": "Richard"},
    ]
    assert record["issued"] == {"date-parts": [[2020]]}
    assert record["container-title"] == "A Journal"
    assert record["volume"] == "19"
    assert record["issue"] == "11"
    assert record["DOI"] == "10.1000/x"
    assert record["abstract"] == "An abstract."
    assert record["keyword"] == "spacing;learning"


def test_parse_tsv_delimiter() -> None:
    text = "Title\tAuthors\nA Title\tDoe, Jane\n"
    result = parse(text, delimiter="\t", mapping={"title": "Title", "author": "Authors"})
    assert result.records[0]["title"] == "A Title"
    assert result.records[0]["author"] == [{"family": "Doe", "given": "Jane"}]


def test_author_split_on_and_when_no_semicolon() -> None:
    text = "Title,Authors\nT,Doe Jane and Roe Richard\n"
    result = parse(text, delimiter=",", mapping={"title": "Title", "author": "Authors"})
    assert result.records[0]["author"] == [
        {"literal": "Doe Jane"},
        {"literal": "Roe Richard"},
    ]


def test_single_comma_separated_name_kept_as_one_entry() -> None:
    """Ambiguous with "Family, Given" -- treated as one name, not guessed apart."""
    text = 'Title,Authors\nT,"Doe, Jane"\n'
    result = parse(text, delimiter=",", mapping={"title": "Title", "author": "Authors"})
    assert result.records[0]["author"] == [{"family": "Doe", "given": "Jane"}]


def test_corporate_author_without_comma_becomes_literal() -> None:
    text = "Title,Authors\nT,World Health Organization\n"
    result = parse(text, delimiter=",", mapping={"title": "Title", "author": "Authors"})
    assert result.records[0]["author"] == [{"literal": "World Health Organization"}]


def test_page_start_and_end_combined() -> None:
    text = "Title,Start,End\nT,10,20\n"
    mapping = {"title": "Title", "page-start": "Start", "page-end": "End"}
    result = parse(text, delimiter=",", mapping=mapping)
    assert result.records[0]["page"] == "10-20"


def test_page_start_only() -> None:
    text = "Title,Start\nT,10\n"
    mapping = {"title": "Title", "page-start": "Start"}
    result = parse(text, delimiter=",", mapping=mapping)
    assert result.records[0]["page"] == "10"


def test_single_page_column_wins_over_start_end() -> None:
    text = "Title,Pages,Start,End\nT,5-9,10,20\n"
    mapping = {"title": "Title", "page": "Pages", "page-start": "Start", "page-end": "End"}
    result = parse(text, delimiter=",", mapping=mapping)
    assert result.records[0]["page"] == "5-9"


def test_missing_title_rejected_without_aborting_later_rows() -> None:
    text = "Title,Authors\n,Doe Jane\nGood,Roe Richard\n"
    result = parse(text, delimiter=",", mapping={"title": "Title", "author": "Authors"})
    assert [r["title"] for r in result.records] == ["Good"]
    assert len(result.rejected) == 1
    assert result.rejected[0].line == 2
    assert result.rejected[0].error == "missing or empty title"


def test_html_entity_in_title_decoded() -> None:
    text = "Title\nSalt &amp; pepper\n"
    result = parse(text, delimiter=",", mapping={"title": "Title"})
    assert result.records[0]["title"] == "Salt & pepper"


def test_unparseable_year_omits_issued() -> None:
    text = "Title,Year\nT,n.d.\n"
    result = parse(text, delimiter=",", mapping={"title": "Title", "year": "Year"})
    assert "issued" not in result.records[0]


def test_empty_file_returns_no_records() -> None:
    result = parse("", delimiter=",", mapping={"title": "Title"})
    assert result.records == []
    assert result.rejected == []


def test_unknown_mapping_target_raises() -> None:
    with pytest.raises(ColumnMappingError, match="unknown mapping target"):
        parse("Title\nT\n", delimiter=",", mapping={"title": "Title", "bogus": "X"})


def test_mapping_without_title_raises() -> None:
    with pytest.raises(ColumnMappingError, match="must include a 'title' column"):
        parse("Authors\nDoe\n", delimiter=",", mapping={"author": "Authors"})


def test_mapped_column_missing_from_header_raises() -> None:
    with pytest.raises(ColumnMappingError, match="not found in header"):
        parse("Title\nT\n", delimiter=",", mapping={"title": "Title", "author": "NoSuchColumn"})


def test_read_header() -> None:
    assert read_header("Title,Authors\nT,A\n", delimiter=",") == ["Title", "Authors"]


def test_read_header_empty_text_returns_empty_list() -> None:
    assert read_header("", delimiter=",") == []
