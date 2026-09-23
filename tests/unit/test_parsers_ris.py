"""Unit tests for strata.ingest.parsers.ris beyond the golden fixtures."""

from __future__ import annotations

from strata.ingest.parsers.ris import parse


def test_parse_empty_text() -> None:
    result = parse("")
    assert result.records == []
    assert result.rejected == []


def test_parse_single_clean_record() -> None:
    text = "TY  - JOUR\nAU  - Doe, Jane\nTI  - A Title\nPY  - 2020\nER  - \n"
    result = parse(text)
    assert result.rejected == []
    assert result.records == [
        {
            "type": "article-journal",
            "title": "A Title",
            "author": [{"family": "Doe", "given": "Jane"}],
            "issued": {"date-parts": [[2020]]},
        }
    ]


def test_corporate_author_without_comma_becomes_literal() -> None:
    text = "TY  - JOUR\nAU  - World Health Organization\nTI  - T\nER  - \n"
    result = parse(text)
    assert result.records[0]["author"] == [{"literal": "World Health Organization"}]


def test_author_with_family_only_omits_given() -> None:
    text = "TY  - JOUR\nAU  - Prince,\nTI  - T\nER  - \n"
    result = parse(text)
    assert result.records[0]["author"] == [{"family": "Prince"}]


def test_missing_final_er_still_parses_last_record() -> None:
    text = (
        "TY  - JOUR\nAU  - Doe, Jane\nTI  - No closing tag\nER  - \n"
        "\nTY  - JOUR\nTI  - Last record, no ER"
    )
    result = parse(text)
    titles = [r["title"] for r in result.records]
    assert titles == ["No closing tag", "Last record, no ER"]


def test_unknown_reference_type_defaults_to_article_journal() -> None:
    text = "TY  - DATA\nTI  - A dataset\nER  - \n"
    result = parse(text)
    assert result.records[0]["type"] == "article-journal"


def test_book_type_mapped() -> None:
    text = "TY  - BOOK\nTI  - A Book\nER  - \n"
    result = parse(text)
    assert result.records[0]["type"] == "book"


def test_page_range_from_start_and_end() -> None:
    text = "TY  - JOUR\nTI  - T\nSP  - 10\nEP  - 20\nER  - \n"
    result = parse(text)
    assert result.records[0]["page"] == "10-20"


def test_page_start_only() -> None:
    text = "TY  - JOUR\nTI  - T\nSP  - 10\nER  - \n"
    result = parse(text)
    assert result.records[0]["page"] == "10"


def test_html_entity_in_title_decoded() -> None:
    text = "TY  - JOUR\nTI  - Salt &amp; pepper\nER  - \n"
    result = parse(text)
    assert result.records[0]["title"] == "Salt & pepper"


def test_text_with_no_tags_at_all_produces_nothing() -> None:
    result = parse("just some free text\nwith no RIS tags\n")
    assert result.records == []
    assert result.rejected == []
