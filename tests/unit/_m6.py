"""Builders for the AI-participation tests: a review that went through the real operations, so the
manifest, the format marker and the commits are those a lead's own repository would have."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from strata.core import operations as ops_mod
from strata.core.actor import add_actor
from strata.core.repo import Repo, open_repo
from tests.unit._m3 import init_review

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
