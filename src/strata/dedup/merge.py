"""Merge semantics for deduplication.

Implements docs/spec/05-workflow-import.md §3.5. Pure functions: no I/O, no
knowledge of `records.ndjson`/`aliases.ndjson` file layout -- callers in
`strata.dedup.engine` are responsible for persisting the result.
"""

from __future__ import annotations

from typing import Any

# docs/spec/05-workflow-import.md §3.5: "most complete record (count of
# populated high-value fields: DOI, abstract, authors, pages)".
_HIGH_VALUE_FIELDS = ("DOI", "abstract", "author", "page")

_RESERVED_KEYS = frozenset({"id", "strata"})


def _completeness(record: dict[str, Any]) -> int:
    return sum(1 for field in _HIGH_VALUE_FIELDS if record.get(field))


def _best_trust(record: dict[str, Any], source_trust: list[str]) -> tuple[int, str]:
    """The record's most-trusted cited source: `(rank, label)`.

    Lower rank is more trusted. A source's `database` and `platform` are both
    checked against the configured list (docs/spec/03-schemas.md §1's
    `source_trust` example mixes database-like and platform-like names, so a
    record's trust is the best match across either field on any of its
    sources). A record with no source matching the list ranks last, labelled
    from its first source if it has one, or `"manual"` if it has none at all.
    """
    sources = record.get("strata", {}).get("sources", [])
    fallback_label = "manual"
    if sources:
        fallback_label = sources[0].get("database") or sources[0].get("platform") or "manual"

    best_rank, best_label = len(source_trust), fallback_label
    for source in sources:
        for field_name in ("database", "platform"):
            value = source.get(field_name)
            if value and value in source_trust and source_trust.index(value) < best_rank:
                best_rank, best_label = source_trust.index(value), value
    return best_rank, best_label


def choose_canonical(
    record_a: dict[str, Any], record_b: dict[str, Any], source_trust: list[str]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """`(canonical, absorbed)` per §3.5: most complete, then most trusted, then lowest id."""
    rank_a, _label_a = _best_trust(record_a, source_trust)
    rank_b, _label_b = _best_trust(record_b, source_trust)
    key_a = (-_completeness(record_a), rank_a, record_a["id"])
    key_b = (-_completeness(record_b), rank_b, record_b["id"])
    return (record_a, record_b) if key_a <= key_b else (record_b, record_a)


def _split_keywords(value: str) -> list[str]:
    return [k.strip() for k in value.split(";") if k.strip()]


def _merge_keywords(a: str, b: str) -> str:
    """Set union, order-preserving (§3.5: `keyword`: set union)."""
    seen: list[str] = []
    for value in (*_split_keywords(a), *_split_keywords(b)):
        if value not in seen:
            seen.append(value)
    return "; ".join(seen)


def merge_fields(
    canonical: dict[str, Any], absorbed: dict[str, Any], source_trust: list[str]
) -> tuple[dict[str, Any], dict[str, str]]:
    """Field-wise merge of `absorbed` into `canonical`, per §3.5.

    Returns `(fields, field_provenance)` -- CSL fields only (`id` and
    `strata` excluded; the caller assembles those). `field_provenance` maps
    each field to the source label (a `source_trust` entry, or "manual") its
    final value came from; `"merged"` for `abstract`/`keyword`, whose value
    is a genuine combination rather than one side's value picked outright.
    """
    canonical_rank, canonical_label = _best_trust(canonical, source_trust)
    absorbed_rank, absorbed_label = _best_trust(absorbed, source_trust)
    canonical_wins_conflicts = canonical_rank <= absorbed_rank

    fields: dict[str, Any] = {}
    provenance: dict[str, str] = dict(canonical.get("strata", {}).get("field_provenance", {}))

    for key in (set(canonical) | set(absorbed)) - _RESERVED_KEYS:
        canonical_value, absorbed_value = canonical.get(key), absorbed.get(key)
        has_canonical, has_absorbed = bool(canonical_value), bool(absorbed_value)

        if key == "keyword" and has_canonical and has_absorbed:
            fields[key] = _merge_keywords(str(canonical_value), str(absorbed_value))
            provenance[key] = "merged"
        elif key == "abstract" and has_canonical and has_absorbed:
            longer_is_absorbed = len(str(absorbed_value)) > len(str(canonical_value))
            fields[key] = absorbed_value if longer_is_absorbed else canonical_value
            provenance[key] = "merged"
        elif has_canonical and (not has_absorbed or canonical_wins_conflicts):
            fields[key] = canonical_value
            provenance[key] = canonical_label
        elif has_absorbed:
            fields[key] = absorbed_value
            provenance[key] = absorbed_label

    return fields, provenance
