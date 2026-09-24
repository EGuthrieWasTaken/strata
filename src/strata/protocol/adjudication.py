"""Adjudication: resolving screening conflicts.

Implements docs/spec/06-workflow-screening.md §8 and the `adjudicate` event
in docs/spec/02-repository-format.md §4.4.

**`criteria_version`/`criteria_digest` on the `adjudicate` event.** §4.4's
event catalog table lists `adjudicate`'s body fields as `stage, record,
decision, criteria[], rationale, supersedes[]` -- no version/digest. But
§4.1 (normative) says plainly: "Every `screen` **and `adjudicate`** event
records `criteria_version`, the set `criteria_digest`, and the specific
`criteria[]` cited. A decision is therefore always interpretable against
the exact rules in force when it was made." An adjudication is exactly the
kind of decision `docs/m2-plan.md` sub-objective 4's staleness engine needs
a stamped version for (`protocol.rescreen._resolved_decision`'s
adjudication branch already expects one). This module follows the
normative §4.1 text and stamps both fields, treating the catalog table's
omission as incomplete rather than as an exemption.
"""

from __future__ import annotations

from typing import Any, Literal

from strata.core import records as records_mod
from strata.core.events import append_new_event
from strata.core.repo import Repo
from strata.protocol import criteria as criteria_mod
from strata.protocol import screening as screening_mod

Decision = Literal["include", "exclude"]
_DECISIONS: tuple[Decision, ...] = ("include", "exclude")

_DISCUSS_SUBJECT = "adjudication-discuss"


class AdjudicationError(ValueError):
    pass


def is_adjudicator(repo: Repo, actor: str) -> bool:
    """§8: "Only actors with the `adjudicator` role or listed in
    `screening.adjudicators` may resolve a conflict.\""""
    if actor in set(repo.config.get("screening", {}).get("adjudicators", [])):
        return True
    return any(
        a.get("handle") == actor and a.get("role") in ("adjudicator", "lead")
        for a in repo.config.get("actors", [])
    )


def conflict_queue(repo: Repo, stage: str) -> list[str]:
    """Canonical record ids whose resolved state at `stage` is `conflict`."""
    if stage not in screening_mod.configured_stages(repo):
        raise AdjudicationError(
            f"unknown stage {stage!r}; configured stages are "
            f"{screening_mod.configured_stages(repo)!r}"
        )
    canonical_ids = sorted(
        r["id"]
        for r in records_mod.read_records(repo)
        if r.get("strata", {}).get("canonical", True)
    )
    all_events = screening_mod.all_screen_events(repo, stage)
    events_by_record: dict[str, list[dict[str, Any]]] = {}
    for event in all_events:
        events_by_record.setdefault(event["body"]["record"], []).append(event)
    assign_events = screening_mod.all_assign_events(repo)

    queue = []
    for record_id in canonical_ids:
        state = screening_mod.resolve_record_state(
            repo,
            stage,
            record_id,
            screen_events=events_by_record.get(record_id, []),
            assign_events=assign_events,
        )
        if state.status == "conflict":
            queue.append(record_id)
    return queue


def record_adjudication(
    repo: Repo,
    *,
    stage: str,
    record_id: str,
    decision: Decision,
    actor: str,
    rationale: str,
    cited: list[str] | None = None,
) -> dict[str, Any]:
    """Resolve one conflict: docs/spec/06 §8.

    Rationale is REQUIRED unconditionally (no `git.require_rationale`
    escape hatch, matching `cli.main._get_required_rationale`'s framing).
    Supersedes every opinion the fold currently sees for `(stage,
    record_id)` -- the adjudication event id list a future `strata why`
    can point back to the disagreement it resolved.
    """
    if not is_adjudicator(repo, actor):
        raise AdjudicationError(
            f"{actor!r} is not an adjudicator for this review "
            "(screening.adjudicators or role 'adjudicator'/'lead')"
        )
    if not rationale.strip():
        raise AdjudicationError("a rationale is required for every adjudication (docs/spec/06 §8)")
    if stage not in screening_mod.configured_stages(repo):
        raise AdjudicationError(
            f"unknown stage {stage!r}; configured stages are "
            f"{screening_mod.configured_stages(repo)!r}"
        )
    if decision not in _DECISIONS:
        raise AdjudicationError(f"decision must be one of {_DECISIONS}, got {decision!r}")
    if records_mod.get_record(repo, record_id) is None:
        raise AdjudicationError(f"no record {record_id!r}")

    cited_ids = sorted(set(cited or []))
    applicable = screening_mod.active_criteria_for_stage(repo, stage)
    for cid in cited_ids:
        if cid not in applicable:
            raise AdjudicationError(
                f"{cid!r} is not an active criterion that applies at stage {stage!r}"
            )
    if decision == "exclude" and not cited_ids and stage == "full-text":
        raise AdjudicationError(
            "an exclude decision at full-text always requires at least one cited "
            "criterion (docs/spec/06 §7)"
        )

    state = screening_mod.resolve_record_state(repo, stage, record_id)
    if state.status != "conflict":
        raise AdjudicationError(
            f"{record_id!r} at {stage!r} is not in conflict (status: {state.status!r})"
        )
    supersedes = sorted(o["id"] for o in state.opinions.values())
    own_conflict = actor in state.opinions

    doc = criteria_mod.read_criteria_doc(repo)
    body: dict[str, Any] = {
        "stage": stage,
        "record": record_id,
        "decision": decision,
        "criteria": cited_ids,
        "rationale": rationale,
        "supersedes": supersedes,
        "criteria_version": doc["version"],
        "criteria_digest": doc["digest"],
        "own_conflict": own_conflict,
    }
    return append_new_event(
        repo.path("events", "adjudication", f"{actor}.ndjson"),
        ev="adjudicate",
        actor=actor,
        body=body,
    )


def record_discussion(
    repo: Repo, *, stage: str, record_id: str, actor: str, text: str
) -> dict[str, Any]:
    """`[d]iscuss`: "records a note event and leaves the conflict open" (§8)."""
    body = {"subject": _DISCUSS_SUBJECT, "text": text, "stage": stage, "record": record_id}
    return append_new_event(
        repo.path("events", "note", f"{actor}.ndjson"), ev="note", actor=actor, body=body
    )
