# ruff: noqa: E501  (the OOXML parts below are long literal strings)
"""`strata export effects`: one row per effect, ready for analysis outside `strata`.

Implements openspec:data-extraction#exporting-effects-for-outside-analysis. The table has the
columns `metafor::rma(yi, vi, data = ...)` expects (`yi`, `vi`) beside `study_id` and `effect_id`,
the effect's inputs and provenance flags, every study-level field, and the effect-level
moderators. It is generated output: the same data always produces the same bytes (fixed ZIP
timestamps, uncompressed RDS, sorted rows), so it can be checked in and diffed.

XLSX and RDS are written directly (a minimal OOXML workbook and an R `data.frame` in R's XDR
serialisation, version 2) rather than through a library, so exporting adds no dependency.
"""

from __future__ import annotations

import io
import math
import struct
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from xml.sax.saxutils import escape

from strata.core.canon import canonical_json
from strata.core.repo import Repo
from strata.extract import effects as effects_mod
from strata.extract import records as rec_mod
from strata.extract import schema as schema_mod
from strata.protocol import studies as studies_mod
from strata.stats import effect_sizes as es

FORMATS = ("csv", "tsv", "xlsx", "rds", "json")
_HEAD = ("study_id", "effect_id", "outcome", "design", "timepoint", "label", "measure", "yi", "vi")
_DETAIL_COLUMNS = (
    "derived_from",
    "derived_from_pvalue",
    "assumed_correlation",
    "continuity_correction",
    "variance_convention",
)
_NOT_INPUT = frozenset({"id", "outcome", "design", "timepoint", "label", "source", "moderators"})

Cell = Any
Extras = Callable[[str], dict[str, Cell]]


class ExportError(ValueError):
    pass


@dataclass
class Table:
    columns: list[str] = field(default_factory=list)
    rows: list[dict[str, Cell]] = field(default_factory=list)


def _flat(entry: dict[str, Any] | None) -> Cell:
    if entry is None or entry.get("not_reported"):
        return None
    value = entry.get("value")
    return ";".join(str(v) for v in value) if isinstance(value, list) else value


def effect_table(repo: Repo, *, extras: Extras | None = None) -> Table:
    """The effects table for every included study that has a consensus extraction.

    `extras(study)` supplies further study-level columns (risk-of-bias moderators, for one).
    """
    schema = schema_mod.load_schema(repo)
    members = studies_mod.study_map(repo).members
    field_names = [f["name"] for f in schema.fields]
    consensus = {
        r["study"]: r
        for kind, _h, r, _p in rec_mod.all_records(repo)
        if kind == "consensus" and r.get("study") in members
    }

    rows: list[dict[str, Cell]] = []
    input_names: set[str] = set()
    moderator_names: set[str] = set()
    extra_names: set[str] = set()
    for study in sorted(consensus):
        record = consensus[study]
        study_cells = {n: _flat(record["fields"].get(n)) for n in field_names}
        study_extra = extras(study) if extras else {}
        extra_names.update(study_extra)
        for effect in sorted(record.get("effects", []), key=lambda e: str(e.get("id", ""))):
            row: dict[str, Cell] = {
                "study_id": study,
                "effect_id": effect.get("id"),
                "outcome": effect.get("outcome"),
                "design": effect.get("design"),
                "timepoint": effect.get("timepoint"),
                "label": effect.get("label"),
                "source": effect.get("source"),
            }
            try:
                computed: es.EffectSize | None = effects_mod.compute(effect["design"], effect)
            except (effects_mod.EffectInputError, es.EffectSizeError):
                computed = None
            row["measure"] = computed.measure if computed else None
            row["yi"] = computed.yi if computed else None
            row["vi"] = computed.vi if computed else None
            for name in _DETAIL_COLUMNS:
                row[name] = computed.details.get(name) if computed else None
            row.update({f"@field:{n}": v for n, v in study_cells.items()})
            row.update({f"@extra:{n}": v for n, v in study_extra.items()})
            inputs = {k: v for k, v in effect.items() if k not in _NOT_INPUT}
            input_names.update(inputs)
            row.update({f"@input:{n}": v for n, v in inputs.items()})
            mods = effect.get("moderators") or {}
            moderator_names.update(mods)
            row.update({f"@mod:{n}": v for n, v in mods.items()})
            rows.append(row)

    columns = list(_HEAD) + list(_DETAIL_COLUMNS) + ["source"]
    taken = set(columns)
    names: dict[str, str] = {}

    def claim(kind: str, name: str) -> None:
        final = name if name not in taken else f"{kind}_{name}"
        while final in taken:
            final = f"{final}_"
        taken.add(final)
        names[f"@{kind}:{name}"] = final
        columns.append(final)

    for n in field_names:
        claim("field", n)
    for n in sorted(extra_names):
        claim("extra", n)
    for n in sorted(input_names):
        claim("input", n)
    for n in sorted(moderator_names):
        claim("mod", n)
    table = Table(columns=columns)
    for row in rows:
        renamed = {names.get(k, k): v for k, v in row.items()}
        table.rows.append({c: renamed.get(c) for c in columns})  # every row has every column
    return table


# --- text formats ----------------------------------------------------------------------------


def _text(value: Cell) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, float):
        return repr(value)
    return str(value)


def _delimited(table: Table, sep: str) -> bytes:
    def cell(value: Cell) -> str:
        text = _text(value)
        if sep == "\t":
            return text.replace("\t", " ").replace("\r", " ").replace("\n", " ")
        if any(c in text for c in ('"', ",", "\n", "\r")):
            return '"' + text.replace('"', '""') + '"'
        return text

    lines = [sep.join(cell(c) for c in table.columns)]
    lines.extend(sep.join(cell(row.get(c)) for c in table.columns) for row in table.rows)
    return ("\n".join(lines) + "\n").encode("utf-8")


def _json(table: Table) -> bytes:
    body = ",\n".join(
        "  " + canonical_json({c: row.get(c) for c in table.columns}) for row in table.rows
    )
    return (("[\n" + body + "\n]\n") if table.rows else "[]\n").encode("utf-8")


# --- xlsx ------------------------------------------------------------------------------------


def _column_letter(index: int) -> str:
    letters = ""
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def _xlsx(table: Table) -> bytes:
    def cell(ref: str, value: Cell) -> str:
        if value is None:
            return ""
        if isinstance(value, bool):
            return f'<c r="{ref}" t="b"><v>{int(value)}</v></c>'
        if isinstance(value, (int, float)):
            return f'<c r="{ref}"><v>{value!r}</v></c>'
        return f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">{escape(str(value))}</t></is></c>'

    sheet_rows = []
    for r, values in enumerate(
        [table.columns] + [[row.get(c) for c in table.columns] for row in table.rows]
    ):
        cells = "".join(cell(f"{_column_letter(c)}{r + 1}", v) for c, v in enumerate(values))
        sheet_rows.append(f'<row r="{r + 1}">{cells}</row>')
    parts = {
        "[Content_Types].xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
            "</Types>"
        ),
        "_rels/.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            "</Relationships>"
        ),
        "xl/workbook.xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="effects" sheetId="1" r:id="rId1"/></sheets></workbook>'
        ),
        "xl/_rels/workbook.xml.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
            "</Relationships>"
        ),
        "xl/styles.xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            '<fonts count="1"><font><sz val="11"/><name val="Calibri"/></font></fonts>'
            '<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>'
            '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
            '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
            '<cellXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/></cellXfs>'
            '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
            "</styleSheet>"
        ),
        "xl/worksheets/sheet1.xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f"<sheetData>{''.join(sheet_rows)}</sheetData></worksheet>"
        ),
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(parts):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, parts[name].encode("utf-8"))
    return buffer.getvalue()


# --- rds -------------------------------------------------------------------------------------

_NA_REAL = struct.pack(">Q", 0x7FF00000000007A2)
_NA_INT = -(2**31)


def _int(n: int) -> bytes:
    return struct.pack(">i", n)


def _rds_charsxp(text: str | None) -> bytes:
    if text is None:
        return _int(9) + _int(-1)  # NA_STRING
    raw = text.encode("utf-8")
    levels = 0x40 if all(b < 128 for b in raw) else 0x08  # ASCII / UTF-8 mark
    return _int(9 | (levels << 12)) + _int(len(raw)) + raw


def _rds_strsxp(values: list[str | None]) -> bytes:
    return _int(16) + _int(len(values)) + b"".join(_rds_charsxp(v) for v in values)


def _rds_symbol(name: str) -> bytes:
    return _int(1) + _rds_charsxp(name)


def _rds_column(values: list[Cell]) -> bytes:
    present = [v for v in values if v is not None]
    if all(isinstance(v, bool) for v in present) and present:
        return (
            _int(10)
            + _int(len(values))
            + b"".join(_int(_NA_INT if v is None else int(v)) for v in values)
        )
    if (
        present
        and all(isinstance(v, int) and not isinstance(v, bool) for v in present)
        and all(abs(v) < 2**31 - 1 for v in present)
    ):
        return (
            _int(13)
            + _int(len(values))
            + b"".join(_int(_NA_INT if v is None else v) for v in values)
        )
    if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in present):
        return (
            _int(14)
            + _int(len(values))
            + b"".join(_NA_REAL if v is None else struct.pack(">d", float(v)) for v in values)
        )
    return _rds_strsxp([None if v is None else _text(v) for v in values])


def _rds(table: Table) -> bytes:
    columns = [[row.get(c) for row in table.rows] for c in table.columns]
    for column in columns:
        for value in column:
            if isinstance(value, float) and not math.isfinite(value):
                raise ExportError("NaN and Infinity cannot be exported")
    out = io.BytesIO()
    out.write(b"X\n" + _int(2) + _int(0x00030500) + _int(0x00020300))  # XDR, version 2
    out.write(_int(19 | 0x100 | 0x200) + _int(len(columns)))  # VECSXP: object, has attributes
    for column in columns:
        out.write(_rds_column(column))

    def attribute(name: str, value: bytes, *, last: bool = False) -> None:
        out.write(_int(2 | 0x400) + _rds_symbol(name) + value)
        if last:
            out.write(_int(254))  # NILVALUE_SXP ends the pairlist

    attribute("names", _rds_strsxp(list(table.columns)))
    attribute("class", _rds_strsxp(["data.frame"]))
    attribute("row.names", _int(13) + _int(2) + _int(_NA_INT) + _int(-len(table.rows)), last=True)
    return out.getvalue()


def provenance_table(repo: Repo) -> Table:
    """Every extracted value with its study and source locator, one row each
    (openspec:data-extraction#extraction-records-and-source-locators: the per-value provenance
    table `strata report` will embed). Consensus records only; sorted by study, then item."""
    members = studies_mod.study_map(repo).members
    table = Table(columns=["study_id", "kind", "item", "value", "unit", "source", "recorded_by"])
    consensus = {
        r["study"]: r
        for kind, _h, r, _p in rec_mod.all_records(repo)
        if kind == "consensus" and r.get("study") in members
    }
    for study in sorted(consensus):
        record = consensus[study]
        by = ";".join(
            str(h) for h in record.get("reconciled_by") or record.get("extracted_by") or []
        )
        for name, entry in record.get("fields", {}).items():
            table.rows.append(
                {
                    "study_id": study,
                    "kind": "field",
                    "item": name,
                    "value": "NR" if entry.get("not_reported") else _flat(entry),
                    "unit": entry.get("unit"),
                    "source": entry.get("source"),
                    "recorded_by": by,
                }
            )
        for effect in sorted(record.get("effects", []), key=lambda e: str(e.get("id", ""))):
            table.rows.append(
                {
                    "study_id": study,
                    "kind": "effect",
                    "item": effect.get("id") or rec_mod.effect_key(effect),
                    "value": f"{effect.get('design')} ({effect.get('outcome')})",
                    "unit": None,
                    "source": effect.get("source"),
                    "recorded_by": by,
                }
            )
    return table


def render(table: Table, fmt: str) -> bytes:
    if fmt == "csv":
        return _delimited(table, ",")
    if fmt == "tsv":
        return _delimited(table, "\t")
    if fmt == "json":
        return _json(table)
    if fmt == "xlsx":
        return _xlsx(table)
    if fmt == "rds":
        return _rds(table)
    raise ExportError(f"format must be one of {', '.join(FORMATS)}, got {fmt!r}")
