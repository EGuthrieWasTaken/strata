"""Blinding between reviewers: which opinions a reviewer must not be shown yet.

openspec:screening#dual-independent-screening-with-blinding asks that no surface reveal another
reviewer's decision before the current reviewer records their own. On a local install that is
also protected by the data layout (each reviewer's events are in their own file, on their own
machine). A hosted instance holds every reviewer's files on one server, so it enforces the rule
itself (openspec:hosted-deployment#blinding-between-users), using this module.

A reviewer is *blinded* to a record at a stage while `screening.blind_reviewers` is set (the
default), the record is assigned to them at that stage, and they have not yet decided it: exactly
their screening queue. Once they decide, or if they were never asked to screen it, there is no
independent judgement left to protect.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from strata.core.repo import Repo
from strata.protocol import screening as screening_mod


def blinding_on(repo: Repo) -> bool:
    return bool(repo.config.get("screening", {}).get("blind_reviewers", True))


def blinded_records(repo: Repo, actor: str) -> dict[str, frozenset[str]]:
    """For each stage, the records `actor` must not yet see anyone else's opinion on."""
    if not blinding_on(repo):
        return {}
    return {
        stage: frozenset(screening_mod.stage_queue(repo, stage, actor))
        for stage in screening_mod.configured_stages(repo)
    }


def is_blinded(blinded: dict[str, frozenset[str]], stage: str | None, record: str | None) -> bool:
    if record is None:
        return False
    if stage is None:
        return any(record in records for records in blinded.values())
    return record in blinded.get(stage, frozenset())


def visible(
    items: Iterable[Any],
    blinded: dict[str, frozenset[str]],
    *,
    stage: str = "stage",
    record: str = "record_id",
) -> list[Any]:
    """`items` (objects or dicts carrying a stage and a record id) without those that would tell
    a blinded reviewer someone else's opinion."""
    if not blinded:
        return list(items)

    def get(item: Any, name: str) -> Any:
        return item.get(name) if isinstance(item, dict) else getattr(item, name, None)

    return [item for item in items if not is_blinded(blinded, get(item, stage), get(item, record))]
