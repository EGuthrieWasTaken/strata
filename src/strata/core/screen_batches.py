"""Screening decisions are written at once and committed in batches, one batch per reviewer.

`openspec:git-integration#batched-screening-commits`: a decision is appended to its event file the
moment it is made (and fsynced), but the commit comes later. Between the two the decision is on
disk and uncommitted, in a file that belongs to its reviewer
(`events/screen/<stage>.<actor>.ndjson`).

Anything else that commits in that window must not take the decision along. A commit for an
adjudication, an import or a criteria change stages `events/` and `derived/`, so it would carry
another reviewer's screening file into a commit that names someone else as its author and an
unrelated operation as its subject, and the history would then say the wrong person did the wrong
thing. So each reviewer's pending decisions are committed first, as a batch of their own, under
their own identity; `flush_pending_screening` does that, and every place that commits calls it.

Done at the start of an operation (the web layer does, for every non-screening request) the batch
commit is complete before the operation writes anything. Done at the point of committing (the safety
net in `commit_domain_work` and the other commit sites), it still keeps attribution right, but the
batch's derived views were regenerated from everything on disk, so for that one commit they also
reflect the operation's own not-yet-committed events.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable, Collection, Iterator, Mapping
from contextlib import contextmanager, nullcontext
from contextvars import ContextVar

from strata import gitio
from strata.core.commit import StructuredCommit, fit_subject
from strata.core.repo import Repo
from strata.protocol import pool as pool_mod

SCREEN_DIR = "events/screen"
BROWSER_BODY = "Screening decisions recorded in the browser."

#: Where a batch's git identity comes from. A hosted instance sets it for the length of a
#: request, so a reviewer's batch is committed as that reviewer whoever's operation flushes it.
_IDENTITY: ContextVar[Callable[[str], Mapping[str, str]] | None] = ContextVar(
    "strata_screening_batch_identity", default=None
)


@contextmanager
def batch_identities(resolver: Callable[[str], Mapping[str, str]]) -> Iterator[None]:
    """Within this block, commit each reviewer's batch under the git environment
    `resolver(handle)`."""
    token = _IDENTITY.set(resolver)
    try:
        yield
    finally:
        _IDENTITY.reset(token)


def _actor_of(filename: str) -> str | None:
    """`title-abstract.sam.ndjson` -> `sam`."""
    stem = filename.removesuffix(".ndjson")
    if stem == filename or "." not in stem:
        return None
    return stem.rsplit(".", 1)[1]


def pending_screening_files(repo: Repo) -> dict[str, list[str]]:
    """Each reviewer's screening files with changes git has not committed (modified, staged or new),
    as paths relative to the repository."""
    result = gitio.run(
        ["status", "--porcelain", "-z", "--untracked-files=all", "--", SCREEN_DIR], cwd=repo.root
    )
    found: dict[str, list[str]] = {}
    for entry in result.stdout.split("\0"):
        if len(entry) < 4:
            continue
        relative = entry[3:]
        actor = _actor_of(relative.rsplit("/", 1)[-1])
        if actor is not None and relative.startswith(f"{SCREEN_DIR}/"):
            found.setdefault(actor, []).append(relative)
    return {actor: sorted(paths) for actor, paths in sorted(found.items())}


def pending_screening_actors(repo: Repo) -> list[str]:
    """The reviewers who have screening decisions that are not committed yet."""
    return list(pending_screening_files(repo))


def _event_ids(text: str) -> set[str]:
    ids = set()
    for line in text.splitlines():
        try:
            ids.add(str(json.loads(line)["id"]))
        except (ValueError, KeyError, TypeError):
            continue
    return ids


def commit_screening_batch(repo: Repo, actor: str, *, body: str = BROWSER_BODY) -> bool:
    """Commit `actor`'s uncommitted screening decisions as one batch with a generated summary
    (openspec:git-integration#batched-screening-commits); whether there was anything to commit.

    Only that actor's screening files are committed, with the derived views they move, so two
    reviewers' batches never share a commit.
    """
    changed = pending_screening_files(repo).get(actor, [])
    if not changed:
        return False
    decisions: Counter[str] = Counter()
    stages: set[str] = set()
    for relative in changed:
        before = gitio.run(["show", f"HEAD:{relative}"], cwd=repo.root, check=False)
        known = _event_ids(before.stdout) if before.returncode == 0 else set()
        for line in repo.path(*relative.split("/")).read_text(encoding="utf-8").splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if str(event.get("id")) in known or event.get("ev") != "screen":
                continue
            event_body = event.get("body", {})
            decisions[str(event_body.get("decision"))] += 1
            stages.add(str(event_body.get("stage")))
    total = sum(decisions.values())
    breakdown = ", ".join(f"{n} {decision}" for decision, n in sorted(decisions.items()))
    summary = f"screen {total} record{'s' if total != 1 else ''}" + (
        f" ({breakdown})" if breakdown else ""
    )
    scope = next(iter(stages)) if len(stages) == 1 else None
    pool_mod.regenerate_all(repo)
    fitted_scope, fitted_summary = fit_subject("screen", scope, summary)
    trailers = {"Op": "screen", "Actor": actor}
    if scope is not None:
        trailers["Stage"] = scope
    message = StructuredCommit(
        op="screen",
        scope=fitted_scope,
        summary=fitted_summary,
        body=body,
        trailers=trailers,
    ).message()
    gitio.add(repo.root, [*changed, "derived"])
    gitio.commit(repo.root, message)
    return True


def flush_pending_screening(
    repo: Repo, *, except_actors: Collection[str] = (), body: str = BROWSER_BODY
) -> int:
    """Commit every reviewer's pending screening decisions, each as a batch of their own under their
    own identity; how many commits that made. `except_actors` are left alone (a screening commit
    for them is the thing being made).

    Does not take the repository lock: it is called from inside operations that already hold it
    (the lock is the operating system's and is not reentrant), and by callers that take it first.
    """
    resolver = _IDENTITY.get()
    made = 0
    for actor in pending_screening_actors(repo):
        if actor in except_actors:
            continue
        with gitio.environment(resolver(actor)) if resolver else nullcontext():
            if commit_screening_batch(repo, actor, body=body):
                made += 1
    return made
