"""Staleness computation: openspec:staleness#the-staleness-rules and
openspec:staleness#staleness-causes.

Pure module, no I/O, no repository knowledge — one of the five
100%-branch-coverage modules named in openspec:test-suite#test-levels-and-coverage-floors. This is
the module the whole project's credibility rests on: "if the staleness
engine does not work and does not feel trustworthy, the project has no
reason to exist" (docs/roadmap.md).

This module answers exactly one question: given one resolved screening
decision and the criterion changes that have happened since it was made,
is it stale, and why? It deliberately does not know about cross-stage
cascading (`upstream-stale`,
openspec:staleness#staleness-cascades-across-stages-without-deleting-work) or manual
invalidation (`manual`, openspec:staleness#staleness-causes) — those need context (a record's
*other* stage decisions, or an
explicit user action) a pure per-decision function cannot have on its own.
The caller (docs/m2-plan.md sub-objective 4) layers those on.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

Decision = Literal["include", "exclude", "maybe"]
Direction = Literal["tightened", "loosened", "both", "editorial"]
Origin = Literal["added", "edited", "retired"]
Reason = Literal[
    "criterion-added",
    "criterion-tightened",
    "criterion-loosened",
    "criterion-retired",
    "criterion-both",
    "maybe-any-change",
]

_EFFECTIVE_DIRECTION_INCLUDE = frozenset({"tightened", "both"})
_EFFECTIVE_DIRECTION_EXCLUDE = frozenset({"loosened", "both"})


@dataclass(frozen=True)
class CriterionChange:
    """One criterion's state transition, as of one version bump.

    `origin`/`direction` follow openspec:criteria-management#declaring-the-direction-of-a-change: a
    criterion **added** behaves as `tightened`; a criterion **retired**
    behaves as `loosened`; an **edited** criterion carries whatever
    direction the user classified the edit as (including `editorial`,
    which `effective_direction` leaves as-is since it invalidates nothing).
    """

    criterion_id: str
    origin: Origin
    direction: Direction
    to_version: int
    applies_at: frozenset[str]

    @property
    def effective_direction(self) -> Direction:
        if self.origin == "added":
            return "tightened"
        if self.origin == "retired":
            return "loosened"
        return self.direction


@dataclass(frozen=True)
class StaleInfo:
    stale: bool
    reason: Reason | None = None
    causes: frozenset[str] = field(default_factory=frozenset)


def relevant_changes(
    changes: Sequence[CriterionChange],
    *,
    decision_version: int,
    current_version: int,
    stage: str,
) -> list[CriterionChange]:
    """`Δ(v_D, v_now, stage)`: changes strictly after `decision_version`, at or
    before `current_version`, that apply at `stage` (openspec:staleness#the-staleness-rules)."""
    return [
        c
        for c in changes
        if decision_version < c.to_version <= current_version and stage in c.applies_at
    ]


def evaluate_staleness(
    *,
    decision: Decision,
    cited: frozenset[str],
    decision_version: int,
    current_version: int,
    stage: str,
    changes: Sequence[CriterionChange],
) -> StaleInfo:
    """openspec:staleness#the-staleness-rules's three-clause rule, plus
    openspec:staleness#staleness-causes's
    reason labels:

    ```
    D is STALE if and only if:
      D.decision == "include"  and  ∃ c ∈ Δ with direction ∈ {tightened, both}
      D.decision == "exclude"  and  ∃ c ∈ Δ ∩ C_D with direction ∈ {loosened, both, retired}
      D.decision == "maybe"    and  Δ ≠ ∅ (any non-editorial change)
    ```

    When more than one criterion change would independently make a decision
    stale, `criterion-both` takes priority (it is the most conservative,
    most informative label to surface), then the origin-specific reason
    (`criterion-added`/`criterion-retired`), then the generic direction
    reason (`criterion-tightened`/`criterion-loosened`) — the spec's
    openspec:staleness#staleness-causes
    table does not itself rank overlapping causes, so this ordering is this
    implementation's own deterministic tie-break, documented here rather
    than left implicit.
    """
    delta = relevant_changes(
        changes, decision_version=decision_version, current_version=current_version, stage=stage
    )
    if not delta:
        return StaleInfo(stale=False)

    if decision == "include":
        causing = [c for c in delta if c.effective_direction in _EFFECTIVE_DIRECTION_INCLUDE]
        if not causing:
            return StaleInfo(stale=False)
        if any(c.effective_direction == "both" for c in causing):
            reason: Reason = "criterion-both"
        elif any(c.origin == "added" for c in causing):
            reason = "criterion-added"
        else:
            reason = "criterion-tightened"
        return StaleInfo(
            stale=True, reason=reason, causes=frozenset(c.criterion_id for c in causing)
        )

    if decision == "exclude":
        causing = [
            c
            for c in delta
            if c.criterion_id in cited and c.effective_direction in _EFFECTIVE_DIRECTION_EXCLUDE
        ]
        if not causing:
            return StaleInfo(stale=False)
        if any(c.effective_direction == "both" for c in causing):
            reason = "criterion-both"
        elif any(c.origin == "retired" for c in causing):
            reason = "criterion-retired"
        else:
            reason = "criterion-loosened"
        return StaleInfo(
            stale=True, reason=reason, causes=frozenset(c.criterion_id for c in causing)
        )

    # decision == "maybe": any non-editorial change, cited or not
    # (openspec:staleness#the-staleness-rules).
    causing = [c for c in delta if c.effective_direction != "editorial"]
    if not causing:
        return StaleInfo(stale=False)
    return StaleInfo(
        stale=True,
        reason="maybe-any-change",
        causes=frozenset(c.criterion_id for c in causing),
    )
