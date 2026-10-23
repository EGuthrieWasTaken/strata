"""The EndNote XML parser: openspec:literature-import#supported-import-formats and #tolerant-parsing."""

# ruff: noqa: E501
from __future__ import annotations

from strata.ingest.parsers import endnote_xml


def _wrap(*records: str) -> str:
    return '<?xml version="1.0"?>\n<xml><records>\n' + "\n".join(records) + "\n</records></xml>\n"


def _record(inner: str, ref_type: str = '<ref-type name="Journal Article">17</ref-type>') -> str:
    return f"<record>{ref_type}{inner}</record>"


def test_style_nested_text_nodes_are_read() -> None:
    xml = _wrap(
        _record(
            "<titles><title><style face='normal'>A <style>nested</style> title</style></title></titles>"
            "<dates><year><style>2020</style></year></dates>"
        )
    )
    result = endnote_xml.parse(xml)
    assert result.records[0]["title"] == "A nested title"
    assert result.records[0]["issued"] == {"date-parts": [[2020]]}


def test_a_year_in_pub_dates_is_found_when_there_is_no_year_element() -> None:
    xml = _wrap(
        _record(
            "<titles><title>T</title></titles><dates><pub-dates><date>Mar 2015</date></pub-dates></dates>"
        )
    )
    assert endnote_xml.parse(xml).records[0]["issued"] == {"date-parts": [[2015]]}


def test_author_names() -> None:
    xml = _wrap(
        _record(
            "<titles><title>T</title></titles><contributors><authors>"
            "<author>Family, Given M.</author><author>Family Only,</author><author>An Institute</author><author>  </author>"
            "</authors></contributors>"
        )
    )
    assert endnote_xml.parse(xml).records[0]["author"] == [
        {"family": "Family", "given": "Given M."},
        {"family": "Family Only"},
        {"literal": "An Institute"},
    ]


def test_reference_types_by_name_then_number() -> None:
    kinds = []
    for ref_type in (
        '<ref-type name="Book Section">5</ref-type>',
        '<ref-type name="">32</ref-type>',
        '<ref-type name="Something New">999</ref-type>',
    ):
        xml = _wrap(_record("<titles><title>T</title></titles>", ref_type))
        kinds.append(endnote_xml.parse(xml).records[0]["type"])
    assert kinds == ["chapter", "thesis", "article-journal"]


def test_an_unescaped_ampersand_and_html_entities_are_repaired() -> None:
    xml = _wrap(
        _record(
            "<titles><title>Smith &amp; Jones &caf; R&D &eacute;tudes &#233; &lt;b&gt;</title></titles>"
        )
    )
    title = endnote_xml.parse(xml).records[0]["title"]
    assert (
        title.startswith("Smith & Jones") and "R&D" in title and "études" in title and "é" in title
    )


def test_one_malformed_record_does_not_lose_the_rest() -> None:
    xml = _wrap(
        _record("<titles><title>First</title></titles>"),
        "<record><titles><title>Cut off",
        _record("<titles><title>Third</title></titles>"),
    )
    result = endnote_xml.parse(xml)
    assert [r["title"] for r in result.records] == ["First", "Third"]
    assert len(result.rejected) == 1 and "malformed XML" in result.rejected[0].error
    assert result.rejected[0].line is not None


def test_a_record_without_a_title_is_rejected_with_its_line() -> None:
    xml = _wrap(_record("<titles><title><style></style></title></titles>"))
    result = endnote_xml.parse(xml)
    assert result.records == [] and result.rejected[0].error == "missing or empty title"
    assert result.rejected[0].line == 3


def test_a_file_with_no_records_is_a_document_level_rejection() -> None:
    result = endnote_xml.parse("<xml><records></records></xml>")
    assert result.records == [] and result.rejected[0].line is None


def test_entity_declarations_are_never_honoured() -> None:
    hostile = (
        '<?xml version="1.0"?>\n<!DOCTYPE xml [<!ENTITY boom "BOOM">]>\n<xml><records>'
        "<record><titles><title>&boom;</title></titles></record>"
        "<record><!DOCTYPE x><titles><title>inside</title></titles></record>"
        "</records></xml>"
    )
    result = endnote_xml.parse(hostile)
    assert [r["title"] for r in result.records] == [
        "&boom;"
    ]  # the declaration outside is not applied
    assert [r.error for r in result.rejected] == ["DOCTYPE and entity declarations are refused"]


def test_doi_keywords_url_language_and_pages() -> None:
    xml = _wrap(
        _record(
            "<titles><title>T</title></titles><pages>10-20</pages><volume>4</volume><number>2</number>"
            "<electronic-resource-num>10.1000/x</electronic-resource-num>"
            "<keywords><keyword>a</keyword><keyword> </keyword><keyword>b</keyword></keywords>"
            "<urls><related-urls><url>https://example.org/x</url></related-urls></urls>"
            "<language>German</language><periodical><full-title>Journal of X</full-title></periodical>"
        )
    )
    record = endnote_xml.parse(xml).records[0]
    assert (record["DOI"], record["keyword"], record["URL"], record["language"]) == (
        "10.1000/x", "a; b", "https://example.org/x", "German",
    )  # fmt: skip
    assert (record["page"], record["volume"], record["issue"], record["container-title"]) == (
        "10-20", "4", "2", "Journal of X",
    )  # fmt: skip
