"""`records/records.ndjson`: canonical bibliographic records.

Implements openspec:data-schemas#record-schema-is-csl-json-plus-a-namespaced-extension (the record
shape) and
openspec:canonical-serialisation#records-ndjson-ordering (ordering: sorted by `id`, ascending,
byte-wise; new records land in hash order rather than at the end).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from strata.core import aliases as aliases_mod
from strata.core.canon import canonical_json
from strata.core.events import append_new_event
from strata.core.fieldedit import parse_value
from strata.core.filters import FieldResolver, FilterEvaluationError
from strata.core.ids import canonical_key, normalise_year
from strata.core.ids import record_id as record_id_for_key
from strata.core.repo import Repo
from strata.core.validate import validate

RECORDS_PATH = ("records", "records.ndjson")

# openspec:filter-language's "Available fields" table lists many fields that
# belong to screening (M2), extraction (M3), risk-of-bias and analysis (M4)
# data this milestone has no way to produce yet. Named here, rather than
# silently treated as unknown, so `record_field_resolver`'s error message can
# tell a user *why* a field they copied from the spec doesn't work yet
# instead of implying they mistyped it.
_NOT_YET_AVAILABLE_FIELDS = frozenset(
    {
        "tiab",
        "fulltext",
        "stale",
        "criteria",
        "rob_overall",
        "derived_from_pvalue",
        "assumed_correlation",
    }
)
_NOT_YET_AVAILABLE_PREFIXES = ("actor_decision.", "rob.")


class RecordNotFoundError(LookupError):
    """No record's id starts with the given prefix (openspec:cli:
    "Record ids may be abbreviated to any unambiguous prefix, as in git")."""


class AmbiguousRecordIdError(LookupError):
    """More than one record's id starts with the given prefix."""

    def __init__(self, prefix: str, matches: list[str]) -> None:
        self.prefix = prefix
        self.matches = matches
        super().__init__(f"{prefix!r} matches {len(matches)} records: {', '.join(matches)}")


def records_path(repo: Repo) -> Path:
    return repo.path(*RECORDS_PATH)


def read_records(repo: Repo) -> list[dict[str, Any]]:
    """All records, in file order (already sorted by id on disk)."""
    path = records_path(repo)
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(json.loads(line))
    return records


def index_by_id(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {r["id"]: r for r in records}


def write_records(repo: Repo, records: list[dict[str, Any]]) -> None:
    """Validate and write the full record set, sorted by id
    (openspec:canonical-serialisation#records-ndjson-ordering).

    Callers pass the *complete* record set on every write -- this module has
    no partial-update API, matching the way `write_records` is actually used
    (the import pipeline reads the whole file, updates its in-memory copy,
    and writes it all back).
    """
    for record in records:
        validate("record", record)
    ordered = sorted(records, key=lambda r: str(r["id"]))
    path = records_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [canonical_json(record) for record in ordered]
    text = "".join(line + "\n" for line in lines)
    path.write_text(text, encoding="utf-8")


def get_record(repo: Repo, record_id: str) -> dict[str, Any] | None:
    """One record by id, without paying `read_records`'s full-file
    JSON-parse cost for every other record in a large repository.

    openspec:performance#scale-targets's "screening decision round trip
    < 100 ms p95" target is unreachable if every `strata screen` decision
    re-parses all 50,000 records just to confirm the one being decided
    exists. A plain substring check per line for the id itself is ~free
    next to `json.loads`; only the line(s) that might match ever get
    parsed. Deliberately *not* anchored to canonical JSON's exact
    `"id":"<value>"` spacing (no space after the colon) -- `records.ndjson`
    is always written that way, but this function has no business assuming
    a caller's fixture, a hand-edited file, or a future non-canonical
    writer matches that exactly, and the id string alone is a strictly
    weaker (so strictly safer) pre-filter. The exact `record["id"] ==
    record_id` check still guards against any false-positive substring
    match (e.g. one id being a prefix of another, or the literal appearing
    in an unrelated field) -- a false positive there just costs one wasted
    parse, never a wrong answer.
    """
    path = records_path(repo)
    if not path.exists():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        if record_id in line:
            record: dict[str, Any] = json.loads(line)
            if record["id"] == record_id:
                return record
    return None


def resolve_id_prefix(repo: Repo, prefix: str) -> str:
    """The one record id starting with `prefix`, per openspec:cli:
    "Record ids may be abbreviated to any unambiguous prefix, as in git."

    An exact full id is also accepted (and returned as-is if it matches no
    *other* id as a prefix too) since it is trivially its own unambiguous
    prefix. Raises `RecordNotFoundError` for zero matches,
    `AmbiguousRecordIdError` for more than one.
    """
    matches: list[str] = sorted(
        str(r["id"]) for r in read_records(repo) if str(r["id"]).startswith(prefix)
    )
    if not matches:
        raise RecordNotFoundError(f"no record id starts with {prefix!r}")
    if len(matches) > 1:
        raise AmbiguousRecordIdError(prefix, matches)
    return matches[0]


def record_field_resolver(
    record: dict[str, Any], *, study_fields: Mapping[str, Any] | None = None
) -> FieldResolver:
    """A `strata.core.filters.FieldResolver` over the M1 subset of
    openspec:filter-language's "Available fields" table -- the fields a bare
    bibliographic record actually has data for at this milestone.

    `via`/`search` resolve to the record's *first* source's value: the
    spec's table types both as scalar `string`, but a merged record's
    `strata.sources` can hold several entries (one per absorbed duplicate).
    The first source is the one that originally established the record,
    which is what "how was this record found" most naturally means; a
    query that needs *any* source's via/search isn't expressible with this
    resolver, a known limitation of treating a spec-scalar field this way.

    `study_fields` carries the record's study-level risk-of-bias moderators (`rob_overall`,
    `rob.<domain>`); a study without that judgement resolves to `None`. Without it those fields
    stay "not available yet".
    """

    def resolve(field: str) -> Any:
        if study_fields is not None and (field == "rob_overall" or field.startswith("rob.")):
            return study_fields.get(field)
        if field == "id":
            return record.get("id")
        if field == "doi":
            return record.get("DOI")
        if field == "pmid":
            return record.get("PMID")
        if field == "title":
            return record.get("title") or ""
        if field == "abstract":
            return record.get("abstract") or ""
        if field == "journal":
            return record.get("container-title") or ""
        if field == "year":
            return normalise_year(record.get("issued"))
        if field == "authors":
            return [
                author.get("family")
                for author in record.get("author") or []
                if isinstance(author, dict) and author.get("family")
            ]
        if field in ("via", "search"):
            sources = record.get("strata", {}).get("sources", [])
            return sources[0].get(field) if sources else None
        if field in _NOT_YET_AVAILABLE_FIELDS or field.startswith(_NOT_YET_AVAILABLE_PREFIXES):
            raise FilterEvaluationError(
                f"field {field!r} is not available yet: it requires screening, extraction, "
                "risk-of-bias, or analysis data that doesn't exist until a later milestone"
            )
        raise FilterEvaluationError(f"unknown filter field {field!r}")

    return resolve


@dataclass(frozen=True)
class Amendment:
    """What correcting a field did (or, with `changed` false, found nothing to do)."""

    #: The field as the record stores it (`issued` when the correction was given as `year`).
    field: str
    old: Any
    new: Any
    changed: bool
    #: The `record-amend` event, if one was written.
    event: dict[str, Any] | None = None
    #: The id the corrected record can now also be reached by: an export carrying the corrected
    #: identity is matched to this record instead of being added again.
    alias: str | None = None
    #: Another record that already has the identity this one now has (run `strata dedup`).
    shares_identity_with: str | None = None


def preview_amendment(repo: Repo, *, record_id: str, field: str, value: str) -> bool:
    """Whether `amend_field` would change anything, raising what it would. Writes nothing."""
    record = get_record(repo, record_id)
    if record is None:
        raise RecordNotFoundError(f"no record with id {record_id!r}")
    stored_field, new_value = parse_value(record, field, value)
    return not _same_value(record.get(stored_field), new_value)


def _same_value(old: Any, new: Any) -> bool:
    return canonical_json(old) == canonical_json(new)


def amend_field(repo: Repo, *, record_id: str, field: str, value: str, actor: str) -> Amendment:
    """Correct one field of a record: `strata fix` (openspec:cli#correcting-a-record).

    Writes the corrected record and appends a `record-amend` event (`record`, `field`, `old`,
    `new`, `source`), per the event catalog in openspec:event-log#event-types. `source` is always
    `"manual"` here, distinguishing a human correction from `strata sync`'s automatic three-way
    merge resolution (openspec:git-integration#gitattributes), which emits the same event type with
    a different `source` value.

    `value` is what a person typed (`fieldedit.parse_value`): identifiers are normalised as an
    import normalises them, an empty value removes the field, and authors and dates are read from
    text. A value the record already has changes nothing and writes nothing.

    A correction that changes the record's canonical key (a DOI, an identifier, or the title,
    year or first author of a record that has none) keeps the record's id, which is permanent,
    and records the id the new key would give as an alias for it
    (openspec:record-identity#identifiers-are-permanent). An export that carries the corrected
    value is then matched to this record, not added beside it. If another record already has that
    identity, no alias is made and `shares_identity_with` names it.

    Raises `FixFieldError` for a field that cannot be corrected or a value that does not fit it,
    and `RecordNotFoundError` for an id with no matching record. `record_id` must already be a
    full, resolved id -- see `resolve_id_prefix` for turning a user-supplied abbreviation into one.
    """
    by_id = index_by_id(read_records(repo))
    if record_id not in by_id:
        raise RecordNotFoundError(f"no record with id {record_id!r}")
    record = by_id[record_id]
    stored_field, new_value = parse_value(record, field, value)
    old_value = record.get(stored_field)
    if _same_value(old_value, new_value):
        return Amendment(field=stored_field, old=old_value, new=new_value, changed=False)

    updated = {k: v for k, v in record.items() if k != stored_field}
    if new_value is not None:
        updated[stored_field] = new_value

    alias: str | None = None
    shares: str | None = None
    old_key, _ = canonical_key(record)
    new_key, _ = canonical_key(updated)
    if new_key != old_key:
        updated["strata"] = {**record.get("strata", {}), "canonical_key": new_key}
        new_id = record_id_for_key(new_key)
        if record.get("strata", {}).get("canonical", True) and new_id != record_id:
            holder = aliases_mod.resolve(repo, new_id) if new_id not in by_id else new_id
            if holder in by_id and holder != record_id:
                shares = holder
            elif new_id not in by_id and holder != record_id:
                alias = new_id

    by_id[record_id] = updated
    write_records(repo, list(by_id.values()))

    event = append_new_event(
        repo.path("events", "fix", f"{actor}.ndjson"),
        ev="record-amend",
        actor=actor,
        body={
            "record": record_id,
            "field": stored_field,
            "old": old_value,
            "new": new_value,
            "source": "manual",
        },
    )
    if alias is not None:
        aliases_mod.append_alias(
            repo, alias=alias, canonical=record_id, reason="correction", event=str(event["id"])
        )
    return Amendment(
        field=stored_field,
        old=old_value,
        new=new_value,
        changed=True,
        event=event,
        alias=alias,
        shares_identity_with=shares,
    )


def records_sharing_identity(repo: Repo, record: dict[str, Any]) -> list[str]:
    """Ids of the other canonical records that have the same canonical key as `record`."""
    key = record.get("strata", {}).get("canonical_key")
    return sorted(
        r["id"]
        for r in read_records(repo)
        if r["id"] != record["id"]
        and r.get("strata", {}).get("canonical", True)
        and r.get("strata", {}).get("canonical_key") == key
    )


def short_citation(record: dict[str, Any]) -> str:
    """`Cepeda et al. (2008)`: the label a person recognises a paper by, from CSL-JSON fields."""
    names: list[str] = []
    for author in record.get("author") or []:
        if isinstance(author, dict):
            names.append(str(author.get("family") or author.get("literal") or "").strip())
        else:
            names.append(str(author).strip())
    names = [n for n in names if n]
    if not names:
        who = "(no author)"
    elif len(names) == 1:
        who = names[0]
    elif len(names) == 2:
        who = f"{names[0]} & {names[1]}"
    else:
        who = f"{names[0]} et al."
    year = normalise_year(record.get("issued"))
    return f"{who} ({year})" if year is not None else who
