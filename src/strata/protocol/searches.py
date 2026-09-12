"""Search recording: `protocol/searches/<id>.yaml`.

Implements docs/spec/05-workflow-import.md §1 and docs/spec/03-schemas.md §5.
PRISMA item 7 requires the full search strategy for every database, so the
query string is never optional at the schema level -- when the caller does
not have it yet, `PENDING_QUERY` is recorded instead and `strata status`
reports it as an outstanding requirement (docs/spec/10-cli.md §4).

Re-running a search on a later date is a **new** file with `supersedes` set,
never an edit -- PRISMA requires the full history of what was actually run.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ruamel.yaml.scalarstring import FoldedScalarString, LiteralScalarString

from strata.core import manifest as manifest_mod
from strata.core.canon import dump_yaml_str, load_yaml_str
from strata.core.repo import Repo
from strata.core.validate import validate

PENDING_QUERY = "PENDING"
SEARCHES_DIR = ("protocol", "searches")

# Schema-declared key order (docs/spec/02-repository-format.md §5.3: YAML keys
# follow the schema, not sorted, because these files are read by humans).
_FIELD_ORDER = (
    "id",
    "database",
    "platform",
    "executed",
    "executed_by",
    "query",
    "limits",
    "hits",
    "export_files",
    "peer_reviewed_by",
    "notes",
    "supersedes",
)


class SearchError(ValueError):
    pass


def searches_dir(repo: Repo) -> Path:
    return repo.path(*SEARCHES_DIR)


def search_path(repo: Repo, search_id: str) -> Path:
    return searches_dir(repo) / f"{search_id}.yaml"


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "search"


def next_search_id(repo: Repo, database: str) -> str:
    """Suggest `S-<nn>-<database-slug>`, the next unused number for this database's slug."""
    slug = _slugify(database)
    existing = {p.stem for p in searches_dir(repo).glob("*.yaml")}
    n = 1
    while True:
        candidate = f"S-{n:02d}-{slug}"
        if candidate not in existing:
            return candidate
        n += 1


def list_searches(repo: Repo) -> list[dict[str, Any]]:
    """All recorded searches, sorted by id."""
    results: list[dict[str, Any]] = []
    if not searches_dir(repo).exists():
        return results
    for path in searches_dir(repo).glob("*.yaml"):
        data = load_yaml_str(path.read_text(encoding="utf-8"))
        if data:
            results.append(dict(data))
    return sorted(results, key=lambda s: str(s["id"]))


def get_search(repo: Repo, search_id: str) -> dict[str, Any] | None:
    path = search_path(repo, search_id)
    if not path.exists():
        return None
    data = load_yaml_str(path.read_text(encoding="utf-8"))
    return dict(data) if data else None


def pending_search_ids(repo: Repo) -> list[str]:
    """Ids of searches recorded with no query string yet (PRISMA item 7)."""
    return [str(s["id"]) for s in list_searches(repo) if s.get("query") == PENDING_QUERY]


def add_search(
    repo: Repo,
    *,
    database: str,
    platform: str,
    executed: str,
    executed_by: str,
    search_id: str | None = None,
    query: str | None = None,
    limits: dict[str, Any] | None = None,
    hits: int | None = None,
    export_files: list[str] | None = None,
    peer_reviewed_by: str | None = None,
    notes: str | None = None,
    supersedes: str | None = None,
) -> dict[str, Any]:
    """Record one executed search as `protocol/searches/<id>.yaml`.

    Returns the plain-dict record actually written (with `query` resolved to
    `PENDING_QUERY` if none was supplied). Raises `SearchError` for a
    duplicate id, an unknown `supersedes` target, or an `executed_by` that
    does not name a configured actor.
    """
    manifest_doc = manifest_mod.load_manifest_doc(repo.root)
    if manifest_mod.find_actor(manifest_doc, executed_by) is None:
        raise SearchError(f"executed_by {executed_by!r} is not a configured actor")

    resolved_id = search_id or next_search_id(repo, database)
    if search_path(repo, resolved_id).exists():
        raise SearchError(f"a search {resolved_id!r} already exists")
    if supersedes is not None and get_search(repo, supersedes) is None:
        raise SearchError(f"supersedes references unknown search {supersedes!r}")

    query_value = query.strip() if query and query.strip() else PENDING_QUERY

    data: dict[str, Any] = {
        "id": resolved_id,
        "database": database,
        "platform": platform,
        "executed": executed,
        "executed_by": executed_by,
        "query": query_value,
        "limits": limits,
        "hits": hits,
        "export_files": list(export_files) if export_files else [],
        "peer_reviewed_by": peer_reviewed_by,
        "notes": notes,
        "supersedes": supersedes,
    }
    validate("search", data)

    yaml_data = {key: data[key] for key in _FIELD_ORDER}
    yaml_data["query"] = LiteralScalarString(query_value)
    if notes:
        yaml_data["notes"] = FoldedScalarString(notes)

    searches_dir(repo).mkdir(parents=True, exist_ok=True)
    search_path(repo, resolved_id).write_text(dump_yaml_str(yaml_data), encoding="utf-8")
    return data
