"""`strata audit --criteria`: docs/spec/06-workflow-screening.md §4.3's
sampling workflow.

Re-presents a random sample of past exclusion decisions so a reviewer can
verify the cited criterion still looks correct -- the mitigation the spec
names for the miscited-criterion residual risk (§4.3: staleness alone
cannot catch a record excluded on a criterion it never actually cited,
because retiring the *wrong* criterion won't flag it). A review aid, not a
mutating command: it never appends an event itself; a correction found
during audit goes through the existing `strata fix`/`strata rescreen
--mark` paths.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from strata.core.fold import fold_last_write_wins
from strata.core.repo import Repo
from strata.protocol import screening as screening_mod


@dataclass(frozen=True)
class AuditItem:
    record_id: str
    stage: str
    actor: str
    criteria: tuple[str, ...]
    note: str | None
    ts: str


def all_exclusions(repo: Repo) -> list[AuditItem]:
    """Every actor's *current standing* exclude opinion, across all stages.

    Last-write-wins per `(stage, record, actor)` (docs/spec/02 §4.3): if a
    reviewer excluded and then changed their mind, only their current
    opinion is a live exclusion worth auditing.
    """
    items = []
    for stage in screening_mod.configured_stages(repo):
        events = screening_mod.all_screen_events(repo, stage)
        by_key = fold_last_write_wins(events, key_fn=lambda e: (e["body"]["record"], e["actor"]))
        for (record_id, actor), event in by_key.items():
            body = event["body"]
            if body["decision"] != "exclude":
                continue
            items.append(
                AuditItem(
                    record_id=record_id,
                    stage=stage,
                    actor=actor,
                    criteria=tuple(body.get("criteria") or []),
                    note=body.get("note"),
                    ts=event["ts"],
                )
            )
    return sorted(items, key=lambda item: (item.stage, item.record_id, item.actor))


def sample_exclusions(
    repo: Repo, *, sample_size: int, seed: int | None = None
) -> tuple[list[AuditItem], int]:
    """A reproducible random sample of `all_exclusions`.

    Returns `(sample, seed_used)`: a seed is generated when none is given,
    but always returned so the exact run can be reproduced later with
    `--seed`, per the CLI's "a run is reproducible on request" framing.
    Sampling `min(sample_size, len(items))` items from a list already
    sorted into a fixed order makes the result depend only on the seed, not
    on file/event iteration order.
    """
    items = all_exclusions(repo)
    resolved_seed = seed if seed is not None else random.SystemRandom().randrange(2**31)
    rng = random.Random(resolved_seed)
    sampled = rng.sample(items, min(sample_size, len(items)))
    return sampled, resolved_seed
