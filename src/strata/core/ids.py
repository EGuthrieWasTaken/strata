"""Identity and normalisation.

Implements docs/spec/01-domain-model.md §3. These rules are normative: a
change to them is a breaking format change (docs/spec/02-repository-format.md
§7) because it can change every id in an existing repository.
"""

from __future__ import annotations

import hashlib
import html
import re
import unicodedata
from datetime import UTC, datetime
from typing import Any

from ulid import ULID

_CROCKFORD_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"

_PARTICLES = frozenset(
    {
        "van",
        "von",
        "de",
        "del",
        "della",
        "da",
        "di",
        "du",
        "la",
        "le",
        "ter",
        "ten",
        "al",
        "bin",
        "ibn",
    }
)

_JOURNAL_ABBREVIATIONS = {
    "j": "journal",
    "psychol": "psychology",
    "med": "medicine",
    "sci": "science",
    "res": "research",
    "rev": "review",
    "int": "international",
    "am": "american",
    "clin": "clinical",
    "acad": "academy",
    "proc": "proceedings",
    "assoc": "association",
    "soc": "society",
}

_DOI_PREFIX_RE = re.compile(r"^(https?://dx\.doi\.org/|https?://doi\.org/|doi:)", re.IGNORECASE)
_DOI_SHAPE_RE = re.compile(r"^10\.\d{4,9}/\S+$")
_TAG_RE = re.compile(r"<[^>]+>")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
_DIGIT_RUN_RE = re.compile(r"\d+")
_FOUR_DIGIT_RE = re.compile(r"\d{4}")


def base32_crockford(data: bytes) -> str:
    """Encode bytes as Crockford base32 (uppercase), no padding."""
    bits = int.from_bytes(data, "big")
    total_bits = len(data) * 8
    num_chars = -(-total_bits // 5)
    chars = []
    for i in range(num_chars):
        shift = total_bits - 5 * (i + 1)
        chunk = (bits >> shift) & 0b11111 if shift >= 0 else (bits << -shift) & 0b11111
        chars.append(_CROCKFORD_ALPHABET[chunk])
    return "".join(chars)


def normalise_doi(raw: str | None) -> str | None:
    """docs/spec/01-domain-model.md §3.2 — DOI."""
    if not raw:
        return None
    s = raw.strip()
    s = _DOI_PREFIX_RE.sub("", s).strip()
    s = re.sub(r"[.,;)]$", "", s)
    s = s.lower()
    if not _DOI_SHAPE_RE.match(s):
        return None
    return s


def normalise_title(raw: str | None) -> str:
    """docs/spec/01-domain-model.md §3.2 — Title.

    Also used, unmodified, for author family names and journal titles before
    their own extra rules are layered on.
    """
    if not raw:
        return ""
    s = html.unescape(raw)
    s = _TAG_RE.sub("", s)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower()
    s = _NON_ALNUM_RE.sub(" ", s)
    return s.strip()


def normalise_author_family(raw: str | None) -> tuple[str, str]:
    """docs/spec/01-domain-model.md §3.2 — Author family name.

    Returns (stripped, unstripped): the particle-stripped form (for identity
    and blocking) and the unstripped form (retained as a blocking alternate).
    """
    unstripped = normalise_title(raw)
    if not unstripped:
        return ("", "")
    tokens = unstripped.split(" ")
    is_leading_particle = tokens[0] in _PARTICLES and len(tokens) > 1
    stripped = " ".join(tokens[1:]) if is_leading_particle else unstripped
    return (stripped, unstripped)


def normalise_year(raw: Any) -> int | None:
    """docs/spec/01-domain-model.md §3.2 — Year.

    Takes the first 4-digit number in [1400, current_year + 2].
    """
    if raw is None:
        return None
    text = str(raw)
    current_year = datetime.now(UTC).year
    for match in _FOUR_DIGIT_RE.finditer(text):
        year = int(match.group())
        if 1400 <= year <= current_year + 2:
            return year
    return None


def normalise_pages(raw: Any) -> str | None:
    """docs/spec/01-domain-model.md §3.2 — Pages: the first integer run."""
    if raw is None:
        return None
    match = _DIGIT_RUN_RE.search(str(raw))
    return match.group() if match else None


def normalise_journal(raw: str | None) -> str:
    """docs/spec/01-domain-model.md §3.2 — Journal / container title."""
    base = normalise_title(raw)
    if not base:
        return base
    tokens = [_JOURNAL_ABBREVIATIONS.get(tok, tok) for tok in base.split(" ")]
    return " ".join(tokens)


def _first_author_family(record: dict[str, Any]) -> str:
    authors = record.get("author") or []
    if not authors:
        return ""
    first = authors[0]
    family = first.get("family") if isinstance(first, dict) else first
    stripped, _unstripped = normalise_author_family(family)
    return stripped


def canonical_key(record: dict[str, Any]) -> tuple[str, bool]:
    """docs/spec/01-domain-model.md §3.1 — the canonical key priority ladder.

    Returns (key, is_deterministic). `is_deterministic` is False only for the
    priority-7 fallback (a fresh ULID), which callers MUST warn about.
    """
    doi = normalise_doi(record.get("DOI"))
    if doi:
        return f"doi:{doi}", True

    pmid = record.get("PMID")
    if pmid is not None:
        digits = re.sub(r"\D", "", str(pmid))
        if digits:
            return f"pmid:{digits}", True

    pmcid = record.get("PMCID")
    if pmcid:
        digits = re.sub(r"\D", "", str(pmcid))
        if digits:
            return f"pmcid:PMC{digits}", True

    arxiv = record.get("arXiv") or record.get("arxiv")
    if arxiv:
        norm = str(arxiv).strip().lower()
        norm = re.sub(r"^arxiv:", "", norm)
        if norm:
            return f"arxiv:{norm}", True

    isbn = record.get("ISBN")
    if isbn:
        digits = re.sub(r"\D", "", str(isbn))
        if digits:
            return f"isbn:{digits}", True

    title = normalise_title(record.get("title"))
    if title:
        year = normalise_year(record.get("issued"))
        first_author = _first_author_family(record)
        return f"sig:{title}|{year if year is not None else ''}|{first_author}", True

    return f"ulid:{ULID()!s}".lower(), False


def record_id(canonical_key_value: str) -> str:
    """docs/spec/01-domain-model.md §3.1 — `rec_` + 16 lowercase base32 chars."""
    digest = hashlib.sha256(canonical_key_value.encode("utf-8")).digest()[:10]
    return "rec_" + base32_crockford(digest).lower()


def assign_record_id(record: dict[str, Any]) -> tuple[str, str, bool]:
    """Compute (record_id, canonical_key, is_deterministic) for an imported record."""
    key, deterministic = canonical_key(record)
    return record_id(key), key, deterministic


def new_event_id() -> str:
    """`ev_` + lowercase ULID, per docs/spec/01-domain-model.md §3.4."""
    return f"ev_{ULID()!s}".lower()


def new_import_id() -> str:
    """`imp_` + ULID, per docs/spec/01-domain-model.md §3.4."""
    return f"imp_{ULID()!s}".lower()
