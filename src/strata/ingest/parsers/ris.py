"""RIS parser.

Implements the RIS row of openspec:literature-import: tag-per-line,
tolerant of both `TY  - ` and `TY - ` spacing, and of a record missing its
closing `ER  - ` line. `rispy` does the tag-to-field mapping, but it is
strict about the two-space tag form and -- worse -- silently drops a record
with no `ER` tag instead of raising, which would violate the "a row that
cannot be parsed MUST NOT abort the import, and losing records silently is
worse than losing them loudly" rule in openspec:literature-import. This module therefore isolates
each `TY ... ER` block itself, synthesises a missing `ER` line, and hands
`rispy` one block at a time so a single bad record cannot swallow its
neighbours.
"""

from __future__ import annotations

import html
import re
from typing import Any

import rispy

from strata.core.ids import normalise_year
from strata.ingest.parsers import ParseResult, RejectedRow, has_title

_TAG_LINE_RE = re.compile(r"^([A-Za-z][A-Za-z0-9])\s*-\s?(.*)$")
_START_TAG_RE = re.compile(r"^TY\s*-")
_END_TAG_RE = re.compile(r"^ER\s*-")

# Not exhaustive and not normative --
# openspec:data-schemas#record-schema-is-csl-json-plus-a-namespaced-extension only requires
# a CSL `type`, defaulting to `article-journal`; this maps the RIS reference
# types that actually appear in the databases openspec:test-suite#golden-parser-fixtures lists.
_TYPE_MAP = {
    "JOUR": "article-journal",
    "JFULL": "article-journal",
    "MGZN": "article-magazine",
    "NEWS": "article-newspaper",
    "BOOK": "book",
    "CHAP": "chapter",
    "CONF": "paper-conference",
    "THES": "thesis",
    "RPRT": "report",
    "UNPB": "manuscript",
    "ABST": "article-journal",
}


def _canonicalise_tag_lines(text: str) -> list[str]:
    """Rewrite every tag line to the `TG  - value` spacing `rispy` requires."""
    out = []
    for line in text.split("\n"):
        match = _TAG_LINE_RE.match(line)
        out.append(f"{match.group(1).upper()}  - {match.group(2)}" if match else line)
    return out


def _close_block(lines: list[str]) -> str:
    if not any(_END_TAG_RE.match(line) for line in lines):
        lines = [*lines, "ER  - "]
    return "\n".join(lines)


def _split_records(lines: list[str]) -> list[tuple[int, str]]:
    """Isolate each `TY ... ER` block as (1-based start line, block text)."""
    blocks: list[tuple[int, str]] = []
    current: list[str] | None = None
    start = 0
    for i, line in enumerate(lines):
        if _START_TAG_RE.match(line):
            if current is not None:
                blocks.append((start, _close_block(current)))
            current = [line]
            start = i + 1
        elif current is not None:
            current.append(line)
    if current is not None:
        blocks.append((start, _close_block(current)))
    return blocks


def _name_to_csl(raw: str) -> dict[str, str]:
    """RIS authors are `Family, Given`; anything without a comma is a corporate author."""
    raw = raw.strip()
    if "," in raw:
        family, given = raw.split(",", 1)
        family, given = family.strip(), given.strip()
        return {"family": family, "given": given} if given else {"family": family}
    return {"literal": raw} if raw else {}


def _to_csl(rec: dict[str, Any]) -> dict[str, Any]:
    csl: dict[str, Any] = {
        "type": _TYPE_MAP.get(str(rec.get("type_of_reference", "")).upper(), "article-journal"),
    }
    title = rec.get("title") or rec.get("primary_title") or rec.get("short_title")
    if title:
        csl["title"] = html.unescape(str(title))
    authors = [a for a in (rec.get("authors") or []) if str(a).strip()]
    if authors:
        names = [_name_to_csl(str(a)) for a in authors]
        csl["author"] = [n for n in names if n]
    year_source = rec.get("year") or rec.get("publication_year") or rec.get("date")
    year = normalise_year(year_source)
    if year is not None:
        csl["issued"] = {"date-parts": [[year]]}
    journal = rec.get("journal_name") or rec.get("alternate_title3") or rec.get("secondary_title")
    if journal:
        csl["container-title"] = html.unescape(str(journal))
    if rec.get("volume"):
        csl["volume"] = str(rec["volume"])
    if rec.get("number"):
        csl["issue"] = str(rec["number"])
    start_page, end_page = rec.get("start_page"), rec.get("end_page")
    if start_page and end_page:
        csl["page"] = f"{start_page}-{end_page}"
    elif start_page:
        csl["page"] = str(start_page)
    if rec.get("doi"):
        csl["DOI"] = str(rec["doi"])
    urls = rec.get("urls") or []
    if urls:
        csl["URL"] = str(urls[0])
    abstract = rec.get("abstract") or rec.get("notes_abstract")
    if abstract:
        csl["abstract"] = html.unescape(str(abstract))
    keywords = rec.get("keywords") or []
    if keywords:
        csl["keyword"] = "; ".join(str(k) for k in keywords)
    if rec.get("language"):
        csl["language"] = str(rec["language"])
    return csl


def parse(text: str) -> ParseResult:
    """Parse RIS text (already decoded and newline-normalised) into CSL-JSON-shaped records."""
    result = ParseResult()
    lines = _canonicalise_tag_lines(text)
    for start_line, block in _split_records(lines):
        try:
            parsed = rispy.loads(block)
        except Exception as exc:  # noqa: BLE001  # pragma: no cover - parser boundary, see below
            # `_split_records` never hands `rispy` anything we've observed it
            # raise on; this is a defensive last resort against a `rispy`
            # internal bug on input this module hasn't been fuzzed against
            # yet (openspec:test-suite#fuzzing, tracked in docs/m1-plan.md
            # sub-objective 8), not a path exercised in the unit/golden suite.
            result.rejected.append(  # pragma: no cover
                RejectedRow(line=start_line, raw=block, error=str(exc))
            )
            continue  # pragma: no cover
        if len(parsed) != 1:
            # Every block starts with a `TY` line and ends with an `ER` line
            # by construction, which `rispy` has always turned into exactly
            # one record in observed testing; kept as a defensive guard
            # against a `rispy` edge case rather than exercised deliberately.
            result.rejected.append(  # pragma: no cover
                RejectedRow(line=start_line, raw=block, error="RIS record did not parse")
            )
            continue  # pragma: no cover
        csl = _to_csl(parsed[0])
        if not has_title(csl):
            result.rejected.append(
                RejectedRow(line=start_line, raw=block, error="missing or empty title")
            )
            continue
        result.records.append(csl)
    return result
