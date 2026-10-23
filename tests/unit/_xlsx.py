"""Builds small `.xlsx` workbooks for tests, so no binary fixture has to be committed."""

from __future__ import annotations

import io
import zipfile
from typing import Any
from xml.sax.saxutils import escape

MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def column_letters(index: int) -> str:
    letters = ""
    index += 1
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(ord("A") + remainder) + letters
    return letters


def _sheet_xml(rows: list[list[Any]], shared: list[str], *, inline: bool) -> str:
    out = [f'<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="{MAIN}"><sheetData>']
    for number, row in enumerate(rows, start=1):
        cells = []
        for index, value in enumerate(row):
            if value is None:
                continue
            ref = f"{column_letters(index)}{number}"
            if isinstance(value, bool):
                cells.append(f'<c r="{ref}" t="b"><v>{int(value)}</v></c>')
            elif isinstance(value, int | float):
                cells.append(f'<c r="{ref}"><v>{value}</v></c>')
            elif inline:
                cells.append(f'<c r="{ref}" t="inlineStr"><is><t>{escape(str(value))}</t></is></c>')
            else:
                shared.append(str(value))
                cells.append(f'<c r="{ref}" t="s"><v>{len(shared) - 1}</v></c>')
        out.append(f'<row r="{number}">{"".join(cells)}</row>')
    out.append("</sheetData></worksheet>")
    return "".join(out)


def build_xlsx(sheets: dict[str, list[list[Any]]], *, inline: bool = False) -> bytes:
    """A workbook with the given sheets (name -> rows); `None` cells are left out of the file."""
    shared: list[str] = []
    parts: dict[str, str] = {}
    names = list(sheets)
    for number, name in enumerate(names, start=1):
        parts[f"xl/worksheets/sheet{number}.xml"] = _sheet_xml(sheets[name], shared, inline=inline)
    sheet_tags = "".join(
        f'<sheet name="{escape(name)}" sheetId="{n}" r:id="rId{n}"/>'
        for n, name in enumerate(names, start=1)
    )
    rel_tags = "".join(
        f'<Relationship Id="rId{n}" Type="{REL}/worksheet" Target="worksheets/sheet{n}.xml"/>'
        for n in range(1, len(names) + 1)
    )
    parts["xl/workbook.xml"] = (
        f'<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="{MAIN}" xmlns:r="{REL}">'
        f"<sheets>{sheet_tags}</sheets></workbook>"
    )
    parts["xl/_rels/workbook.xml.rels"] = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">{rel_tags}</Relationships>'
    )
    if shared:
        items = "".join(f"<si><t>{escape(s)}</t></si>" for s in shared)
        parts["xl/sharedStrings.xml"] = (
            f'<?xml version="1.0" encoding="UTF-8"?><sst xmlns="{MAIN}">{items}</sst>'
        )
    parts["[Content_Types].xml"] = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>'
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, text in parts.items():
            archive.writestr(name, text)
    return buffer.getvalue()


def rewrite_part(workbook: bytes, part: str, text: str) -> bytes:
    """The workbook with one part's XML replaced."""
    source = zipfile.ZipFile(io.BytesIO(workbook))
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for info in source.infolist():
            archive.writestr(info.filename, text if info.filename == part else source.read(info))
    return buffer.getvalue()
