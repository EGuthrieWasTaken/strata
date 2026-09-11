"""`strata.toml` construction and editing.

Implements docs/spec/03-schemas.md §1. The manifest is hand-editable
(docs/spec/02-repository-format.md §3), so edits go through `tomlkit` rather
than the stdlib `tomllib`, to preserve comments and formatting the user wrote.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import tomlkit
from tomlkit import items as tomlkit_items

from strata import __version__

DEFAULT_STAGES = ["title-abstract", "full-text"]
DEFAULT_SOURCE_TRUST = ["crossref", "pubmed", "scopus", "wos", "embase", "ebsco", "manual"]


def build_initial_manifest(
    *,
    project_id: str,
    title: str,
    slug: str,
    created: str,
    actor_handle: str,
    actor_name: str,
    actor_email: str | None,
) -> tomlkit.TOMLDocument:
    doc = tomlkit.document()
    doc.add("schema_version", 1)
    doc.add("created_with", f"strata/{__version__}")

    project = tomlkit.table()
    project.add("id", project_id)
    project.add("title", title)
    project.add("slug", slug)
    project.add("created", created)
    doc.add("project", project)

    actor = tomlkit.table()
    actor.add("handle", actor_handle)
    actor.add("name", actor_name)
    if actor_email:
        actor.add("email", actor_email)
    actor.add("role", "lead")
    actors = tomlkit.aot()
    actors.append(actor)
    doc.add("actors", actors)

    screening = tomlkit.table()
    screening.add("stages", DEFAULT_STAGES)
    screening.add("mode", "dual")
    screening.add("adjudicators", [actor_handle])
    screening.add("blind_reviewers", True)
    screening.add("blind_metadata", False)
    screening.add("require_exclusion_reason", True)
    doc.add("screening", screening)

    dedup = tomlkit.table()
    dedup.add("auto_merge_threshold", 0.95)
    dedup.add("review_threshold", 0.80)
    dedup.add("source_trust", DEFAULT_SOURCE_TRUST)
    doc.add("dedup", dedup)

    git = tomlkit.table()
    git.add("commit_style", "structured")
    git.add("require_rationale", True)
    git.add("sync_strategy", "merge")
    git.add("remote", "origin")
    doc.add("git", git)

    enrichment = tomlkit.table()
    enrichment.add("enabled", False)
    enrichment.add("providers", tomlkit.array())
    enrichment.add("contact_email", "")
    doc.add("enrichment", enrichment)

    analysis = tomlkit.table()
    analysis.add("engine", "native")
    doc.add("analysis", analysis)

    return doc


def manifest_path(root: Path) -> Path:
    return root / "strata.toml"


def write_manifest(root: Path, doc: tomlkit.TOMLDocument) -> None:
    manifest_path(root).write_text(tomlkit.dumps(doc), encoding="utf-8")


def load_manifest_doc(root: Path) -> tomlkit.TOMLDocument:
    return tomlkit.parse(manifest_path(root).read_text(encoding="utf-8"))


def get_value(doc: tomlkit.TOMLDocument, dotted_key: str) -> Any:
    node: Any = doc
    for part in dotted_key.split("."):
        if not isinstance(node, dict) or part not in node:
            raise KeyError(dotted_key)
        node = node[part]
    if isinstance(node, tomlkit_items.Item):
        return node.unwrap()
    return node


def set_value(doc: tomlkit.TOMLDocument, dotted_key: str, value: Any) -> None:
    parts = dotted_key.split(".")
    node: Any = doc
    for part in parts[:-1]:
        if part not in node:
            node[part] = tomlkit.table()
        node = node[part]
    node[parts[-1]] = value


def find_actor(doc: tomlkit.TOMLDocument, handle: str) -> dict[str, Any] | None:
    for actor in doc.get("actors", []):
        if actor.get("handle") == handle:
            return cast(dict[str, Any], actor)
    return None
