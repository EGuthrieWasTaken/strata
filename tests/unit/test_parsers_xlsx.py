"""The Excel reader: openspec:literature-import#supported-import-formats (read-only, first sheet
unless one is named) and its size caps."""

# ruff: noqa: E501
from __future__ import annotations

import io
import zipfile

import pytest

from strata.ingest.parsers import csv_tsv
from strata.ingest.parsers import xlsx as xlsx_parser
from tests.unit._xlsx import build_xlsx, column_letters, rewrite_part

HEADER = ["Title", "Authors", "Year", "DOI"]
ROWS = [
    HEADER,
    [
        "Spacing effects in learning",
        "Cepeda, N.; Vul, E.",
        2008,
        "10.1111/j.1467-9280.2008.02209.x",
    ],
    ["Retrieval practice", "Roediger, H.", 2006, None],
]


def test_the_first_sheet_is_read_by_default() -> None:
    raw = build_xlsx({"Export": ROWS, "Notes": [["not", "this"]]})
    name, rows = xlsx_parser.read_rows(raw)
    assert name == "Export" and rows[0] == HEADER
    assert rows[1] == [
        "Spacing effects in learning",
        "Cepeda, N.; Vul, E.",
        "2008",
        "10.1111/j.1467-9280.2008.02209.x",
    ]
    assert rows[2] == [
        "Retrieval practice",
        "Roediger, H.",
        "2006",
    ]  # a missing last cell is just short


def test_a_sheet_can_be_chosen_by_name_or_position() -> None:
    raw = build_xlsx({"Export": ROWS, "Second": [["a"], ["b"]]})
    assert xlsx_parser.read_rows(raw, "second")[0] == "Second"  # names are matched without case
    assert xlsx_parser.read_rows(raw, "2")[1] == [["a"], ["b"]]
    assert xlsx_parser.sheet_names(raw) == ["Export", "Second"]
    with pytest.raises(xlsx_parser.XlsxError, match="no sheet 'Missing'.*'Export', 'Second'"):
        xlsx_parser.read_rows(raw, "Missing")


def test_inline_strings_numbers_booleans_and_gaps() -> None:
    raw = build_xlsx(
        {"S": [["a", None, "c"], [1.0, 2.5, True], [None, None, None], ["end"]]}, inline=True
    )
    _name, rows = xlsx_parser.read_rows(raw)
    assert rows == [["a", "", "c"], ["1", "2.5", "TRUE"], [], ["end"]]


def test_columns_past_z_are_placed_correctly() -> None:
    assert [column_letters(i) for i in (0, 25, 26, 27, 701, 702)] == [
        "A",
        "Z",
        "AA",
        "AB",
        "ZZ",
        "AAA",
    ]
    row: list[object] = [None] * 28 + ["far"]
    _name, rows = xlsx_parser.read_rows(build_xlsx({"S": [row]}))
    assert len(rows[0]) == 29 and rows[0][28] == "far"


def test_trailing_blank_rows_are_dropped_and_an_empty_sheet_is_an_error() -> None:
    _name, rows = xlsx_parser.read_rows(build_xlsx({"S": [["x"], [None], [" "]]}))
    assert rows == [["x"]]
    with pytest.raises(xlsx_parser.XlsxError, match="empty"):
        xlsx_parser.read_rows(build_xlsx({"S": [[None]]}))


def test_the_sheet_goes_through_the_same_parser_as_a_tsv_export() -> None:
    _name, rows = xlsx_parser.read_rows(build_xlsx({"S": ROWS}))
    text = xlsx_parser.rows_to_tsv(rows)
    result = csv_tsv.parse(
        text,
        delimiter="\t",
        mapping={"title": "Title", "author": "Authors", "year": "Year", "DOI": "DOI"},
    )
    assert [r["title"] for r in result.records] == [
        "Spacing effects in learning",
        "Retrieval practice",
    ]
    assert result.records[0]["DOI"] == "10.1111/j.1467-9280.2008.02209.x"
    assert result.rejected == []


def test_cells_with_tabs_quotes_and_line_breaks_survive_the_tsv() -> None:
    rows = [["Title", "Abstract"], ['A "quoted"\ttitle', "line one\nline two"]]
    text = xlsx_parser.rows_to_tsv(xlsx_parser.read_rows(build_xlsx({"S": rows}))[1])
    result = csv_tsv.parse(text, delimiter="\t", mapping={"title": "Title", "abstract": "Abstract"})
    assert result.records[0]["title"] == 'A "quoted"\ttitle'
    assert result.records[0]["abstract"] == "line one\nline two"


def test_the_value_excel_cached_for_a_formula_is_what_is_read() -> None:
    raw = build_xlsx({"S": [["a"]]})
    sheet = (
        '<?xml version="1.0"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<sheetData><row r="1"><c r="A1" t="str"><f>1+1</f><v>cached text</v></c><c r="B1"><f>2+2</f><v>4</v></c>'
        '<c r="C1" t="e"><v>#DIV/0!</v></c></row></sheetData></worksheet>'
    )
    _name, rows = xlsx_parser.read_rows(rewrite_part(raw, "xl/worksheets/sheet1.xml", sheet))
    assert rows == [["cached text", "4", ""]]


def test_rich_text_shared_strings_drop_phonetic_hints() -> None:
    raw = build_xlsx({"S": [["x"]]})
    strings = (
        '<?xml version="1.0"?><sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        "<si><r><t>Rich </t></r><r><t>text</t></r><rPh><t>かな</t></rPh></si></sst>"
    )
    _name, rows = xlsx_parser.read_rows(rewrite_part(raw, "xl/sharedStrings.xml", strings))
    assert rows == [["Rich text"]]


# --- refusing what should not be read -----------------------------------------------------------


def test_something_that_is_not_a_workbook_is_refused_with_advice() -> None:
    with pytest.raises(xlsx_parser.XlsxError, match="not an .xlsx workbook"):
        xlsx_parser.read_rows(b"just some text")
    with pytest.raises(xlsx_parser.XlsxError, match=r"encrypted or legacy .xls"):
        xlsx_parser.read_rows(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 64)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("readme.txt", "a zip, but not a workbook")
    with pytest.raises(xlsx_parser.XlsxError, match="no xl/workbook.xml"):
        xlsx_parser.read_rows(buffer.getvalue())


def test_a_part_that_declares_entities_is_refused() -> None:
    raw = build_xlsx({"S": [["x"]]})
    hostile = '<?xml version="1.0"?><!DOCTYPE s [<!ENTITY a "boom">]><sst xmlns="x"><si><t>&a;</t></si></sst>'
    with pytest.raises(xlsx_parser.XlsxError, match="declares entities"):
        xlsx_parser.read_rows(rewrite_part(raw, "xl/sharedStrings.xml", hostile))


def test_invalid_xml_in_a_part_is_an_error_not_a_crash() -> None:
    raw = rewrite_part(
        build_xlsx({"S": [["x"]]}), "xl/worksheets/sheet1.xml", "<worksheet><sheetData>"
    )
    with pytest.raises(xlsx_parser.XlsxError, match="not valid XML"):
        xlsx_parser.read_rows(raw)


def test_size_caps(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = build_xlsx({"S": [["a", "b"], ["c", "d"], ["e", "f"]]})
    monkeypatch.setattr(xlsx_parser, "MAX_ROWS", 2)
    with pytest.raises(xlsx_parser.XlsxError, match="more than 2 rows"):
        xlsx_parser.read_rows(raw)
    monkeypatch.undo()
    monkeypatch.setattr(xlsx_parser, "MAX_COLUMNS", 1)
    with pytest.raises(xlsx_parser.XlsxError, match="more than 1 columns"):
        xlsx_parser.read_rows(raw)
    monkeypatch.undo()
    monkeypatch.setattr(xlsx_parser, "MAX_CELL_CHARS", 3)
    with pytest.raises(xlsx_parser.XlsxError, match="longer than 3 characters"):
        xlsx_parser.read_rows(build_xlsx({"S": [["toolong"]]}))
    monkeypatch.undo()
    monkeypatch.setattr(xlsx_parser, "MAX_FILE_BYTES", 10)
    with pytest.raises(xlsx_parser.XlsxError, match="larger than the"):
        xlsx_parser.read_rows(raw)
    monkeypatch.undo()
    monkeypatch.setattr(xlsx_parser, "MAX_PART_BYTES", 10)
    with pytest.raises(xlsx_parser.XlsxError, match="expands to more than"):
        xlsx_parser.read_rows(raw)


def test_a_zip_bomb_is_stopped_by_the_declared_size() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("xl/workbook.xml", "<workbook/>")
        archive.writestr("xl/worksheets/sheet1.xml", b"0" * (xlsx_parser.MAX_PART_BYTES + 1))
    assert len(buffer.getvalue()) < xlsx_parser.MAX_FILE_BYTES  # compresses to almost nothing
    with pytest.raises(xlsx_parser.XlsxError, match="expands to more than"):
        xlsx_parser.read_rows(buffer.getvalue())
