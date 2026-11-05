"""AI participation: the policy, the agents, and the checks a write by an agent must pass.

Implements openspec:ai-participation. `strata` ships no model and makes no network call. An agent is
somebody else's software on the far end of MCP, and everything here is about *accounting for it*:
a review's reviewers decide whether, where and how far AI may take part (`[ai]`, `[ai.policy]` in
`strata.toml`, committed, off by default); each model they accept is a registered actor of
`kind = "agent"`; and every write carries who (the model, as the agent reported it) and for whom
(the person who started the server).

The model name is the agent's own claim. Nothing here verifies it, and the wording of everything
generated from it says so.

This module reads the configuration and answers questions about it. Writing the policy is
`strata.core.operations` (a rationale-bearing commit); acting on a refusal is the caller's.
"""

from __future__ import annotations

import contextlib
import contextvars
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Any

import tomlkit
from tomlkit import items as tomlkit_items

from strata.core import manifest as manifest_mod
from strata.core.events import agent_scope
from strata.core.repo import Repo

#: The kinds of work a policy sets a mode for
#: (openspec:ai-participation#a-policy-for-each-kind-of-work).
KINDS_OF_WORK: tuple[str, ...] = (
    "screening",
    "extraction",
    "risk-of-bias",
    "retrieval",
    "studies",
    "dedup",
    "records",
    "search-import",
    "criteria",
    "adjudication",
    "analysis",
)

MODE_OFF = "off"
MODE_SUGGEST = "suggest"
MODE_COUNT = "count"
MODES: tuple[str, ...] = (MODE_OFF, MODE_SUGGEST, MODE_COUNT)

SHOW_AFTER_OWN_DECISION = "after-own-decision"
SHOW_ALWAYS = "always"
SHOW_SUGGESTIONS_CHOICES: tuple[str, ...] = (SHOW_AFTER_OWN_DECISION, SHOW_ALWAYS)

#: Where an agent's work is read as opinions that fill a reviewer slot. Other kinds have no slot.
OPINION_KINDS = frozenset({"screening", "extraction", "risk-of-bias"})

KIND_HUMAN = "human"
KIND_AGENT = "agent"

# Refusal codes. They are stable: a client can branch on them without parsing the message.
REFUSED_NOT_ENABLED = "AI_NOT_ENABLED"
REFUSED_POLICY_OFF = "AI_POLICY_OFF"
REFUSED_NO_MODEL = "AI_NO_MODEL"
REFUSED_UNKNOWN_MODEL = "AI_UNKNOWN_MODEL"
REFUSED_DEACTIVATED = "AI_AGENT_DEACTIVATED"
REFUSED_NO_INVOKER = "AI_NO_INVOKER"
REFUSED_BAD_INVOKER = "AI_BAD_INVOKER"


class AgentRefused(Exception):
    """A write by an agent is refused. Nothing is recorded; the message says what to do next."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


# ------------------------------------------------------------------------------ the configuration


def _ai_section(repo: Repo) -> Mapping[str, Any]:
    section = repo.config.get("ai", {})
    return section if isinstance(section, Mapping) else {}


def is_enabled(repo: Repo) -> bool:
    """Whether the review accepts agent-authored events and suggestions at all.

    Both halves are needed: the lead enabled it in `strata.toml` *and* the repository is in a format
    that permits it, so an older tool, or a hand edit of one half, never reads as "on".
    """
    return bool(_ai_section(repo).get("enabled", False)) and repo.supports_ai


def show_suggestions(repo: Repo) -> str:
    """When a reviewer may see an agent's suggestion about a record (`[ai] show_suggestions`)."""
    value = _ai_section(repo).get("show_suggestions", SHOW_AFTER_OWN_DECISION)
    return str(value) if value in SHOW_SUGGESTIONS_CHOICES else SHOW_AFTER_OWN_DECISION


def policy(repo: Repo) -> dict[str, str]:
    """The mode for every kind of work, in the order of `KINDS_OF_WORK`; `off` unless set.

    A review that has not enabled AI has every kind `off`, whatever a hand-edited policy table says.
    """
    configured = _ai_section(repo).get("policy", {})
    enabled = is_enabled(repo)
    return {
        kind: (str(configured.get(kind, MODE_OFF)) if enabled else MODE_OFF)
        for kind in KINDS_OF_WORK
    }


def mode_for(repo: Repo, kind: str) -> str:
    """The mode for one kind of work. Raises `ValueError` for a kind that is not one."""
    if kind not in KINDS_OF_WORK:
        raise ValueError(unknown_kind_message(kind))
    return policy(repo)[kind]


def unknown_kind_message(kind: str) -> str:
    return f"unknown kind of work {kind!r}; the kinds are {', '.join(KINDS_OF_WORK)}"


# ------------------------------------------------------------------------------------- the actors


def _actor_kind(actor: Mapping[str, Any]) -> str:
    return str(actor.get("kind", KIND_HUMAN))


def is_agent(repo: Repo, handle: str) -> bool:
    """Whether `handle` is a registered agent actor (active or not)."""
    return handle in agent_handles(repo)


def agent_handles(repo: Repo) -> frozenset[str]:
    """Every registered agent actor, deactivated ones included: their history is still theirs."""
    return frozenset(
        str(a["handle"]) for a in repo.config.get("actors", []) if _actor_kind(a) == KIND_AGENT
    )


def agent_actors(repo: Repo, *, active_only: bool = False) -> list[dict[str, Any]]:
    """The review's agent actors, in the order `strata.toml` lists them."""
    return [
        dict(a)
        for a in repo.config.get("actors", [])
        if _actor_kind(a) == KIND_AGENT and not (active_only and a.get("role") == "inactive")
    ]


def human_actors(repo: Repo) -> list[dict[str, Any]]:
    """The review's people (every actor that is not an agent), deactivated ones included."""
    return [dict(a) for a in repo.config.get("actors", []) if _actor_kind(a) != KIND_AGENT]


def accepted_models(repo: Repo) -> list[str]:
    """The models the review accepts: those of its active agent actors."""
    return [str(a["model"]) for a in agent_actors(repo, active_only=True) if a.get("model")]


# ---------------------------------------------------------------------------------- the invoker


@dataclass(frozen=True)
class Invoker:
    """The person on whose behalf agents act, or why there is none."""

    handle: str | None
    problem: str | None = None


def resolve_invoker(repo: Repo, as_handle: str | None = None) -> Invoker:
    """Who started the server (openspec:mcp-server#the-invoking-person).

    With `as_handle`, that person must be an active, non-observer *person*; naming an agent, an
    observer, a deactivated person or a stranger gives no invoker and says why. Without it, the
    review's only such person is used; with none or several there is no invoker.
    """
    candidates = [
        str(a["handle"])
        for a in human_actors(repo)
        if a.get("role") not in ("inactive", "observer")
    ]
    if as_handle is not None:
        actor = next(
            (a for a in repo.config.get("actors", []) if a.get("handle") == as_handle), None
        )
        if actor is None:
            return Invoker(None, f"--as {as_handle!r} is not an actor of this review")
        if _actor_kind(actor) == KIND_AGENT:
            return Invoker(None, f"--as {as_handle!r} is an AI agent; it must name a person")
        if actor.get("role") == "inactive":
            return Invoker(None, f"--as {as_handle!r} has been deactivated")
        if actor.get("role") == "observer":
            return Invoker(
                None, f"--as {as_handle!r} is an observer, and observers cannot invoke agents"
            )
        return Invoker(as_handle)
    if len(candidates) == 1:
        return Invoker(candidates[0])
    if not candidates:
        return Invoker(None, "this review has no active person who can invoke an agent")
    return Invoker(
        None,
        f"this review has {len(candidates)} active people ({', '.join(candidates)}), so the "
        "server needs to be told who is invoking agents: start it with `strata mcp --as HANDLE`",
    )


# ---------------------------------------------------------------------------------- the context


@dataclass(frozen=True)
class AgentContext:
    """What a write by an agent carries: who did it, as whom, and for whom.

    It is built once per write by `authorise` and handed down to the code that appends events, which
    puts `envelope_value()` in the `agent` envelope key and the rest in the commit's author and
    trailers (openspec:ai-participation#every-agent-event-is-attributed).
    """

    #: The agent actor's handle: the `actor` of every event it causes.
    actor: str
    #: The model name exactly as the agent reported it.
    model: str
    #: The person who started the server.
    invoked_by: str
    client_name: str | None = None
    client_version: str | None = None

    def envelope_value(self) -> dict[str, Any]:
        """The `agent` envelope key (openspec:event-log#event-envelope)."""
        value: dict[str, Any] = {"model": self.model, "invoked_by": self.invoked_by}
        client = {
            key: val
            for key, val in (("name", self.client_name), ("version", self.client_version))
            if val
        }
        if client:
            value["client"] = client
        return value

    def commit_author(self) -> str:
        """`Name <address>` for the commit's author: the agent, and whose session it was.

        The address is on the reserved `.invalid` domain, which can never be delivered to or matched
        to a hosting account, so nothing is credited to a stranger or to the person.
        """
        return f"{self.actor} (via {self.invoked_by}) <{self.actor}@agents.invalid>"

    def commit_trailers(self) -> dict[str, str]:
        """The trailers an agent's commit carries so that `strata log` can find it."""
        return {
            "Agent": self.actor,
            "Invoked-By": self.invoked_by,
            "Via": "mcp",
            "Model": self.model,
        }


_ACTING: contextvars.ContextVar[AgentContext | None] = contextvars.ContextVar(
    "strata_acting_agent", default=None
)


@contextlib.contextmanager
def acting_as(context: AgentContext) -> Iterator[None]:
    """Run a block as the agent `context` describes: every event is the agent's, with its `agent`
    key, and every commit is authored by the agent and committed by the person."""
    token = _ACTING.set(context)
    try:
        with agent_scope(context.actor, context.envelope_value()):
            yield
    finally:
        _ACTING.reset(token)


def current_context() -> AgentContext | None:
    """The agent whose write is in progress, if one is."""
    return _ACTING.get()


@dataclass(frozen=True)
class Authorised:
    """A write that may go ahead: the identity it carries and the mode it runs in."""

    context: AgentContext
    mode: str


def agent_for_model(repo: Repo, model: str | None) -> dict[str, Any]:
    """The active agent actor registered for the model an agent reports, or `AgentRefused`.

    The match is exact: a model name that differs in case, by a suffix or by a version is a
    different model and is refused with the way to accept it. A deactivated agent is refused as
    such. Used by every write and by the reads that are about the agent itself.
    """
    reported = (model or "").strip()
    if not reported:
        raise AgentRefused(
            REFUSED_NO_MODEL,
            "a model name is required: every write must say which model is acting, as the agent "
            "itself reports it",
        )
    registered = [a for a in agent_actors(repo) if a.get("model") == reported]
    active = [a for a in registered if a.get("role") != "inactive"]
    if active:
        return active[0]
    if registered:
        raise AgentRefused(
            REFUSED_DEACTIVATED,
            f"the agent {registered[0]['handle']!r} registered for the model {reported!r} "
            "has been deactivated, so its work is no longer accepted by this review",
        )
    accepted = accepted_models(repo)
    accepted_text = (
        f" This review accepts: {', '.join(accepted)}." if accepted else " It accepts no model yet."
    )
    raise AgentRefused(
        REFUSED_UNKNOWN_MODEL,
        f"the model {reported!r} is not one this review accepts.{accepted_text} A lead can "
        f"accept it with `strata actor add NAME --kind agent --model {reported} "
        "--role screener`.",
    )


def authorise(
    repo: Repo,
    *,
    kind: str,
    model: str | None,
    invoked_by: str | None,
    client_name: str | None = None,
    client_version: str | None = None,
) -> Authorised:
    """Decide whether an agent may do `kind` of work now, or raise `AgentRefused`.

    Checked every call, never cached, so a lead changing the policy mid-session takes effect on the
    next write. The order is the order of usefulness to the person reading the refusal: first
    whether AI is on at all, then whether this kind of work is, then who is asking.
    """
    if kind not in KINDS_OF_WORK:
        raise ValueError(unknown_kind_message(kind))
    if not is_enabled(repo):
        raise AgentRefused(
            REFUSED_NOT_ENABLED,
            "AI participation is not enabled for this review, so no agent may write to it. "
            "A lead enables it with `strata ai enable`.",
        )
    registered_agent = agent_for_model(repo, model)
    reported = str(registered_agent["model"])
    mode = mode_for(repo, kind)
    if mode == MODE_OFF:
        raise AgentRefused(
            REFUSED_POLICY_OFF,
            f'this review\'s AI policy has {kind!r} set to "off" ([ai.policy] {kind}), so an '
            f"agent cannot do this kind of work here. A lead can change it with "
            f"`strata ai policy {kind} suggest`.",
        )

    if not invoked_by:
        raise AgentRefused(
            REFUSED_NO_INVOKER,
            "no person is named as invoking this agent. Start the server with "
            "`strata mcp --as HANDLE` so that every write says who is responsible for it.",
        )
    invoker = resolve_invoker(repo, invoked_by)
    if invoker.handle is None:
        raise AgentRefused(REFUSED_BAD_INVOKER, invoker.problem or "the invoking person is invalid")

    return Authorised(
        context=AgentContext(
            actor=str(registered_agent["handle"]),
            model=reported,
            invoked_by=invoker.handle,
            client_name=client_name,
            client_version=client_version,
        ),
        mode=mode,
    )


# ------------------------------------------------------------------------ editing the manifest


def enable_in_doc(doc: tomlkit.TOMLDocument) -> bool:
    """Turn AI participation on in `doc`, every kind of work `off`. False if it already was on."""
    existing = doc.get("ai")
    if existing is not None and existing.get("enabled", False):
        return False
    ai = tomlkit.table()
    ai.add("enabled", True)
    policy_table = tomlkit.table()
    for kind in KINDS_OF_WORK:
        policy_table.add(kind, MODE_OFF)
    if existing is not None:
        # An [ai] table a lead wrote by hand before enabling: keep what it says, turn it on.
        for key, value in existing.items():
            if key not in ("enabled", "policy"):
                ai.add(key, value)
        for kind, mode in existing.get("policy", {}).items():
            policy_table[kind] = mode
    ai.add("policy", policy_table)
    doc["ai"] = ai
    return True


def set_policy_in_doc(doc: tomlkit.TOMLDocument, kind: str, mode: str) -> tuple[str, str]:
    """Set one kind of work to `mode` in `doc`; returns `(old, new)`.

    Raises `ValueError` for an unknown kind or mode (naming the valid ones) and `ConfigError` when
    the review has not enabled AI.
    """
    if kind not in KINDS_OF_WORK:
        raise ValueError(unknown_kind_message(kind))
    if mode not in MODES:
        raise ValueError(f"unknown mode {mode!r}; the modes are {', '.join(MODES)}")
    ai = doc.get("ai")
    if ai is None or not ai.get("enabled", False):
        raise manifest_mod.ConfigError(
            ["AI participation is not enabled for this review; run `strata ai enable` first"]
        )
    policy_table = ai.get("policy")
    if policy_table is None:
        policy_table = tomlkit.table()
        ai["policy"] = policy_table
    previous = policy_table.get(kind, MODE_OFF)
    old = previous.unwrap() if isinstance(previous, tomlkit_items.Item) else str(previous)
    policy_table[kind] = mode
    return str(old), mode
