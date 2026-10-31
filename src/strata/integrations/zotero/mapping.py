"""`integrations/zotero.ndjson`: which Zotero item each record is.

Implements openspec:zotero-integration#identity-mapping. The file is committed, append-only and
merged by union, like the full-text manifest, so two collaborators linking at once never conflict:
a changed link is a new row, and the row with the highest `item_version` for a record and item is
the one that counts.

```json
{"record":"rec_3kq8v1r0zx2m4a7b","library":"users/12345","item_key":"AB3D9XYZ","item_version":8842,
 "linked":"2026-03-28","via":"doi"}
```

`via` is the rung of the canonical-key ladder the item was matched by, or `created` for an item
`strata` itself made in Zotero. That last value is how `strata` knows which items it may change.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from strata.core.canon import canonical_json
from strata.core.repo import Repo
from strata.core.validate import validate

MAPPING_PATH = ("integrations", "zotero.ndjson")
CREATED = "created"


@dataclass(frozen=True)
class MappingRow:
    record: str
    library: str
    item_key: str
    item_version: int
    linked: str
    via: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "record": self.record,
            "library": self.library,
            "item_key": self.item_key,
            "item_version": self.item_version,
            "linked": self.linked,
            "via": self.via,
        }

    @property
    def created_by_strata(self) -> bool:
        return self.via == CREATED


def mapping_path(repo: Repo) -> Path:
    return repo.path(*MAPPING_PATH)


def read_mapping(repo: Repo) -> list[MappingRow]:
    """Every row, in file order. A missing file is an empty mapping."""
    path = mapping_path(repo)
    if not path.exists():
        return []
    rows: list[MappingRow] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        data = json.loads(line)
        validate("zotero-mapping", data)
        rows.append(MappingRow(**data))
    return rows


def append_rows(repo: Repo, rows: Iterable[MappingRow]) -> int:
    """Validate and append rows; how many were written. Nothing is written if any row is invalid."""
    data = [row.as_dict() for row in rows]
    for item in data:
        validate("zotero-mapping", item)
    if not data:
        return 0
    path = mapping_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="\n") as handle:
        for item in data:
            handle.write(canonical_json(item) + "\n")
    return len(data)


def current_rows(rows: Sequence[MappingRow], library: str) -> list[MappingRow]:
    """The row that counts for each (record, item) in a library: the highest `item_version`, and
    the later row of two that tie. In first-seen order, so the result does not depend on how a
    union merge happened to interleave the file."""
    best: dict[tuple[str, str], MappingRow] = {}
    for row in rows:
        if row.library != library:
            continue
        key = (row.record, row.item_key)
        held = best.get(key)
        if held is None or row.item_version >= held.item_version:
            best[key] = row
    return list(best.values())


def absorbed_into(records: Iterable[Mapping[str, Any]]) -> dict[str, str]:
    """Absorbed record id -> the canonical record that took it in (openspec:deduplication)."""
    result: dict[str, str] = {}
    for record in records:
        for absorbed in record.get("strata", {}).get("absorbed", []):
            result[str(absorbed)] = str(record["id"])
    return result


def canonical_record_id(
    record_id: str, known: Mapping[str, Any], absorbed: Mapping[str, str]
) -> str | None:
    """The canonical record a mapped record id stands for now, or `None` if it no longer exists.

    A merge in `strata dedup` can absorb the record a row names; the row then belongs to the
    record that absorbed it.
    """
    seen: set[str] = set()
    node = record_id
    while node in absorbed and node not in seen:
        seen.add(node)
        node = absorbed[node]
    return node if node in known else None


def row_for_record(
    rows: Sequence[MappingRow],
    library: str,
    record_id: str,
    *,
    follow: Mapping[str, str] | None = None,
) -> MappingRow | None:
    """The item a record is linked to in a library: the most recently linked, then the highest key.

    `follow` maps an absorbed record id to its canonical record, so a link made to a record that
    has since been merged away still serves the record that remains.
    """
    candidates = [
        row
        for row in current_rows(rows, library)
        if (follow or {}).get(row.record, row.record) == record_id
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda r: (r.linked, r.item_version, r.item_key))
