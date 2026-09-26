"""`records/aliases.ndjson`: absorbed-id -> canonical-id.

Implements openspec:record-identity#alias-resolution. Alias resolution is transitive
by construction here: a merge only ever appends one new `alias -> canonical`
edge for the record it just absorbed, never rewrites an older entry, so a
record absorbed twice (once into an intermediate canonical, later again when
that canonical is itself absorbed) resolves correctly by chain-walking
(`resolve`) rather than needing history rewritten.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from strata.core.canon import canonical_json
from strata.core.repo import Repo

ALIASES_PATH = ("records", "aliases.ndjson")


def aliases_path(repo: Repo) -> Path:
    return repo.path(*ALIASES_PATH)


def read_aliases(repo: Repo) -> list[dict[str, Any]]:
    path = aliases_path(repo)
    if not path.exists():
        return []
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def write_aliases(repo: Repo, entries: list[dict[str, Any]]) -> None:
    path = aliases_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(canonical_json(entry) + "\n" for entry in entries)
    path.write_text(text, encoding="utf-8")


def append_alias(repo: Repo, *, alias: str, canonical: str, reason: str, event: str) -> None:
    entries = read_aliases(repo)
    entries.append({"alias": alias, "canonical": canonical, "reason": reason, "event": event})
    write_aliases(repo, entries)


def remove_alias(repo: Repo, alias: str) -> dict[str, Any] | None:
    """Drop the entry for `alias` (used by `--undo`). Returns the removed entry, if any."""
    entries = read_aliases(repo)
    remaining, removed = [], None
    for entry in entries:
        if entry["alias"] == alias and removed is None:
            removed = entry
        else:
            remaining.append(entry)
    write_aliases(repo, remaining)
    return removed


def resolve(repo: Repo, record_id: str) -> str:
    """Follow the alias chain from `record_id` to its current canonical id.

    Returns `record_id` unchanged if it is not an alias of anything.
    `strata verify` is what checks this graph for cycles
    (`E_ALIAS_CYCLE`); this function assumes it is acyclic, per that check.
    """
    edges = {entry["alias"]: entry["canonical"] for entry in read_aliases(repo)}
    node = record_id
    seen: set[str] = set()
    while node in edges and node not in seen:
        seen.add(node)
        node = edges[node]
    return node
