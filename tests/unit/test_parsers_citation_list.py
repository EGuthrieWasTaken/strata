"""The plain-text citation-list parser: best effort, flagged for a person to check."""

# ruff: noqa: E501
from __future__ import annotations

from strata.ingest.parsers import citation_list


def test_a_vancouver_reference() -> None:
    result = citation_list.parse(
        "1. Roediger HL, Karpicke JD. Test-enhanced learning: taking memory tests improves long-term retention. Psychol Sci. 2006;17(3):249-255. PMID: 16507066\n"
    )
    record = result.records[0]
    assert (
        record["title"]
        == "Test-enhanced learning: taking memory tests improves long-term retention"
    )
    assert record["author"] == [
        {"family": "Roediger", "given": "HL"},
        {"family": "Karpicke", "given": "JD"},
    ]
    assert record["issued"] == {"date-parts": [[2006]]}
    assert (record["container-title"], record["volume"], record["issue"], record["page"]) == (
        "Psychol Sci",
        "17",
        "3",
        "249-255",
    )
    assert record["PMID"] == "16507066" and result.best_effort is True


def test_an_apa_reference_with_a_doi_url() -> None:
    record = citation_list.parse(
        "[7] Kornell, N., & Bjork, R. A. (2008). Learning concepts and categories: Is spacing the enemy of induction? Psychological Science, 19(6), 585-592. https://doi.org/10.1111/j.1467-9280.2008.02127.x"
    ).records[0]
    assert record["author"] == [
        {"family": "Kornell", "given": "N."},
        {"family": "Bjork", "given": "R. A."},
    ]
    assert record["title"] == "Learning concepts and categories: Is spacing the enemy of induction?"
    assert record["DOI"] == "10.1111/j.1467-9280.2008.02127.x"
    assert (record["container-title"], record["volume"], record["page"]) == (
        "Psychological Science",
        "19",
        "585-592",
    )


def test_entries_continue_over_lines_and_a_doi_keeps_its_own_punctuation_trimmed() -> None:
    text = "1. Smith J, Jones K. A title that\n   wraps onto a second line. J Test. 2001;5:10-12.\n   doi:10.1000/abc.def).\n2. Lee A. Another title. J Test. 2002;6:1-2.\n"
    result = citation_list.parse(text)
    assert [r["title"] for r in result.records] == [
        "A title that wraps onto a second line",
        "Another title",
    ]
    assert result.records[0]["DOI"] == "10.1000/abc.def"


def test_paragraphs_separate_entries_when_the_list_is_not_numbered() -> None:
    text = "Smith J, Jones K. First title. J Test. 2001;5:10-12.\n\nLee A. Second title. J Test. 2002;6:1-2.\n"
    assert [r["title"] for r in citation_list.parse(text).records] == [
        "First title",
        "Second title",
    ]


def test_what_is_not_a_reference_is_rejected_with_its_line_and_the_entry() -> None:
    text = "1. Smith J. Only a title.\n2. Lee A, Kim B. Good title. J Test. 2003;1:1-9.\n3. See appendix B.\n"
    result = citation_list.parse(text)
    assert [r["title"] for r in result.records] == ["Good title"]
    assert [(r.line, r.raw) for r in result.rejected] == [
        (1, "Smith J. Only a title."),
        (3, "See appendix B."),
    ]


def test_et_al_and_a_missing_year_do_not_break_the_entry() -> None:
    record = citation_list.parse(
        "1. Wixted JT, et al. Memory spacing. Cogn Sci. 12(2):5-9.\n"
    ).records[0]
    assert [a["family"] for a in record["author"]] == ["Wixted"] and "issued" not in record


def test_an_empty_file_has_no_records() -> None:
    result = citation_list.parse("\n\n")
    assert result.records == [] and result.rejected == []
