"""`strata actor add|list|deactivate`.

Implements openspec:data-schemas#project-manifest: handles are unique and match
`^[a-z0-9][a-z0-9-]{0,31}$`; an actor is never removed once they have
authored an event, only deactivated (`role = "inactive"`).
"""

from __future__ import annotations

import re
from typing import Any

import tomlkit

from strata.core import manifest as manifest_mod
from strata.core.repo import Repo

HANDLE_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")
VALID_ROLES = frozenset({"lead", "screener", "extractor", "adjudicator", "observer", "inactive"})


class ActorError(ValueError):
    pass


def add_actor(
    repo: Repo, *, handle: str, name: str, email: str | None = None, role: str = "screener"
) -> None:
    if not HANDLE_RE.match(handle):
        raise ActorError(f"invalid actor handle {handle!r} (must match {HANDLE_RE.pattern})")
    if role not in VALID_ROLES:
        raise ActorError(f"invalid role {role!r}; must be one of {sorted(VALID_ROLES)}")
    doc = manifest_mod.load_manifest_doc(repo.root)
    if manifest_mod.find_actor(doc, handle) is not None:
        raise ActorError(f"actor {handle!r} already exists")

    actor = tomlkit.table()
    actor.add("handle", handle)
    actor.add("name", name)
    if email:
        actor.add("email", email)
    actor.add("role", role)
    doc["actors"].append(actor)
    manifest_mod.write_manifest(repo.root, doc)


def list_actors(repo: Repo) -> list[dict[str, Any]]:
    doc = manifest_mod.load_manifest_doc(repo.root)
    return [dict(a) for a in doc.get("actors", [])]


def deactivate_actor(repo: Repo, handle: str) -> None:
    doc = manifest_mod.load_manifest_doc(repo.root)
    actor = manifest_mod.find_actor(doc, handle)
    if actor is None:
        raise ActorError(f"actor {handle!r} not found")
    actor["role"] = "inactive"
    manifest_mod.write_manifest(repo.root, doc)
