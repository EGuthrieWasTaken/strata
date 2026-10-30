"""Correcting one field of a record by hand: what a person may type, and what is stored.

Implements openspec:cli#correcting-a-record (`strata fix`). A value arrives as the text a person
typed in a terminal or a form. This module turns it into the value the record stores (a string, a
list of authors, a date), tidied the way an import would have tidied it, and turns a stored value
back into text a person can read and edit. It reads and writes no files.

Fields fall in two groups. The *string* fields are stored as typed, with surrounding space removed;
the identifiers among them (DOI, PMID, PMCID, ISBN) are normalised as an import normalises them,
so a corrected DOI is stored the way the same DOI arriving in an export would be. The *structured*
fields are `author`, and the date of publication, which is named `issued` and may also be given
as `year`. An empty value removes the field, except for the title, which a record cannot lack.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime
from typing import Any

from strata.core.ids import IDENTIFIER_NORMALISERS

# The record schema's plain string fields a human can safely correct (openspec:cli). `id`, `type`
# and `strata` are identity and bookkeeping, not metadata.
EDITABLE_STRING_FIELDS = frozenset(
    {
        "title",
        "container-title",
        "volume",
        "issue",
        "page",
        "DOI",
        "PMID",
        "PMCID",
        "URL",
        "ISBN",
        "abstract",
        "keyword",
        "language",
    }
)

#: Fields stored as structure rather than text. `year` is a way of writing `issued`.
STRUCTURED_FIELDS = frozenset({"author", "issued", "year"})

EDITABLE_FIELDS = EDITABLE_STRING_FIELDS | STRUCTURED_FIELDS

_DATE_RE = re.compile(r"^(\d{4})(?:-(\d{1,2})(?:-(\d{1,2}))?)?$")
_FIRST_YEAR = 1400


class FixFieldError(ValueError):
    """A correction that cannot be made: a field that is not editable, or a bad value."""


def _unknown_field(field: str) -> FixFieldError:
    return FixFieldError(
        f"field {field!r} cannot be corrected with `strata fix`; it can correct: "
        f"{', '.join(sorted(EDITABLE_FIELDS))}"
    )


def parse_authors(text: str) -> list[dict[str, str]]:
    """Authors from `Family, Given; Family, Given`, or from a JSON list of author objects.

    A name with no comma (an organisation, say) is kept whole as a `literal`. An empty text gives
    no authors.
    """
    text = text.strip()
    if not text:
        return []
    if text.startswith("["):
        try:
            loaded = json.loads(text)
        except json.JSONDecodeError as exc:
            raise FixFieldError(f"authors given as JSON are not valid JSON ({exc.msg})") from None
        if not isinstance(loaded, list) or not all(
            isinstance(a, dict)
            and a
            and all(
                k in ("family", "given", "literal") and isinstance(v, str) for k, v in a.items()
            )
            for a in loaded
        ):
            raise FixFieldError(
                "authors given as JSON must be a list of objects with `family`, `given` or "
                "`literal` text"
            )
        return [{k: v.strip() for k, v in a.items() if v.strip()} for a in loaded]
    authors: list[dict[str, str]] = []
    for part in re.split(r"[;\n]", text):
        name = part.strip()
        if not name:
            continue
        if "," in name:
            family, _, given = name.partition(",")
            family, given = family.strip(), given.strip()
            if not family:
                raise FixFieldError(f"an author needs a family name before the comma: {name!r}")
            authors.append({"family": family, "given": given} if given else {"family": family})
        else:
            authors.append({"literal": name})
    return authors


def format_authors(authors: Any) -> str:
    """Authors as `Family, Given; Family, Given`: the form `parse_authors` reads back."""
    names = []
    for author in authors or []:
        if not isinstance(author, dict):
            names.append(str(author))
        elif author.get("family"):
            given = author.get("given")
            # A family name alone keeps its comma, or it would read back as a whole-name `literal`.
            names.append(f"{author['family']}, {given}" if given else f"{author['family']},")
        else:
            names.append(str(author.get("literal") or ""))
    return "; ".join(n for n in names if n)


def _date_parts(issued: Any) -> list[int]:
    parts = ((issued or {}).get("date-parts") or [[]]) if isinstance(issued, dict) else [[]]
    first = parts[0] if parts and isinstance(parts[0], list) else []
    return [int(p) for p in first]


def format_issued(issued: Any) -> str:
    """A date as `2008`, `2008-03` or `2008-03-01`: the form `parse_issued` reads back."""
    parts = _date_parts(issued)
    return "-".join(f"{p:04d}" if i == 0 else f"{p:02d}" for i, p in enumerate(parts))


def _check_year(year: int) -> int:
    latest = datetime.now(UTC).year + 2
    if not _FIRST_YEAR <= year <= latest:
        raise FixFieldError(f"a year must be between {_FIRST_YEAR} and {latest}, got {year}")
    return year


def parse_issued(text: str) -> dict[str, Any]:
    """A date from `YYYY`, `YYYY-MM` or `YYYY-MM-DD`."""
    match = _DATE_RE.match(text.strip())
    if match is None:
        raise FixFieldError(f"a date is written YYYY, YYYY-MM or YYYY-MM-DD, got {text.strip()!r}")
    parts = [int(g) for g in match.groups() if g is not None]
    _check_year(parts[0])
    month = parts[1] if len(parts) > 1 else 1
    day = parts[2] if len(parts) > 2 else 1
    try:
        date(parts[0], month, day)
    except ValueError:
        raise FixFieldError(f"{text.strip()!r} is not a real date") from None
    return {"date-parts": [parts]}


def parse_year(text: str, current: Any) -> dict[str, Any]:
    """A year, keeping the month and day the record already has (`issued` replaces them all)."""
    stripped = text.strip()
    if not re.fullmatch(r"\d{4}", stripped):
        raise FixFieldError(f"a year is four digits, got {stripped!r}")
    rest = _date_parts(current)[1:]
    return {"date-parts": [[_check_year(int(stripped)), *rest]]}


def parse_value(record: dict[str, Any], field: str, text: str) -> tuple[str, Any]:
    """What to store when `field` is corrected to `text`: `(stored field, value)`.

    A value of `None` removes the field. Raises `FixFieldError` for a field that cannot be
    corrected and for a value that does not fit it.
    """
    if field not in EDITABLE_FIELDS:
        raise _unknown_field(field)
    if field == "author":
        return "author", parse_authors(text) or None
    if field == "issued":
        return "issued", parse_issued(text) if text.strip() else None
    if field == "year":
        if not text.strip():
            return "issued", None
        return "issued", parse_year(text, record.get("issued"))
    value = text.strip()
    normaliser = IDENTIFIER_NORMALISERS.get(field)
    if normaliser is not None and value:
        value = normaliser(value) or value  # an identifier that will not normalise is kept as typed
    if not value:
        if field == "title":
            raise FixFieldError("a title cannot be empty")
        return field, None
    return field, value


def format_field_value(field: str, value: Any) -> str | None:
    """A stored value as text for a person to read, or `None` for a field the record lacks."""
    if value is None:
        return None
    if field == "author":
        return format_authors(value) or None
    if field in ("issued", "year"):
        return format_issued(value) or None
    return str(value)
