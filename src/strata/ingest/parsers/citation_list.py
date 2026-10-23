"""PRISMA-style plain-text citation list parser.

Implements the citation-list row of openspec:literature-import: a `.txt` file of formatted
references (the reference list of a paper, or a PRISMA flow diagram's "records identified through
other sources"), one per numbered line or one per paragraph. This is best-effort by nature: a
formatted reference carries no field markers, so authors, title and journal are inferred from the
two layouts that cover nearly every list (Vancouver `Authors. Title. Journal. 2019;12(3):45-67.` and
APA `Authors (2019). Title. Journal, 12(3), 45-67.`) and from identifiers (DOI, PMID) wherever they
appear. Anything the layouts do not fit is rejected, with the entry, rather than guessed.

Because the fields are inferred, every record from this parser is flagged
(`ParseResult.best_effort`) and the import pipeline marks it so that deduplication never merges it
without a person looking
(openspec:literature-import#supported-import-formats: "always routed to manual review").
"""

from __future__ import annotations

import re
from typing import Any

from strata.ingest.parsers import ParseResult, RejectedRow, has_title

_ENTRY_START_RE = re.compile(r"^\s*(?:\[\d{1,5}\]|\d{1,5}[.)])\s+")
_DOI_RE = re.compile(
    r"(?:doi:?\s*|https?://(?:dx\.)?doi\.org/)?(10\.\d{4,9}/[^\s<>\"]+)", re.IGNORECASE
)
_PMID_RE = re.compile(r"\bPMID:?\s*(\d{4,9})\b", re.IGNORECASE)
_APA_RE = re.compile(
    r"^(?P<authors>.+?)\s*\((?P<year>(?:19|20)\d{2})[a-z]?\)\.\s*(?P<title>.+?[.?!])\s+(?P<rest>.+)$"
)
_YEAR_RE = re.compile(r"(?:^|[\s.;,(])((?:19|20)\d{2})[a-z]?(?=[;:,.)\s]|$)")
_VANCOUVER_NAME_RE = re.compile(r"^([A-Z][\w'’\-]*(?: [A-Z][\w'’\-]*)*) ([A-Z]{1,3})$")
_APA_NAME_RE = re.compile(r"([A-Z][\w'’\-]+(?: [A-Z][\w'’\-]+)*),\s*((?:[A-Z]\.\s*)+)")
_VOLUME_PAGES_RE = re.compile(
    r"[,;]?\s*(?:(?:19|20)\d{2}[;:]?\s*)?(\d+)(?:\((\d+[A-Za-z\-]*)\))?[:,]\s*([\w\-–]+)\s*\.?$"
)


def _split_entries(text: str) -> list[tuple[int, str]]:
    """`(1-based first line, entry text)`: numbered lines start entries, else blank lines do."""
    lines = text.split("\n")
    numbered = sum(1 for line in lines if _ENTRY_START_RE.match(line)) >= 2
    entries: list[tuple[int, list[str]]] = []
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            if not numbered:
                entries.append((0, []))  # a paragraph break closes the entry
            continue
        starts = bool(_ENTRY_START_RE.match(line))
        if numbered and starts or not entries or (not numbered and not entries[-1][1]):
            entries.append((number, [line]))
        else:
            entries[-1][1].append(line)
    cleaned = []
    for first, parts in entries:
        if parts:
            joined = " ".join(" ".join(parts).split())
            cleaned.append((first, _ENTRY_START_RE.sub("", joined, count=1).strip()))
    return cleaned


def _authors(raw: str) -> list[dict[str, str]]:
    raw = re.sub(r"\bet al\.?", "", raw).strip(" ,;")
    apa = _APA_NAME_RE.findall(raw)
    if apa:
        return [
            {"family": family.strip(), "given": " ".join(given.split())} for family, given in apa
        ]
    names = []
    for part in re.split(r",|;|\s&\s|\sand\s", raw):
        part = part.strip(" .&")
        if not part:
            continue
        match = _VANCOUVER_NAME_RE.match(part)
        names.append(
            {"family": match.group(1), "given": match.group(2)} if match else {"literal": part}
        )
    return names


def _split_journal(rest: str) -> tuple[str, dict[str, str]]:
    """The journal (and volume, issue, pages when they are at the end) of the rest of an entry."""
    rest = rest.strip(" .")
    extra: dict[str, str] = {}
    match = _VOLUME_PAGES_RE.search(rest)
    if match:
        extra["volume"] = match.group(1)
        if match.group(2):
            extra["issue"] = match.group(2)
        extra["page"] = match.group(3)
        rest = rest[: match.start()]
    journal = re.sub(r"[,;]?\s*(?:19|20)\d{2}[a-z]?$", "", rest.strip(" .,;")).strip(" .,;")
    return journal, extra


def _entry_to_csl(entry: str) -> dict[str, Any] | None:
    csl: dict[str, Any] = {"type": "article-journal"}
    doi = _DOI_RE.search(entry)
    if doi:
        csl["DOI"] = doi.group(1).rstrip(".,;)")
    pmid = _PMID_RE.search(entry)
    if pmid:
        csl["PMID"] = pmid.group(1)
    body = _DOI_RE.sub("", _PMID_RE.sub("", entry)).strip(" .,;")
    body = re.sub(r"\s+", " ", body)
    apa = _APA_RE.match(body)
    if apa:
        csl["author"] = _authors(apa.group("authors"))
        csl["issued"] = {"date-parts": [[int(apa.group("year"))]]}
        csl["title"] = apa.group("title").strip().rstrip(".")
        journal, extra = _split_journal(apa.group("rest"))
        if journal:
            csl["container-title"] = journal
        csl.update(extra)
        return csl
    segments = [s.strip() for s in re.split(r"\.\s+", body) if s.strip()]
    if len(segments) < 3:
        return None  # authors + title + source: fewer than that is not a layout this understands
    csl["author"] = _authors(segments[0])
    csl["title"] = segments[1]
    year = _YEAR_RE.search(" ".join(segments[2:]))
    if year:
        csl["issued"] = {"date-parts": [[int(year.group(1))]]}
    journal, extra = _split_journal(" ".join(segments[2:]))
    journal = re.split(r"\s+(?:19|20)\d{2}\b", journal)[0].strip(" .,;")
    if journal:
        csl["container-title"] = journal
    csl.update(extra)
    return csl


def parse(text: str) -> ParseResult:
    """Parse a plain-text citation list into CSL-JSON-shaped records."""
    result = ParseResult(best_effort=True)
    for line, entry in _split_entries(text):
        csl = _entry_to_csl(entry)
        if csl is None or not has_title(csl):
            result.rejected.append(
                RejectedRow(line=line, raw=entry, error="not a recognisable reference layout")
            )
            continue
        result.records.append(csl)
    return result
