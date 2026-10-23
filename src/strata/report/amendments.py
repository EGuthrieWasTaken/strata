"""Protocol amendments, from `criteria-change` events (PRISMA 2020 item 24c).

Implements openspec:manuscript-generation#generated-sections (Amendments) and the amendments item
of openspec:prisma-reporting#the-checklist. Each change to the eligibility criteria after the
protocol was fixed is joined to the commit that carried it (and so to the rationale its author
gave), and its effect is measured by replaying history: which screening decisions the change
invalidated, how many were screened again, and how many of those ended excluded. The numbers come
from the log, never from memory.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from strata import gitio
from strata.core.repo import Repo
from strata.protocol import criteria as criteria_mod
from strata.protocol import rescreen as rescreen_mod
from strata.protocol import screening as screening_mod

_DIRECTION_WORDS = {
    "tightened": "tightened",
    "loosened": "loosened",
    "both": "both tightened and loosened",
    "editorial": "reworded without changing its meaning",
}


@dataclass
class Amendment:
    ts: str
    actor: str
    from_version: int
    to_version: int
    deltas: list[dict[str, Any]]
    rationale: str
    commit: str | None = None
    invalidated: int = 0
    rescreened: int = 0
    still_stale: int = 0
    now_excluded: int = 0
    now_included: int = 0
    stages: dict[str, int] = field(default_factory=dict)

    @property
    def date(self) -> str:
        return self.ts[:10]


def _resolved_now(repo: Repo, stage: str, record_ids: list[str]) -> dict[str, str]:
    states = screening_mod.stage_states(repo, stage, record_ids)
    return {r: s.status for r, s in states.items()}


def _order(event: dict[str, Any]) -> tuple[str, str]:
    """`(ts, id)`, the order the fold uses: `ts` has second precision, and the ULID `id` still
    orders two events made in the same second."""
    return event["ts"], event["id"]


def _first_decision(repo: Repo) -> tuple[str, str] | None:
    """Where the first screening decision, at any stage, falls in the order of events."""
    keys = [
        _order(e)
        for stage in screening_mod.configured_stages(repo)
        for e in screening_mod.all_screen_events(repo, stage)
    ]
    return min(keys) if keys else None


def amendments(repo: Repo) -> list[Amendment]:
    """Every change to the criteria made after screening began, oldest first."""
    events = criteria_mod.all_criteria_change_events(repo)
    started = _first_decision(repo)
    stale_now = {(s.record_id, s.stage) for s in rescreen_mod.compute_stale_records(repo)}
    found: list[Amendment] = []
    for event in events:
        body = event["body"]
        to_version, from_version = int(body["to_version"]), int(body["from_version"])
        # Setting the criteria up before anyone screens is writing the protocol, not amending it.
        if started is None or _order(event) <= started:
            continue
        after = {
            (s.record_id, s.stage)
            for s in rescreen_mod.stale_records_as_of(repo, before=event, version=to_version)
        }
        before = {
            (s.record_id, s.stage)
            for s in rescreen_mod.stale_records_as_of(repo, before=event, version=from_version)
        }
        invalidated = sorted(after - before)
        amendment = Amendment(
            ts=event["ts"],
            actor=event["actor"],
            from_version=from_version,
            to_version=to_version,
            deltas=list(body["deltas"]),
            rationale=str(body.get("rationale") or "").strip(),
            invalidated=len(invalidated),
        )
        for _record, stage in invalidated:
            amendment.stages[stage] = amendment.stages.get(stage, 0) + 1
        by_stage: dict[str, list[str]] = {}
        for record_id, stage in invalidated:
            by_stage.setdefault(stage, []).append(record_id)
        for stage, record_ids in by_stage.items():
            statuses = _resolved_now(repo, stage, record_ids)
            for record_id in record_ids:
                if (record_id, stage) in stale_now:
                    amendment.still_stale += 1
                else:
                    amendment.rescreened += 1
                    status = statuses.get(record_id)
                    amendment.now_excluded += status == "exclude"
                    amendment.now_included += status == "include"
        commits = gitio.commits_adding(repo.root, str(event["id"]), ["events/criteria"])
        amendment.commit = commits[0] if commits else None
        found.append(amendment)
    return found


def _criterion_phrase(delta: dict[str, Any]) -> str:
    kind = str(delta["kind"])
    label = str(delta["label"])
    cid = str(delta["id"])
    if delta["origin"] == "added":
        return f"the {kind} criterion {cid} ({label}) was added"
    if delta["origin"] == "retired":
        return f"the {kind} criterion {cid} ({label}) was retired"
    return (
        f"the {kind} criterion {cid} ({label}) was edited, a change that "
        f"{_DIRECTION_WORDS.get(str(delta['direction']), str(delta['direction']))} it"
    )


def _join(parts: list[str]) -> str:
    if len(parts) <= 1:
        return "".join(parts)
    return ", ".join(parts[:-1]) + " and " + parts[-1]


def paragraph(amendment: Amendment) -> str:
    """One amendment as prose: the date, the criterion, what it invalidated, around the author's
    own rationale."""
    what = _join([_criterion_phrase(d) for d in amendment.deltas])
    text = (
        f"On {amendment.date}, {what} (criteria version {amendment.from_version} to "
        f"{amendment.to_version}, by {amendment.actor})."
    )
    if amendment.rationale:
        text += f' The stated rationale was: "{amendment.rationale}"'
    if amendment.invalidated:
        text += (
            f" The change made {amendment.invalidated} screening decision(s) stale; "
            f"{amendment.rescreened} have been screened again, of which {amendment.now_excluded} "
            f"ended excluded and {amendment.now_included} included"
        )
        if amendment.still_stale:
            text += f", and {amendment.still_stale} still await re-screening"
        text += "."
    else:
        text += " No screening decision was invalidated by it."
    if amendment.commit:
        text += f" (commit {amendment.commit[:10]})"
    return text


def text(repo: Repo) -> str:
    """The amendments section: a paragraph per change, or the statement that there were none."""
    found = amendments(repo)
    if not found:
        return "The eligibility criteria were not amended after screening began.\n"
    return "\n\n".join(paragraph(a) for a in found) + "\n"
