"""Excel (`.xlsx`) reader.

Implements the Excel row of openspec:literature-import: read-only, the first sheet unless one is
named. An `.xlsx` file is a zip archive of XML parts, so this reads it with the standard library
only (no formula engine, no macros, no external references, no new dependency) and treats it as the
untrusted input it is:

- the file, the unpacked parts, the number of rows and columns and the size of a cell are capped;
- a part with a DOCTYPE or entity declaration is refused;
- formulas are never evaluated; the value Excel cached with the cell is what is read;
- dates stored as numbers come through as the serial number Excel keeps them as (a year typed as a
  number or as text is read as written).

The sheet is turned into tab-separated text (`rows_to_tsv`) and then goes through the same column
mapping and parser as a TSV export.
"""

from __future__ import annotations

import csv
import io
import re
import xml.etree.ElementTree as ET
import zipfile
import zlib
from collections.abc import Iterator

MAX_FILE_BYTES = 50 * 1024 * 1024
MAX_PART_BYTES = 200 * 1024 * 1024
MAX_ROWS = 250_000
MAX_COLUMNS = 512
MAX_CELL_CHARS = 100_000

_NS = {
    "m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
}
_UNSAFE_RE = re.compile(rb"<!(?:DOCTYPE|ENTITY)", re.IGNORECASE)
_CELL_REF_RE = re.compile(r"^([A-Za-z]+)")
_OLE2_MAGIC = b"\xd0\xcf\x11\xe0"


class XlsxError(ValueError):
    """The workbook cannot be read; the message says why in terms a user can act on."""


def _column_index(reference: str) -> int:
    match = _CELL_REF_RE.match(reference)
    if not match:
        raise XlsxError(f"cell reference {reference!r} is not understood")
    index = 0
    for letter in match.group(1).upper():
        index = index * 26 + (ord(letter) - ord("A") + 1)
    return index - 1


def _open(raw: bytes) -> zipfile.ZipFile:
    if len(raw) > MAX_FILE_BYTES:
        raise XlsxError(f"the file is larger than the {MAX_FILE_BYTES // (1024 * 1024)} MB limit")
    if raw.startswith(_OLE2_MAGIC):
        raise XlsxError(
            "this is an encrypted or legacy .xls workbook; save it as an unprotected .xlsx "
            "(or export to CSV) and import that"
        )
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile:
        raise XlsxError("this is not an .xlsx workbook (not a zip archive)") from None
    if sum(info.file_size for info in archive.infolist()) > MAX_PART_BYTES:
        raise XlsxError("the workbook expands to more than the allowed size")
    return archive


def _part(archive: zipfile.ZipFile, name: str) -> bytes:
    try:
        info = archive.getinfo(name)
    except KeyError:
        raise XlsxError(f"the workbook has no {name}") from None
    if info.file_size > MAX_PART_BYTES:
        raise XlsxError(f"{name} is larger than the allowed size")
    try:
        data = archive.read(info)
    except (
        zipfile.BadZipFile,
        zlib.error,
        RuntimeError,
        NotImplementedError,
        EOFError,
        OSError,
        ValueError,
    ):
        raise XlsxError(f"{name} is damaged or uses an unsupported kind of compression") from None
    if _UNSAFE_RE.search(data):
        raise XlsxError(f"{name} declares entities, which are not accepted")
    return data


def _parse(data: bytes, name: str) -> ET.Element:
    try:
        return ET.fromstring(data)
    except ET.ParseError as exc:
        raise XlsxError(f"{name} is not valid XML: {exc}") from None


def _sheets(archive: zipfile.ZipFile) -> list[tuple[str, str]]:
    """`(name, part path)` for each sheet, in workbook order."""
    workbook = _parse(_part(archive, "xl/workbook.xml"), "xl/workbook.xml")
    targets: dict[str, str] = {}
    if "xl/_rels/workbook.xml.rels" in archive.namelist():
        rels = _parse(_part(archive, "xl/_rels/workbook.xml.rels"), "xl/_rels/workbook.xml.rels")
        for rel in rels.findall("rel:Relationship", _NS):
            target = rel.get("Target") or ""
            targets[rel.get("Id") or ""] = (
                target.lstrip("/") if target.startswith("/") else f"xl/{target}"
            )
    found = []
    for index, sheet in enumerate(workbook.findall("m:sheets/m:sheet", _NS), start=1):
        rid = sheet.get(f"{{{_NS['r']}}}id") or ""
        found.append(
            (
                sheet.get("name") or f"Sheet{index}",
                targets.get(rid, f"xl/worksheets/sheet{index}.xml"),
            )
        )
    if not found:
        raise XlsxError("the workbook has no sheets")
    return found


def sheet_names(raw: bytes) -> list[str]:
    return [name for name, _ in _sheets(_open(raw))]


def _item_text(item: ET.Element) -> str:
    """Every text run of a shared string, except phonetic hints (<rPh>)."""
    text_tag = f"{{{_NS['m']}}}t"
    hints = {id(t) for ph in item.iter(f"{{{_NS['m']}}}rPh") for t in ph.iter(text_tag)}
    return "".join(t.text or "" for t in item.iter(text_tag) if id(t) not in hints)


def _shared_strings(archive: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    root = _parse(_part(archive, "xl/sharedStrings.xml"), "xl/sharedStrings.xml")
    return [_item_text(si) for si in root.findall("m:si", _NS)]


def _cell_value(cell: ET.Element, shared: list[str]) -> str:
    kind = cell.get("t") or "n"
    if kind == "inlineStr":
        return "".join(t.text or "" for t in cell.iter(f"{{{_NS['m']}}}t"))
    value = cell.find("m:v", _NS)
    text = value.text if value is not None and value.text is not None else ""
    if kind == "s":
        try:
            return shared[int(text)]
        except (ValueError, IndexError):
            return ""
    if kind == "b":
        return "TRUE" if text.strip() == "1" else "FALSE"
    if kind == "e":
        return ""
    if kind == "n" and re.fullmatch(r"-?\d+\.0+", text):
        return text.split(".")[0]
    return text


def _rows(archive: zipfile.ZipFile, part: str, shared: list[str]) -> Iterator[list[str]]:
    root = _parse(_part(archive, part), part)
    count = 0
    expected = 1
    for row in root.iter(f"{{{_NS['m']}}}row"):
        try:
            number = int(row.get("r") or expected)
        except ValueError:
            raise XlsxError("a row has a number that is not understood") from None
        if number > MAX_ROWS:
            raise XlsxError(f"the sheet has more than {MAX_ROWS} rows")
        for _ in range(number - expected):  # blank rows between used ones
            yield []
            count += 1
        expected = number + 1
        cells: dict[int, str] = {}
        position = 0
        for cell in row.findall("m:c", _NS):
            reference = cell.get("r")
            index = _column_index(reference) if reference else position
            position = index + 1
            if index >= MAX_COLUMNS:
                raise XlsxError(f"the sheet has more than {MAX_COLUMNS} columns")
            value = _cell_value(cell, shared)
            if len(value) > MAX_CELL_CHARS:
                raise XlsxError(
                    f"a cell in row {number} is longer than {MAX_CELL_CHARS} characters"
                )
            cells[index] = value
        yield [cells.get(i, "") for i in range(max(cells, default=-1) + 1)]
        count += 1
        if count > MAX_ROWS:
            raise XlsxError(f"the sheet has more than {MAX_ROWS} rows")


def read_rows(raw: bytes, sheet: str | None = None) -> tuple[str, list[list[str]]]:
    """`(sheet name, rows)` of the named sheet (or its 1-based position), else the first one.

    Trailing blank rows are dropped; `XlsxError` for anything that cannot be read.
    """
    archive = _open(raw)
    sheets = _sheets(archive)
    chosen = sheets[0]
    if sheet is not None:
        by_name = [s for s in sheets if s[0].lower() == sheet.lower()]
        if by_name:
            chosen = by_name[0]
        elif sheet.isdigit() and 1 <= int(sheet) <= len(sheets):
            chosen = sheets[int(sheet) - 1]
        else:
            names = ", ".join(repr(name) for name, _ in sheets)
            raise XlsxError(f"there is no sheet {sheet!r}; the workbook has {names}")
    rows = list(_rows(archive, chosen[1], _shared_strings(archive)))
    while rows and not any(cell.strip() for cell in rows[-1]):
        rows.pop()
    if not rows:
        raise XlsxError(f"sheet {chosen[0]!r} is empty")
    return chosen[0], rows


def rows_to_tsv(rows: list[list[str]]) -> str:
    """The rows as tab-separated text, quoting any cell with a tab, quote or line break."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter="\t", lineterminator="\n")
    width = max(len(row) for row in rows)
    for row in rows:
        writer.writerow([*row, *[""] * (width - len(row))])
    return buffer.getvalue()
