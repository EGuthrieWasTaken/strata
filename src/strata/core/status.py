"""`strata status`: the repository dashboard.

Per openspec:cli#the-status-dashboard: project identity, actors, commit count,
working-tree cleanliness, criteria version, record count, searches, and
(as of M2) per-stage screening counts (resolved/unscreened/partial/
conflicts/stale) plus a single "next action" recommendation. Dedup's own
pending-review count is not included here: `dedup.engine.run_dedup` has no
dry-run mode, and `status` MUST be read-only, so surfacing a live count
would mean either mutating on every `strata status` call or building a
separate preview path -- left for a future session, noted in
docs/m2-plan.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from strata import gitio
from strata.core import records as records_mod
from strata.core.canon import load_yaml_str
from strata.core.repo import Repo
from strata.protocol import rescreen as rescreen_mod
from strata.protocol import screening as screening_mod
from strata.protocol.searches import list_searches, pending_search_ids

_RESOLVED_STATUSES = frozenset({"include", "exclude"})


@dataclass
class StageStatus:
    stage: str
    total: int
    resolved: int
    unscreened: int
    partial: int
    conflicts: int
    stale: int


@dataclass
class StatusReport:
    title: str
    slug: str
    actor_count: int
    commit_count: int
    is_clean: bool
    criteria_version: int
    record_count: int
    search_count: int
    pending_searches: list[str]
    stages: list[StageStatus] = field(default_factory=list)
    next_action: str | None = None


def _count_ndjson_lines(path) -> int:  # type: ignore[no-untyped-def]
    if not path.exists():
        return 0
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


def _read_criteria_version(repo: Repo) -> int:
    path = repo.path("protocol", "criteria.yaml")
    if not path.exists():
        return 0
    data = load_yaml_str(path.read_text(encoding="utf-8"))
    if not data:
        return 0
    return int(data.get("version", 0))


def _compute_stage_status(
    repo: Repo, stage: str, canonical_ids: list[str], stale_by_record: dict[str, set[str]]
) -> StageStatus:
    events = screening_mod.all_screen_events(repo, stage)
    events_by_record: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        events_by_record.setdefault(event["body"]["record"], []).append(event)
    adjudications = screening_mod.all_adjudicate_events(repo, stage)
    adjudicate_by_record: dict[str, list[dict[str, Any]]] = {}
    for event in adjudications:
        adjudicate_by_record.setdefault(event["body"]["record"], []).append(event)
    assign_events = screening_mod.all_assign_events(repo)

    resolved = unscreened = partial = conflicts = stale = 0
    for record_id in canonical_ids:
        state = screening_mod.resolve_record_state(
            repo,
            stage,
            record_id,
            screen_events=events_by_record.get(record_id, []),
            assign_events=assign_events,
            adjudicate_events=adjudicate_by_record.get(record_id, []),
        )
        if state.status in _RESOLVED_STATUSES:
            resolved += 1
        elif state.status == "unscreened":
            unscreened += 1
        elif state.status == "partial":
            partial += 1
        elif state.status == "conflict":
            conflicts += 1
        if stage in stale_by_record.get(record_id, ()):
            stale += 1

    return StageStatus(
        stage=stage,
        total=len(canonical_ids),
        resolved=resolved,
        unscreened=unscreened,
        partial=partial,
        conflicts=conflicts,
        stale=stale,
    )


def _next_action(stages: list[StageStatus]) -> str | None:
    if any(s.conflicts for s in stages):
        return "strata adjudicate"
    if any(s.stale for s in stages):
        return "strata rescreen"
    for s in stages:
        if s.unscreened or s.partial:
            return f"strata screen {s.stage}"
    return None


def compute_status(repo: Repo) -> StatusReport:
    project = repo.config.get("project", {})
    actors = repo.config.get("actors", [])
    commits = gitio.log(repo.root)

    canonical_ids = sorted(
        r["id"]
        for r in records_mod.read_records(repo)
        if r.get("strata", {}).get("canonical", True)
    )
    stale_by_record: dict[str, set[str]] = {}
    for stale in rescreen_mod.compute_stale_records(repo):
        stale_by_record.setdefault(stale.record_id, set()).add(stale.stage)

    stages = [
        _compute_stage_status(repo, stage, canonical_ids, stale_by_record)
        for stage in screening_mod.configured_stages(repo)
    ]

    return StatusReport(
        title=project.get("title", "(untitled)"),
        slug=project.get("slug", ""),
        actor_count=len(actors),
        commit_count=len(commits),
        is_clean=not gitio.is_dirty(repo.root),
        criteria_version=_read_criteria_version(repo),
        record_count=_count_ndjson_lines(repo.path("records", "records.ndjson")),
        search_count=len(list_searches(repo)),
        pending_searches=pending_search_ids(repo),
        stages=stages,
        next_action=_next_action(stages),
    )
