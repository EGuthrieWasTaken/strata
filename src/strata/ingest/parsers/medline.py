"""PubMed / MEDLINE (`.nbib`) parser.

Implements the PubMed/MEDLINE row of openspec:literature-import:
`PMID- `, `TI  - `-style four-character tags padded to a six-column prefix,
with continuation lines indented six spaces so they line up under the value.
No general-purpose library parses this format, so it is hand-rolled.

Unlike RIS there is no per-record end tag; MEDLINE records are separated by a
blank line, so that is what this module splits on.
"""

from __future__ import annotations

import html
import re
from typing import Any

from strata.core.ids import normalise_year
from strata.ingest.parsers import ParseResult, RejectedRow, has_title

_TAG_LINE_RE = re.compile(r"^([A-Z]{2,4})\s*-\s?(.*)$")
_CONTINUATION_RE = re.compile(r"^\s{4,}(\S.*)$")
_DOI_IN_AID_RE = re.compile(r"^(.*?)\s*\[doi\]\s*$", re.IGNORECASE)


def _split_records(text: str) -> list[tuple[int, list[str]]]:
    """Split on blank lines into (1-based start line, non-empty lines) blocks."""
    blocks: list[tuple[int, list[str]]] = []
    current: list[str] = []
    start = 1
    for i, line in enumerate(text.split("\n"), start=1):
        if line.strip():
            if not current:
                start = i
            current.append(line)
        elif current:
            blocks.append((start, current))
            current = []
    if current:
        blocks.append((start, current))
    return blocks


def _parse_fields(lines: list[str]) -> dict[str, list[str]]:
    """One MEDLINE record's tag lines, folding continuation lines into their tag's value."""
    fields: dict[str, list[str]] = {}
    current_tag: str | None = None
    for line in lines:
        match = _TAG_LINE_RE.match(line)
        if match:
            tag, value = match.group(1), match.group(2)
            fields.setdefault(tag, []).append(value)
            current_tag = tag
            continue
        continuation = _CONTINUATION_RE.match(line)
        text = continuation.group(1) if continuation else line.strip()
        if current_tag is not None and text:
            fields[current_tag][-1] = f"{fields[current_tag][-1].rstrip()} {text}".strip()
    return fields


def _first(fields: dict[str, list[str]], *tags: str) -> str | None:
    for tag in tags:
        values = fields.get(tag)
        if values:
            return values[0]
    return None


def _authors(fields: dict[str, list[str]]) -> list[dict[str, str]]:
    """`FAU` ("Family, Given Middle") is preferred; `AU` ("Family GM") is the fallback.

    `CN` (collective/corporate name) is a distinct MEDLINE tag from either --
    real exports use it for a corporate author rather than folding one into
    FAU/AU -- and is appended as a literal name regardless of which of the two
    personal-author tags was used, since a collaborative work can carry both.
    """
    authors: list[dict[str, str]] = []
    full = fields.get("FAU")
    if full:
        for name in full:
            if "," in name:
                family, given = (part.strip() for part in name.split(",", 1))
                authors.append({"family": family, "given": given} if given else {"family": family})
            elif name.strip():
                authors.append({"literal": name.strip()})
    else:
        for name in fields.get("AU") or []:
            name = name.strip()
            if not name:
                continue
            parts = name.rsplit(" ", 1)
            if len(parts) == 2:
                authors.append({"family": parts[0], "given": parts[1]})
            else:
                authors.append({"literal": name})
    for corporate in fields.get("CN") or []:
        if corporate.strip():
            authors.append({"literal": corporate.strip()})
    return authors


def _doi(fields: dict[str, list[str]]) -> str | None:
    for tag in ("LID", "AID"):
        for value in fields.get(tag, []):
            match = _DOI_IN_AID_RE.match(value.strip())
            if match:
                return match.group(1).strip()
    return None


def _to_csl(fields: dict[str, list[str]]) -> dict[str, Any]:
    csl: dict[str, Any] = {"type": "article-journal"}
    title = _first(fields, "TI")
    if title:
        csl["title"] = html.unescape(title)
    authors = _authors(fields)
    if authors:
        csl["author"] = authors
    date = _first(fields, "DP", "DA", "DEP")
    year = normalise_year(date)
    if year is not None:
        csl["issued"] = {"date-parts": [[year]]}
    journal = _first(fields, "JT", "TA")
    if journal:
        csl["container-title"] = html.unescape(journal)
    volume = _first(fields, "VI")
    if volume:
        csl["volume"] = volume
    issue = _first(fields, "IP")
    if issue:
        csl["issue"] = issue
    pages = _first(fields, "PG")
    if pages:
        csl["page"] = pages
    pmid = _first(fields, "PMID")
    if pmid:
        csl["PMID"] = pmid
    pmc = _first(fields, "PMC")
    if pmc:
        csl["PMCID"] = pmc if pmc.upper().startswith("PMC") else f"PMC{pmc}"
    doi = _doi(fields)
    if doi:
        csl["DOI"] = doi
    abstract = _first(fields, "AB")
    if abstract:
        csl["abstract"] = html.unescape(abstract)
    keywords = fields.get("MH") or []
    if keywords:
        csl["keyword"] = "; ".join(html.unescape(k) for k in keywords)
    language = _first(fields, "LA")
    if language:
        csl["language"] = language
    return csl


def parse(text: str) -> ParseResult:
    """Parse MEDLINE/`.nbib` text into CSL-JSON-shaped records."""
    result = ParseResult()
    for start_line, lines in _split_records(text):
        fields = _parse_fields(lines)
        csl = _to_csl(fields)
        if not has_title(csl):
            result.rejected.append(
                RejectedRow(line=start_line, raw="\n".join(lines), error="missing or empty title")
            )
            continue
        result.records.append(csl)
    return result
