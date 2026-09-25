"""Inter-rater reliability: docs/spec/02-repository-format.md §6.5.

Computed over *independent first opinions only* — an opinion changed after
seeing another reviewer's decision would no longer be independent
(docs/spec/06 §2's blinding requirement exists precisely so first opinions
are trustworthy), which is why this uses `core.fold.fold_first_write`, not
the last-write-wins fold everything else in this codebase uses.

**Binary only.** The 2x2 table and PABAK are binary-classification tools by
definition; a pair comparison here only counts records where *both*
reviewers' first opinion at that stage was a completed decision
(`include`/`exclude`). A `maybe` first opinion is excluded from the
computation (there is no natural three-category form of a 2x2 table or
PABAK) but the exclusion count is reported alongside `n` so the numbers are
auditable rather than silently smaller than a reviewer would expect.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import Any

from strata.core.canon import canonical_json
from strata.core.fold import fold_first_write
from strata.core.repo import Repo
from strata.protocol import screening as screening_mod

_BINARY = frozenset({"include", "exclude"})
_ROUND_DP = 6


class IrrError(ValueError):
    pass


@dataclass(frozen=True)
class PairIrr:
    stage: str
    actor_a: str
    actor_b: str
    n: int
    excluded_maybe: int
    table: dict[str, int] = field(default_factory=dict)
    raw_agreement: float = 0.0
    kappa: float = 0.0
    pabak: float = 0.0


def _first_opinions_by_actor(repo: Repo, stage: str) -> dict[str, dict[str, dict[str, Any]]]:
    """`actor -> record_id -> first screen event` at `stage`."""
    events = screening_mod.all_screen_events(repo, stage)
    by_actor: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        by_actor.setdefault(event["actor"], []).append(event)
    return {
        actor: fold_first_write(actor_events, key_fn=lambda e: e["body"]["record"])
        for actor, actor_events in by_actor.items()
    }


def _kappa_stats(a: int, b: int, c: int, d: int) -> tuple[float, float, float]:
    """`(raw_agreement, kappa, pabak)` for a 2x2 table `[[a, b], [c, d]]`.

    `a`/`d` are the agreement cells; `b`/`c` are the disagreement cells.
    PABAK (Byrt, Bishop & Carlin 1993) = `2 * raw_agreement - 1`, immune to
    Cohen's kappa's paradoxical collapse under skewed prevalence.
    """
    n = a + b + c + d
    if n == 0:
        return 0.0, 0.0, 0.0
    po = (a + d) / n
    pe = ((a + b) / n) * ((a + c) / n) + ((c + d) / n) * ((b + d) / n)
    kappa = 1.0 if pe >= 1.0 else (po - pe) / (1 - pe)
    pabak = 2 * po - 1
    return po, kappa, pabak


def compute_pair_irr(repo: Repo, stage: str, actor_a: str, actor_b: str) -> PairIrr:
    first = _first_opinions_by_actor(repo, stage)
    a_opinions = first.get(actor_a, {})
    b_opinions = first.get(actor_b, {})
    common_ids = sorted(set(a_opinions) & set(b_opinions))

    both_include = a_include_b_exclude = a_exclude_b_include = both_exclude = 0
    excluded_maybe = 0
    for record_id in common_ids:
        decision_a = a_opinions[record_id]["body"]["decision"]
        decision_b = b_opinions[record_id]["body"]["decision"]
        if decision_a not in _BINARY or decision_b not in _BINARY:
            excluded_maybe += 1
        elif decision_a == "include" and decision_b == "include":
            both_include += 1
        elif decision_a == "include" and decision_b == "exclude":
            a_include_b_exclude += 1
        elif decision_a == "exclude" and decision_b == "include":
            a_exclude_b_include += 1
        else:
            both_exclude += 1

    raw_agreement, kappa, pabak = _kappa_stats(
        both_include, a_include_b_exclude, a_exclude_b_include, both_exclude
    )
    n = both_include + a_include_b_exclude + a_exclude_b_include + both_exclude
    return PairIrr(
        stage=stage,
        actor_a=actor_a,
        actor_b=actor_b,
        n=n,
        excluded_maybe=excluded_maybe,
        table={
            "both_include": both_include,
            "a_include_b_exclude": a_include_b_exclude,
            "a_exclude_b_include": a_exclude_b_include,
            "both_exclude": both_exclude,
        },
        raw_agreement=round(raw_agreement, _ROUND_DP),
        kappa=round(kappa, _ROUND_DP),
        pabak=round(pabak, _ROUND_DP),
    )


def compute_stage_irr(repo: Repo, stage: str) -> list[PairIrr]:
    """Every reviewer pair with at least one first opinion each at `stage`,
    sorted by `(actor_a, actor_b)`."""
    if stage not in screening_mod.configured_stages(repo):
        raise IrrError(
            f"unknown stage {stage!r}; configured stages are "
            f"{screening_mod.configured_stages(repo)!r}"
        )
    actors = sorted(_first_opinions_by_actor(repo, stage).keys())
    return [
        compute_pair_irr(repo, stage, actor_a, actor_b)
        for actor_a, actor_b in itertools.combinations(actors, 2)
    ]


def regenerate_irr_json(repo: Repo) -> str:
    """Regenerate `derived/irr.json` (docs/spec/02-repository-format.md §6.5)."""
    payload: dict[str, list[dict[str, Any]]] = {}
    for stage in screening_mod.configured_stages(repo):
        payload[stage] = [
            {
                "actor_a": pair.actor_a,
                "actor_b": pair.actor_b,
                "n": pair.n,
                "excluded_maybe": pair.excluded_maybe,
                "table": pair.table,
                "raw_agreement": pair.raw_agreement,
                "kappa": pair.kappa,
                "pabak": pair.pabak,
            }
            for pair in compute_stage_irr(repo, stage)
        ]
    text = canonical_json(payload) + "\n"
    path = repo.path("derived", "irr.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return text
