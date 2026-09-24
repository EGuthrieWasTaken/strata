"""Unit tests for strata.ingest.parsers.medline beyond the golden fixtures."""

from __future__ import annotations

from strata.ingest.parsers.medline import parse


def test_parse_empty_text() -> None:
    result = parse("")
    assert result.records == []
    assert result.rejected == []


def test_title_continuation_line_joined() -> None:
    text = "PMID- 1\nTI  - A title that wraps\n      onto a continuation line.\n"
    result = parse(text)
    assert result.records[0]["title"] == "A title that wraps onto a continuation line."


def test_fau_preferred_over_au() -> None:
    text = "PMID- 1\nTI  - T\nFAU - Doe, Jane Q\nAU  - Doe JQ\n"
    result = parse(text)
    assert result.records[0]["author"] == [{"family": "Doe", "given": "Jane Q"}]


def test_au_fallback_when_no_fau() -> None:
    text = "PMID- 1\nTI  - T\nAU  - Doe JQ\n"
    result = parse(text)
    assert result.records[0]["author"] == [{"family": "Doe", "given": "JQ"}]


def test_au_without_space_becomes_literal() -> None:
    text = "PMID- 1\nTI  - T\nAU  - WorldHealthOrganization\n"
    result = parse(text)
    assert result.records[0]["author"] == [{"literal": "WorldHealthOrganization"}]


def test_doi_extracted_from_aid_doi_suffix() -> None:
    text = "PMID- 1\nTI  - T\nAID - 10.1/example [doi]\nAID - S0028-3932(08)00174-3 [pii]\n"
    result = parse(text)
    assert result.records[0]["DOI"] == "10.1/example"


def test_doi_prefers_lid_over_aid() -> None:
    text = "PMID- 1\nTI  - T\nLID - 10.1/from-lid [doi]\nAID - 10.1/from-aid [doi]\n"
    result = parse(text)
    assert result.records[0]["DOI"] == "10.1/from-lid"


def test_pmc_id_normalised_with_prefix() -> None:
    text = "PMID- 1\nTI  - T\nPMC - 123456\n"
    result = parse(text)
    assert result.records[0]["PMCID"] == "PMC123456"


def test_journal_prefers_jt_over_ta() -> None:
    text = "PMID- 1\nTI  - T\nTA  - Psychol Sci\nJT  - Psychological Science\n"
    result = parse(text)
    assert result.records[0]["container-title"] == "Psychological Science"


def test_journal_falls_back_to_ta() -> None:
    text = "PMID- 1\nTI  - T\nTA  - Psychol Sci\n"
    result = parse(text)
    assert result.records[0]["container-title"] == "Psychol Sci"


def test_html_entity_in_title_decoded() -> None:
    text = "PMID- 1\nTI  - Salt &amp; pepper\n"
    result = parse(text)
    assert result.records[0]["title"] == "Salt & pepper"


def test_two_records_separated_by_blank_line() -> None:
    text = "PMID- 1\nTI  - First\n\nPMID- 2\nTI  - Second\n"
    result = parse(text)
    assert [r["title"] for r in result.records] == ["First", "Second"]


def test_empty_title_rejected_without_aborting_later_records() -> None:
    text = "PMID- 1\nTI  -\n\nPMID- 2\nTI  - Good record\n"
    result = parse(text)
    assert [r["title"] for r in result.records] == ["Good record"]
    assert len(result.rejected) == 1
    assert result.rejected[0].error == "missing or empty title"


def test_corporate_author_via_cn_tag() -> None:
    text = "PMID- 1\nTI  - T\nFAU - Doe, Jane\nCN  - World Health Organization\n"
    result = parse(text)
    assert result.records[0]["author"] == [
        {"family": "Doe", "given": "Jane"},
        {"literal": "World Health Organization"},
    ]


def test_mesh_headings_joined_as_keyword() -> None:
    text = "PMID- 1\nTI  - T\nMH  - Adult\nMH  - Humans\n"
    result = parse(text)
    assert result.records[0]["keyword"] == "Adult; Humans"


def test_no_trailing_newline_still_flushes_final_record() -> None:
    result = parse("PMID- 1\nTI  - No trailing newline")
    assert result.records[0]["title"] == "No trailing newline"


def test_stray_text_before_first_tag_is_ignored() -> None:
    text = "Some stray header text\nPMID- 1\nTI  - T\n"
    result = parse(text)
    assert result.records[0]["PMID"] == "1"


def test_fau_without_comma_becomes_literal() -> None:
    text = "PMID- 1\nTI  - T\nFAU - CorporateNameWithoutComma\n"
    result = parse(text)
    assert result.records[0]["author"] == [{"literal": "CorporateNameWithoutComma"}]


def test_blank_fau_entry_skipped() -> None:
    text = "PMID- 1\nTI  - T\nFAU - \nFAU - Doe, Jane\n"
    result = parse(text)
    assert result.records[0]["author"] == [{"family": "Doe", "given": "Jane"}]


def test_blank_au_entry_skipped() -> None:
    text = "PMID- 1\nTI  - T\nAU  - \nAU  - Doe JQ\n"
    result = parse(text)
    assert result.records[0]["author"] == [{"family": "Doe", "given": "JQ"}]


def test_blank_cn_entry_ignored() -> None:
    text = "PMID- 1\nTI  - T\nFAU - Doe, Jane\nCN  - \n"
    result = parse(text)
    assert result.records[0]["author"] == [{"family": "Doe", "given": "Jane"}]


def test_doi_skips_non_doi_tagged_locators_before_the_real_one() -> None:
    text = "PMID- 1\nTI  - T\nAID - S0028-3932(08)00174-3 [pii]\nAID - 10.1/example [doi]\n"
    result = parse(text)
    assert result.records[0]["DOI"] == "10.1/example"


def test_record_without_pmid_has_no_pmid_field() -> None:
    result = parse("TI  - No PMID here\n")
    assert "PMID" not in result.records[0]
