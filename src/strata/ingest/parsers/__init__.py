"""Bibliographic export parsers.

Implements docs/spec/05-workflow-import.md §2.1. Every format module in this
package exposes a single `parse(text: str) -> ParseResult` function that takes
already-decoded, newline-normalised text (see `decode_bytes`/`normalise_newlines`
below, used by the import pipeline before dispatch) and returns CSL-JSON-shaped
record dicts per docs/spec/03-schemas.md §2, *without* the `strata` extension
object -- the import pipeline attaches that once it has assigned ids.

A row that cannot be parsed MUST NOT abort the rest of the file (§2.1): parsers
collect failures as `RejectedRow` entries alongside successful `records`
instead of raising. A record with a missing or empty title is treated as a
reject for the same reason -- an empty title is a hard requirement violation
per docs/spec/03-schemas.md §2, and "the whole import aborts" is a worse
outcome than "one row didn't make it in", exactly per §2.1's stated rationale.
"""

from __future__ import annotations

import codecs
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class RejectedRow:
    """One record that failed to parse or failed a hard structural requirement.

    `line` is 1-based and format-specific in what it points at (a source line
    for line-oriented formats, an array index for JSON, a row number for
    tabular formats); `None` when the failure is document-wide and no single
    location applies.
    """

    line: int | None
    raw: str
    error: str


@dataclass
class ParseResult:
    records: list[dict[str, Any]] = field(default_factory=list)
    rejected: list[RejectedRow] = field(default_factory=list)


def decode_bytes(raw: bytes) -> tuple[str, str]:
    """docs/spec/05-workflow-import.md §2.1 -- the encoding fallback chain.

    A byte-order mark is detected explicitly (rather than as a decode
    failure) so it is stripped instead of surviving into the text as a
    leading `\\ufeff`. Falls through UTF-8, then CP1252, then Latin-1, which
    accepts any byte sequence and therefore always terminates the chain.
    Returns `(text, encoding_used)`; the caller records `encoding_used` in the
    import manifest.
    """
    if raw.startswith(codecs.BOM_UTF8):
        return raw[len(codecs.BOM_UTF8) :].decode("utf-8"), "utf-8-sig"
    try:
        return raw.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        pass
    try:
        return raw.decode("cp1252"), "cp1252"
    except UnicodeDecodeError:
        pass
    return raw.decode("latin-1"), "latin-1"


def normalise_newlines(text: str) -> str:
    """CRLF and lone CR both become LF (docs/spec/05-workflow-import.md §2.1)."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def has_title(record: dict[str, Any]) -> bool:
    return bool(str(record.get("title") or "").strip())
