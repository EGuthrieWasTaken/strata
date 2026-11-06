"""`strata actor add|list|deactivate`.

Implements openspec:data-schemas#project-manifest: handles are unique and match
`^[a-z0-9][a-z0-9-]{0,31}$`; an actor is never removed once they have
authored an event, only deactivated (`role = "inactive"`).

An actor is a person (the default) or, once a lead has enabled AI participation, an AI agent
(openspec:data-schemas#agent-actors-and-ai-settings): `kind = "agent"` with the `model` the review
accepts under that handle. Agents are registered here, by a person, and lose their standing only
through `strata ai revoke` (openspec:ai-participation#revoking-an-agent).
"""

from __future__ import annotations

import re
from typing import Any

import tomlkit

from strata.core import agents as agents_mod
from strata.core import manifest as manifest_mod
from strata.core.repo import Repo

HANDLE_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")
VALID_ROLES = frozenset({"lead", "screener", "extractor", "adjudicator", "observer", "inactive"})


class ActorError(ValueError):
    pass


def add_actor(
    repo: Repo,
    *,
    handle: str,
    name: str,
    email: str | None = None,
    role: str = "screener",
    kind: str = agents_mod.KIND_HUMAN,
    model: str | None = None,
) -> None:
    if not HANDLE_RE.match(handle):
        raise ActorError(f"invalid actor handle {handle!r} (must match {HANDLE_RE.pattern})")
    if role not in VALID_ROLES:
        raise ActorError(f"invalid role {role!r}; must be one of {sorted(VALID_ROLES)}")
    if kind not in (agents_mod.KIND_HUMAN, agents_mod.KIND_AGENT):
        raise ActorError(f"invalid kind {kind!r}; must be 'human' or 'agent'")
    if kind == agents_mod.KIND_AGENT:
        _check_can_register_agent(repo, role=role, model=model)
    elif model:
        raise ActorError("--model is only for an agent (--kind agent); a person has no model")

    doc = manifest_mod.load_manifest_doc(repo.root)
    if manifest_mod.find_actor(doc, handle) is not None:
        raise ActorError(f"actor {handle!r} already exists")

    actor = tomlkit.table()
    actor.add("handle", handle)
    actor.add("name", name)
    if email:
        actor.add("email", email)
    actor.add("role", role)
    if kind == agents_mod.KIND_AGENT:
        actor.add("kind", agents_mod.KIND_AGENT)
        actor.add("model", str(model))
    doc["actors"].append(actor)
    try:
        manifest_mod.validate_config(doc.unwrap())
    except manifest_mod.ConfigError as exc:
        raise ActorError(str(exc)) from exc
    manifest_mod.write_manifest(repo.root, doc)


def _check_can_register_agent(repo: Repo, *, role: str, model: str | None) -> None:
    """Refuse, in words that say what to do, an agent that cannot be registered now."""
    if not repo.supports_ai:
        raise ActorError(
            f"an agent can only be registered in format 2, and this repository is at format "
            f"{repo.schema_version}: run `strata ai enable` (it runs `strata migrate` for you), "
            "then register the agent"
        )
    if not agents_mod.is_enabled(repo):
        raise ActorError(
            "AI participation is not enabled for this review, so an agent cannot be registered "
            "yet: run `strata ai enable`"
        )
    if not model or not model.strip():
        raise ActorError(
            "an agent needs the model the review accepts under its handle: --model MODEL (the "
            "name the agent reports about itself)"
        )
    if role == "lead":
        raise ActorError("an AI agent cannot hold the role 'lead'")
    for existing in agents_mod.agent_actors(repo, active_only=True):
        if existing.get("model") == model:
            raise ActorError(
                f"the model {model!r} is already registered as the agent {existing['handle']!r}; "
                "a reported model must name exactly one active agent"
            )


def list_actors(repo: Repo) -> list[dict[str, Any]]:
    doc = manifest_mod.load_manifest_doc(repo.root)
    return [dict(a) for a in doc.get("actors", [])]


def active_actors(repo: Repo) -> list[dict[str, Any]]:
    """The review's actors who can still be given work: everyone not deactivated, in the order
    `strata.toml` lists them."""
    return [a for a in repo.config.get("actors", []) if a.get("role") != "inactive"]


def deactivate_actor(repo: Repo, handle: str, *, revoking: bool = False) -> None:
    """Set an actor's role to `inactive`. An agent is only ever deactivated by `strata ai revoke`
    (`revoking=True`), which also puts its counted decisions back in the queue for people."""
    doc = manifest_mod.load_manifest_doc(repo.root)
    actor = manifest_mod.find_actor(doc, handle)
    if actor is None:
        raise ActorError(f"actor {handle!r} not found")
    if agents_mod.is_agent(repo, handle) and not revoking:
        raise ActorError(
            f"{handle!r} is an AI agent, and an agent is removed with `strata ai revoke {handle}`, "
            "which also marks the decisions it counted for re-screening by people; its history "
            "stays in the record either way"
        )
    actor["role"] = "inactive"
    manifest_mod.write_manifest(repo.root, doc)
