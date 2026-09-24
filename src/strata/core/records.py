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
from strata.core.repo import Repo
from strata.core.validate import validate

RECORDS_PATH = ("records", "records.ndjson")


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
    for record in read_records(repo):
        if record["id"] == record_id:
            return record
    return None
