"""CSV/TSV parser with explicit column mapping.

Implements openspec:literature-import#csv-column-mapping: CSV exports vary per
platform, so column mapping cannot be hard-coded into the parser itself.
Unlike every other module in this package, `parse` here cannot resolve a
header row into records on its own -- it takes a `mapping` (target field ->
source column name) that the caller (`strata.ingest.pipeline`) resolves from
a detection profile (`strata.ingest.profiles`) or an explicit `--map` before
calling in.
"""

from __future__ import annotations

import csv
import html
import io
from typing import Any

from strata.core.ids import normalise_year
from strata.ingest.parsers import ParseResult, RejectedRow, has_title

# Target keys a `mapping` may use. `page` and `page-start`/`page-end` are
# alternatives (a platform gives one column or two); `page` wins if both are
# supplied.
FIELDS = frozenset(
    {
        "title",
        "author",
        "year",
        "container-title",
        "volume",
        "issue",
        "page",
        "page-start",
        "page-end",
        "DOI",
        "PMID",
        "ISBN",
        "URL",
        "abstract",
        "keyword",
    }
)

_SIMPLE_FIELDS = ("volume", "issue", "DOI", "PMID", "ISBN", "URL")


class ColumnMappingError(ValueError):
    """`mapping` names an unknown target field, or a source column missing from the header."""


def read_header(text: str, *, delimiter: str) -> list[str]:
    """The header row alone, for profile detection and `--map` validation."""
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    return next(reader, [])


def _name_to_csl(raw: str) -> dict[str, str]:
    raw = raw.strip()
    if "," in raw:
        family, given = raw.split(",", 1)
        family, given = family.strip(), given.strip()
        return {"family": family, "given": given} if given else {"family": family}
    return {"literal": raw} if raw else {}


def _split_authors(raw: str) -> list[str]:
    """Platforms separate a multi-author string with `;` or ` and `.

    A semicolon is unambiguous and checked first. A bare comma-separated list
    is genuinely ambiguous with the "Family, Given" form of a single name, so
    -- lacking a semicolon or " and " -- the whole string is treated as one
    name rather than guessed apart.
    """
    if ";" in raw:
        return [p.strip() for p in raw.split(";") if p.strip()]
    if " and " in raw:
        return [p.strip() for p in raw.split(" and ") if p.strip()]
    return [raw.strip()] if raw.strip() else []


def _field(row: dict[str, str | None], mapping: dict[str, str], key: str) -> str:
    if key not in mapping:
        return ""
    return (row.get(mapping[key]) or "").strip()


def parse(text: str, *, delimiter: str, mapping: dict[str, str]) -> ParseResult:
    """Parse CSV/TSV text into CSL-JSON-shaped records using `mapping`.

    Raises `ColumnMappingError` -- not a per-row `RejectedRow` -- for a
    problem with the mapping itself (an unknown target field, a mapped
    column absent from the header, no `title` mapped): these make the whole
    file unparsable rather than one row of it.
    """
    unknown_targets = set(mapping) - FIELDS
    if unknown_targets:
        raise ColumnMappingError(f"unknown mapping target(s): {sorted(unknown_targets)}")
    if "title" not in mapping:
        raise ColumnMappingError("mapping must include a 'title' column")

    result = ParseResult()
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    if reader.fieldnames is None:
        return result

    missing_columns = set(mapping.values()) - set(reader.fieldnames)
    if missing_columns:
        raise ColumnMappingError(f"mapped column(s) not found in header: {sorted(missing_columns)}")

    for row_number, row in enumerate(reader, start=2):  # the header is row 1
        record: dict[str, Any] = {"type": "article-journal"}

        title = _field(row, mapping, "title")
        if title:
            record["title"] = html.unescape(title)

        raw_authors = _field(row, mapping, "author")
        if raw_authors:
            names = [n for n in (_name_to_csl(a) for a in _split_authors(raw_authors)) if n]
            if names:  # pragma: no cover - `raw_authors` non-empty always yields >=1 name
                record["author"] = names

        year = normalise_year(_field(row, mapping, "year") or None)
        if year is not None:
            record["issued"] = {"date-parts": [[year]]}

        container = _field(row, mapping, "container-title")
        if container:
            record["container-title"] = html.unescape(container)

        for target in _SIMPLE_FIELDS:
            value = _field(row, mapping, target)
            if value:
                record[target] = value

        page = _field(row, mapping, "page")
        if page:
            record["page"] = page
        else:
            start, end = _field(row, mapping, "page-start"), _field(row, mapping, "page-end")
            if start and end:
                record["page"] = f"{start}-{end}"
            elif start:
                record["page"] = start

        abstract = _field(row, mapping, "abstract")
        if abstract:
            record["abstract"] = html.unescape(abstract)

        keyword = _field(row, mapping, "keyword")
        if keyword:
            record["keyword"] = html.unescape(keyword)

        if not has_title(record):
            raw_line = delimiter.join(row.get(c) or "" for c in reader.fieldnames)
            result.rejected.append(
                RejectedRow(line=row_number, raw=raw_line, error="missing or empty title")
            )
            continue
        result.records.append(record)
    return result
