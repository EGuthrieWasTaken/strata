"""BibTeX parser.

Implements the BibTeX row of openspec:literature-import:
brace-balanced parsing -- handled by `bibtexparser`'s own tokeniser, which
isolates a malformed entry (e.g. an unbalanced brace) into `failed_blocks`
without losing the rest of the file -- and preservation of `@misc` and
unknown fields, folded into a CSL `note` since CSL-JSON has no general
extension slot for arbitrary BibTeX fields.
"""

from __future__ import annotations

import html
import re
from typing import Any

from bibtexparser.entrypoint import parse_string
from bibtexparser.middlewares import SeparateCoAuthors, SplitNameParts
from bibtexparser.middlewares.names import NameParts
from bibtexparser.model import Entry

from strata.core.ids import normalise_year
from strata.ingest.parsers import ParseResult, RejectedRow, has_title

# Not exhaustive and not normative -- see the equivalent note in ris.py.
_TYPE_MAP = {
    "article": "article-journal",
    "inproceedings": "paper-conference",
    "conference": "paper-conference",
    "incollection": "chapter",
    "inbook": "chapter",
    "book": "book",
    "phdthesis": "thesis",
    "mastersthesis": "thesis",
    "techreport": "report",
    "unpublished": "manuscript",
}

_KNOWN_FIELDS = frozenset(
    {
        "author",
        "title",
        "year",
        "journal",
        "journaltitle",
        "volume",
        "number",
        "pages",
        "doi",
        "url",
        "abstract",
        "keywords",
        "keyword",
        "language",
    }
)

_BRACE_RE = re.compile(r"[{}]")


def _clean(value: str) -> str:
    """Strip BibTeX's protective braces (e.g. `{DNA}` mid-title) and decode HTML entities.

    Neither is standard BibTeX, but both occur in real exports (a title
    round-tripped through a web export pipeline), and
    openspec:literature-import requires tolerating HTML entities wherever they appear.
    """
    return html.unescape(_BRACE_RE.sub("", value)).strip()


def _name_to_csl(parts: NameParts) -> dict[str, str]:
    """A bare `{Corporate Name}` last-part with no first/von/jr is a corporate author."""
    last_tokens = [t for t in (*parts.von, *parts.last) if t]
    if not parts.first and not parts.jr and len(last_tokens) == 1:
        literal = _clean(last_tokens[0])
        if literal:
            return {"literal": literal}
    given = " ".join(_clean(t) for t in (*parts.first, *parts.jr) if t)
    family = " ".join(_clean(t) for t in last_tokens if t)
    csl: dict[str, str] = {}
    if family:
        csl["family"] = family
    if given:
        csl["given"] = given
    return csl


def _to_csl(entry: Entry) -> dict[str, Any]:
    fields = entry.fields_dict
    csl: dict[str, Any] = {"type": _TYPE_MAP.get(entry.entry_type.lower(), "document")}
    if "title" in fields:
        csl["title"] = _clean(str(fields["title"].value))

    author_field = fields.get("author")
    if author_field is not None:
        raw_authors = author_field.value
        if isinstance(raw_authors, list):
            names = [
                _name_to_csl(a) if isinstance(a, NameParts) else {"literal": _clean(str(a))}
                for a in raw_authors
            ]
        else:  # pragma: no cover - SeparateCoAuthors always yields a list; defensive only
            names = [{"literal": _clean(str(raw_authors))}]
        authors = [n for n in names if n]
        if authors:
            csl["author"] = authors

    if "year" in fields:
        year = normalise_year(fields["year"].value)
        if year is not None:
            csl["issued"] = {"date-parts": [[year]]}

    journal = fields.get("journal") or fields.get("journaltitle")
    if journal is not None:
        csl["container-title"] = _clean(str(journal.value))
    if "volume" in fields:
        csl["volume"] = _clean(str(fields["volume"].value))
    if "number" in fields:
        csl["issue"] = _clean(str(fields["number"].value))
    if "pages" in fields:
        csl["page"] = _clean(str(fields["pages"].value)).replace("--", "-")
    if "doi" in fields:
        csl["DOI"] = _clean(str(fields["doi"].value))
    if "url" in fields:
        csl["URL"] = _clean(str(fields["url"].value))
    if "abstract" in fields:
        csl["abstract"] = _clean(str(fields["abstract"].value))

    keyword_field = fields.get("keywords") or fields.get("keyword")
    if keyword_field is not None:
        csl["keyword"] = _clean(str(keyword_field.value))
    if "language" in fields:
        csl["language"] = _clean(str(fields["language"].value))

    unknown = {key: _clean(str(f.value)) for key, f in fields.items() if key not in _KNOWN_FIELDS}
    unknown = {k: v for k, v in unknown.items() if v}
    if unknown:
        csl["note"] = "; ".join(f"{k}: {v}" for k, v in sorted(unknown.items()))
    return csl


def parse(text: str) -> ParseResult:
    """Parse BibTeX text into CSL-JSON-shaped records."""
    result = ParseResult()
    library = parse_string(text)
    library = SeparateCoAuthors().transform(library)
    library = SplitNameParts().transform(library)

    for block in library.failed_blocks:
        line = block.start_line + 1 if block.start_line is not None else None
        # BlockAbortedException carries its message in `abort_reason`, not `str()`.
        error = getattr(block.error, "abort_reason", None) or str(block.error) or repr(block.error)
        result.rejected.append(RejectedRow(line=line, raw=block.raw or "", error=error))

    for entry in library.entries:
        csl = _to_csl(entry)
        line = entry.start_line + 1 if entry.start_line is not None else None
        if not has_title(csl):
            raw = f"@{entry.entry_type}{{{entry.key}, ...}}"
            result.rejected.append(RejectedRow(line=line, raw=raw, error="missing or empty title"))
            continue
        result.records.append(csl)
    return result
