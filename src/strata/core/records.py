"""`records/records.ndjson`: canonical bibliographic records.

Implements docs/spec/03-schemas.md §2 (the record shape) and
docs/spec/02-repository-format.md §5.2 (ordering: sorted by `id`, ascending,
byte-wise; new records land in hash order rather than at the end).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from strata.core.canon import canonical_json
from strata.core.events import append_new_event
from strata.core.filters import FieldResolver, FilterEvaluationError
from strata.core.ids import normalise_year
from strata.core.repo import Repo
from strata.core.validate import validate

RECORDS_PATH = ("records", "records.ndjson")

# The record schema's plain string fields a human can safely correct with
# `strata fix --field <f> --value <v>` (docs/spec/10-cli.md §2). `id`/`type`
# are identity, not metadata; `author`/`issued`/`strata` are structured, not
# a flat string -- `strata fix` doesn't support editing those yet.
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

# docs/spec/10-cli.md §3's "Available fields" table lists many fields that
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
    """No record's id starts with the given prefix (docs/spec/10-cli.md §1:
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
    """Validate and write the full record set, sorted by id (§5.2).

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

    `docs/spec/13-nonfunctional.md` §1's "screening decision round trip
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
    """The one record id starting with `prefix`, per docs/spec/10-cli.md §1:
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


def record_field_resolver(record: dict[str, Any]) -> FieldResolver:
    """A `strata.core.filters.FieldResolver` over the M1 subset of
    docs/spec/10-cli.md §3's "Available fields" table -- the fields a bare
    bibliographic record actually has data for at this milestone.

    `via`/`search` resolve to the record's *first* source's value: the
    spec's table types both as scalar `string`, but a merged record's
    `strata.sources` can hold several entries (one per absorbed duplicate).
    The first source is the one that originally established the record,
    which is what "how was this record found" most naturally means; a
    query that needs *any* source's via/search isn't expressible with this
    resolver, a known limitation of treating a spec-scalar field this way.
    """

    def resolve(field: str) -> Any:
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


class FixFieldError(ValueError):
    """`strata fix --field <f>` named a field `amend_field` cannot correct."""


def amend_field(
    repo: Repo, *, record_id: str, field: str, value: str, actor: str
) -> tuple[Any, Any]:
    """Correct one plain-string field on a record: `strata fix` (docs/spec/10-cli.md §2).

    Returns `(old_value, new_value)`. Writes the updated record set and
    appends a `record-amend` event (`record`, `field`, `old`, `new`,
    `source`), per the event catalog in docs/spec/02-repository-format.md
    §4.4. `source` is always `"manual"` here, distinguishing a human
    correction from `strata sync`'s automatic three-way-merge resolution
    (docs/spec/04-git-integration.md §3), which emits the same event type
    with a different `source` value.

    Raises `FixFieldError` for a field that isn't one of
    `EDITABLE_STRING_FIELDS` (structured fields like `author`/`issued`
    aren't expressible as a single string value) and `RecordNotFoundError`
    for an id with no matching record. `record_id` must already be a full,
    resolved id -- see `resolve_id_prefix` for turning a user-supplied
    abbreviation into one.
    """
    if field not in EDITABLE_STRING_FIELDS:
        raise FixFieldError(
            f"field {field!r} cannot be corrected with `strata fix` -- only plain string "
            f"fields can: {', '.join(sorted(EDITABLE_STRING_FIELDS))}. `author` and `issued` "
            "are structured fields, not editable this way yet."
        )

    by_id = index_by_id(read_records(repo))
    if record_id not in by_id:
        raise RecordNotFoundError(f"no record with id {record_id!r}")

    record = by_id[record_id]
    old_value = record.get(field)
    by_id[record_id] = {**record, field: value}
    write_records(repo, list(by_id.values()))

    events_path = repo.path("events", "fix", f"{actor}.ndjson")
    append_new_event(
        events_path,
        ev="record-amend",
        actor=actor,
        body={
            "record": record_id,
            "field": field,
            "old": old_value,
            "new": value,
            "source": "manual",
        },
    )
    return old_value, value
