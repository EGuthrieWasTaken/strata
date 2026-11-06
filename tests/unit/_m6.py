"""Builders for the AI-participation tests: a review that went through the real operations, so the
manifest, the format marker and the commits are those a lead's own repository would have."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from strata.core import operations as ops_mod
from strata.core.actor import add_actor
from strata.core.agents import AgentContext
from strata.core.repo import Repo, open_repo
from strata.protocol import criteria as criteria_mod
from strata.protocol import suggestions as suggestions_mod
from tests.unit._m3 import add_records, init_review

MODEL = "claude-opus-5-5"
AGENT = "claude-opus"
WHY = "Piloting AI help on this review, as the protocol allows."


def ai_review(
    tmp_path: Path,
    *,
    people: tuple[str, ...] = ("sam",),
    agents: Mapping[str, str] | None = None,
    policy: Mapping[str, str] | None = None,
) -> Repo:
    """A review (`ethan` leads) with AI enabled, the agents registered and the policy set.

    `agents` maps a handle to the model registered for it (default: `claude-opus` for
    `claude-opus-5-5`); `policy` maps a kind of work to a mode.
    """
    repo = init_review(tmp_path, actors=people)
    ops_mod.enable_ai(repo, rationale=WHY)
    repo = open_repo(repo.root)
    for handle, model in (agents if agents is not None else {AGENT: MODEL}).items():
        add_actor(
            repo, handle=handle, name=handle.title(), role="screener", kind="agent", model=model
        )
        repo = open_repo(repo.root)
    for kind, mode in (policy or {}).items():
        ops_mod.set_ai_policy(repo, kind=kind, mode=mode, rationale=WHY)
        repo = open_repo(repo.root)
    return repo


# ---------------------------------------------------------------------------- suggestions

STAGE = "title-abstract"


def context(invoked_by: str = "sam", actor: str = AGENT, model: str = MODEL) -> AgentContext:
    return AgentContext(
        actor=actor,
        model=model,
        invoked_by=invoked_by,
        client_name="claude-code",
        client_version="2.1.3",
    )


def add_criteria(repo: Repo) -> None:
    """EXC-01 (not empirical) and EXC-02 (wrong population), both applying at both stages."""
    for label in ("Not empirical", "Wrong population"):
        criteria_mod.add_criterion(
            repo,
            kind="exclusion",
            label=label,
            definition=f"{label}.",
            applies_at=[STAGE, "full-text"],
            actor="ethan",
            rationale="Establishing the protocol.",
        )


def suggest_world(tmp_path: Path, *, records: int = 4, **kwargs: object) -> tuple[Repo, list[str]]:
    """A review with AI on, screening in `suggest` mode, two exclusion criteria and records.

    `kwargs` go to `ai_review`; `policy` defaults to screening and criteria on `suggest`.
    """
    kwargs.setdefault("policy", {"screening": "suggest", "criteria": "suggest"})
    repo = ai_review(tmp_path, **kwargs)  # type: ignore[arg-type]
    add_criteria(repo)
    ids = add_records(repo, records)
    return open_repo(repo.root), ids


def suggest_screen(
    repo: Repo,
    record: str,
    decision: str = "include",
    *,
    ctx: AgentContext | None = None,
    criteria: list[str] | None = None,
    rationale: str = "Meets the population and outcome criteria.",
    stage: str = STAGE,
) -> dict[str, Any]:
    args: dict[str, Any] = {"stage": stage, "record": record, "decision": decision}
    if criteria is not None:
        args["criteria"] = criteria
    return suggestions_mod.make_suggestion(
        repo, context=ctx or context(), op="screen", args=args, rationale=rationale
    )


def derived_bytes(repo: Repo) -> dict[str, bytes]:
    root = repo.path("derived")
    return {p.name: p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}
