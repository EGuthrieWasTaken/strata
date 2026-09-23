"""Unit tests for strata.ingest.parsers.bibtex beyond the golden fixtures."""

from __future__ import annotations

from strata.ingest.parsers.bibtex import parse


def test_parse_empty_text() -> None:
    result = parse("")
    assert result.records == []
    assert result.rejected == []


def test_parse_single_clean_entry() -> None:
    text = """
    @article{doe2020,
      author = {Doe, Jane},
      title = {A Title},
      year = {2020},
    }
    """
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


def test_corporate_author_double_braced_becomes_literal() -> None:
    text = """
    @misc{who2021,
      author = {{World Health Organization}},
      title = {A Report},
    }
    """
    result = parse(text)
    assert result.records[0]["author"] == [{"literal": "World Health Organization"}]


def test_unknown_fields_folded_into_note() -> None:
    text = """
    @article{doe2020,
      title = {A Title},
      note_field_one = {value one},
    }
    """
    result = parse(text)
    assert result.records[0]["note"] == "note_field_one: value one"


def test_unknown_entry_type_defaults_to_document() -> None:
    text = """
    @weirdtype{x2020,
      title = {A Title},
    }
    """
    result = parse(text)
    assert result.records[0]["type"] == "document"


def test_double_dash_page_range_normalised_to_single_dash() -> None:
    text = """
    @article{doe2020,
      title = {A Title},
      pages = {10--20},
    }
    """
    result = parse(text)
    assert result.records[0]["page"] == "10-20"


def test_braces_stripped_from_title() -> None:
    text = """
    @article{doe2020,
      title = {Effects of {DNA} damage},
    }
    """
    result = parse(text)
    assert result.records[0]["title"] == "Effects of DNA damage"


def test_html_entity_in_title_decoded() -> None:
    text = """
    @article{doe2020,
      title = {Salt &amp; pepper},
    }
    """
    result = parse(text)
    assert result.records[0]["title"] == "Salt & pepper"


def test_blank_author_field_omits_author_key() -> None:
    text = """
    @article{doe2020,
      author = {   },
      title = {A Title},
    }
    """
    result = parse(text)
    assert "author" not in result.records[0]


def test_empty_trailing_author_is_dropped_not_kept_as_blank_entry() -> None:
    """A stray trailing `and` (`Solo, Han and `) yields a second, entirely blank name."""
    text = """
    @article{doe2020,
      author = {Solo, Han and {}},
      title = {A Title},
    }
    """
    result = parse(text)
    assert result.records[0]["author"] == [{"family": "Solo", "given": "Han"}]


def test_unparseable_year_omits_issued() -> None:
    text = """
    @article{doe2020,
      title = {A Title},
      year = {n.d.},
    }
    """
    result = parse(text)
    assert "issued" not in result.records[0]


def test_url_abstract_and_language_fields() -> None:
    text = """
    @article{doe2020,
      title = {A Title},
      url = {https://example.org/paper},
      abstract = {An abstract.},
      language = {English},
    }
    """
    result = parse(text)
    record = result.records[0]
    assert record["URL"] == "https://example.org/paper"
    assert record["abstract"] == "An abstract."
    assert record["language"] == "English"
