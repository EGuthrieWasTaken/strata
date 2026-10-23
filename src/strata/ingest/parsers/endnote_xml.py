"""EndNote XML parser.

Implements the EndNote XML row of openspec:literature-import: `<records><record>` with every text
value nested in `<style>` elements. Each `<record>` is cut out of the file and parsed on its own, so
one malformed record is rejected (with its line number) instead of losing the file, and the
malformations real exports have are repaired first:

- an `&` that starts no valid XML entity (EndNote writes `Smith & Jones` and HTML named entities
  such as `&eacute;` unescaped) is escaped, and HTML entities in the text are unescaped afterwards;
- a DOCTYPE or entity declaration is never honoured: the declarations lie outside the records and a
  record containing one is rejected, so a hostile export cannot define entities of its own.
"""

from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET
from typing import Any

from strata.core.ids import normalise_year
from strata.ingest.parsers import ParseResult, RejectedRow, has_title

_RECORD_START_RE = re.compile(r"<record(?=[\s>])", re.IGNORECASE)
_RECORD_END_RE = re.compile(r"</record\s*>", re.IGNORECASE)
_BARE_AMPERSAND_RE = re.compile(r"&(?!(?:amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);)")
_UNSAFE_RE = re.compile(r"<!(?:DOCTYPE|ENTITY)", re.IGNORECASE)

# EndNote reference type names and numbers -> CSL types (not exhaustive or normative; see ris.py).
_TYPE_BY_NAME = {
    "journal article": "article-journal",
    "magazine article": "article-magazine",
    "newspaper article": "article-newspaper",
    "book": "book",
    "edited book": "book",
    "book section": "chapter",
    "conference proceedings": "paper-conference",
    "conference paper": "paper-conference",
    "thesis": "thesis",
    "report": "report",
    "manuscript": "manuscript",
    "web page": "webpage",
    "electronic article": "article-journal",
    "generic": "article-journal",
}
_TYPE_BY_NUMBER = {
    "17": "article-journal", "19": "article-magazine", "23": "article-newspaper", "6": "book",
    "28": "book", "5": "chapter", "10": "paper-conference", "47": "paper-conference",
    "32": "thesis", "27": "report", "36": "manuscript", "12": "webpage", "43": "article-journal",
    "13": "article-journal",
}  # fmt: skip


def _text(element: ET.Element | None) -> str:
    """All text under `element` (the `<style>` children included), whitespace collapsed."""
    if element is None:
        return ""
    return " ".join("".join(element.itertext()).split())


def _clean(value: str) -> str:
    return html.unescape(value).strip()


def _name_to_csl(raw: str) -> dict[str, str]:
    """`Family, Given` as EndNote stores it; one token or an institution is a literal name."""
    raw = _clean(raw)
    if not raw:
        return {}
    if "," in raw:
        family, given = (part.strip() for part in raw.split(",", 1))
        return {"family": family, "given": given} if given else {"family": family}
    return {"literal": raw}


def _record_to_csl(record: ET.Element) -> dict[str, Any]:
    ref_type = record.find("ref-type")
    type_name = (ref_type.get("name") or "").lower() if ref_type is not None else ""
    type_number = _text(ref_type)
    csl: dict[str, Any] = {
        "type": _TYPE_BY_NAME.get(type_name) or _TYPE_BY_NUMBER.get(type_number, "article-journal")
    }
    title = _clean(_text(record.find("titles/title")))
    if title:
        csl["title"] = title
    authors = [_name_to_csl(_text(a)) for a in record.findall("contributors/authors/author")]
    authors = [a for a in authors if a]
    if authors:
        csl["author"] = authors
    year = normalise_year(_text(record.find("dates/year")) or _text(record.find("dates/pub-dates")))
    if year is not None:
        csl["issued"] = {"date-parts": [[year]]}
    journal = _clean(
        _text(record.find("periodical/full-title")) or _text(record.find("titles/secondary-title"))
    )
    if journal:
        csl["container-title"] = journal
    for tag, field in (("volume", "volume"), ("number", "issue"), ("pages", "page")):
        value = _clean(_text(record.find(tag)))
        if value:
            csl[field] = value
    doi = _text(record.find("electronic-resource-num"))
    if doi:
        csl["DOI"] = doi
    url = _text(record.find("urls/related-urls/url"))
    if url:
        csl["URL"] = url
    abstract = _clean(_text(record.find("abstract")))
    if abstract:
        csl["abstract"] = abstract
    keywords = [_clean(_text(k)) for k in record.findall("keywords/keyword")]
    keywords = [k for k in keywords if k]
    if keywords:
        csl["keyword"] = "; ".join(keywords)
    language = _clean(_text(record.find("language")))
    if language:
        csl["language"] = language
    return csl


def parse(text: str) -> ParseResult:
    """Parse EndNote XML text (decoded, newline-normalised) into CSL-JSON-shaped records."""
    result = ParseResult()
    starts = [m.start() for m in _RECORD_START_RE.finditer(text)]
    if not starts:
        result.rejected.append(
            RejectedRow(line=None, raw=text[:200], error="no <record> elements found")
        )
        return result
    # A record runs from its own `<record>` to the next one, so a record that never closes cannot
    # swallow its neighbours; whatever follows its last `</record>` (the closing tags) is dropped.
    for index, start in enumerate(starts):
        block = text[start : starts[index + 1] if index + 1 < len(starts) else len(text)]
        closes = list(_RECORD_END_RE.finditer(block))
        if closes:
            block = block[: closes[-1].end()]
        line = text.count("\n", 0, start) + 1
        if _UNSAFE_RE.search(block):
            result.rejected.append(
                RejectedRow(
                    line=line, raw=block, error="DOCTYPE and entity declarations are refused"
                )
            )
            continue
        try:
            record = ET.fromstring(_BARE_AMPERSAND_RE.sub("&amp;", block))
        except ET.ParseError as exc:
            result.rejected.append(RejectedRow(line=line, raw=block, error=f"malformed XML: {exc}"))
            continue
        csl = _record_to_csl(record)
        if not has_title(csl):
            result.rejected.append(
                RejectedRow(line=line, raw=block, error="missing or empty title")
            )
            continue
        result.records.append(csl)
    return result
