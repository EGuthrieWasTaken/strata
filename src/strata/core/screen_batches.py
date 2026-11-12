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

When a batch is committed (`BatchTracker` keeps the count and the clock for a server): when the
reviewer ends the session, at the `BATCH_SIZE`th decision, after `BATCH_IDLE` seconds without one,
and before anything else commits. A routine batch gets a generated message and asks for nothing. A
decision that changes the reviewer's own earlier one carries its reason in the event's note (the
screens require one), and the batch's message lists each such change with its reason, so the
rationale the requirement asks for is in the log and in the history without a prompt at commit
time, which a timer or a shutdown could not answer.

Done at the start of an operation (the web layer does, for every non-screening request) the batch
commit is complete before the operation writes anything. Done at the point of committing (the safety
net in `commit_domain_work` and the other commit sites), it still keeps attribution right, but the
batch's derived views were regenerated from everything on disk, so for that one commit they also
reflect the operation's own not-yet-committed events.
"""

from __future__ import annotations

import json
import threading
import time
from collections import Counter
from collections.abc import Callable, Collection, Iterator, Mapping
from contextlib import contextmanager, nullcontext
from contextvars import ContextVar
from dataclasses import dataclass

from strata import gitio
from strata.core.commit import StructuredCommit, fit_subject
from strata.core.repo import LockTimeoutError, Repo, repo_lock
from strata.protocol import pool as pool_mod

SCREEN_DIR = "events/screen"
BROWSER_BODY = "Screening decisions recorded in the browser."
RECOVERED_BODY = "Screening decisions an earlier session recorded and did not commit."
#: openspec:git-integration#batched-screening-commits: a batch is committed at this many decisions,
BATCH_SIZE = 200
#: or after this many seconds without one.
BATCH_IDLE = 15 * 60.0
NO_REASON = "no reason was recorded"

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


@dataclass(frozen=True)
class ChangedDecision:
    """A decision that differs from the same reviewer's earlier one for the record at the stage."""

    stage: str
    record: str
    before: str
    after: str
    reason: str | None

    def line(self) -> str:
        return (
            f"- {self.record} at {self.stage}: {self.before} -> {self.after}. "
            f"Why: {self.reason or NO_REASON}"
        )


def batch_summary(decisions: Mapping[str, int], *, verb: str = "screen") -> str:
    """`screen 200 records (183 exclude, 17 include)`: the generated subject of a batch, the same
    whether the command line or the browser recorded it."""
    total = sum(decisions.values())
    breakdown = ", ".join(f"{n} {decision}" for decision, n in sorted(decisions.items()) if n)
    return f"{verb} {total} record{'s' if total != 1 else ''}" + (
        f" ({breakdown})" if breakdown else ""
    )


def own_decision(repo: Repo, *, stage: str, record_id: str, actor: str) -> dict[str, object] | None:
    """The body of the reviewer's own current decision for the record at the stage, if any."""
    path = repo.path(*SCREEN_DIR.split("/"), f"{stage}.{actor}.ndjson")
    if not path.exists():
        return None
    found: dict[str, object] | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        body = event.get("body") or {}
        if event.get("ev") == "screen" and body.get("record") == record_id:
            found = body
    return found


def changed_decision(
    repo: Repo, *, stage: str, record_id: str, actor: str, decision: str
) -> str | None:
    """The reviewer's own current decision for the record at the stage if `decision` would change
    it, else `None` (nothing decided yet, or the same decision again)."""
    body = own_decision(repo, stage=stage, record_id=record_id, actor=actor)
    before = str(body.get("decision")) if body is not None else None
    return before if before is not None and before != decision else None


def _read_batch(
    repo: Repo, changed: list[str]
) -> tuple[Counter[str], set[str], list[ChangedDecision]]:
    """What the uncommitted events in `changed` (one reviewer's screening files) decide: how many
    of each decision, at which stages, and which of them change the reviewer's earlier decision."""
    decisions: Counter[str] = Counter()
    stages: set[str] = set()
    changes: list[ChangedDecision] = []
    for relative in changed:
        before = gitio.run(["show", f"HEAD:{relative}"], cwd=repo.root, check=False)
        known = _event_ids(before.stdout) if before.returncode == 0 else set()
        standing: dict[tuple[str, str], str] = {}
        for line in repo.path(*relative.split("/")).read_text(encoding="utf-8").splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if event.get("ev") != "screen":
                continue
            event_body = event.get("body", {})
            decision = str(event_body.get("decision"))
            key = (str(event_body.get("stage")), str(event_body.get("record")))
            earlier = standing.get(key)
            standing[key] = decision
            if str(event.get("id")) in known:
                continue
            decisions[decision] += 1
            stages.add(key[0])
            if earlier is not None and earlier != decision:
                note = str(event_body.get("note") or "").strip() or None
                changes.append(ChangedDecision(key[0], key[1], earlier, decision, note))
    return decisions, stages, changes


def pending_changes(repo: Repo, actor: str) -> list[ChangedDecision]:
    """The changes of mind among `actor`'s uncommitted screening decisions."""
    return _read_batch(repo, pending_screening_files(repo).get(actor, []))[2]


def commit_screening_batch(repo: Repo, actor: str, *, body: str = BROWSER_BODY) -> bool:
    """Commit `actor`'s uncommitted screening decisions as one batch with a generated summary
    (openspec:git-integration#batched-screening-commits); whether there was anything to commit.

    Only that actor's screening files are committed, with the derived views they move, so two
    reviewers' batches never share a commit. Decisions that change the reviewer's earlier ones are
    listed in the message, each with the reason recorded with it.
    """
    changed = pending_screening_files(repo).get(actor, [])
    if not changed:
        return False
    decisions, stages, changes = _read_batch(repo, changed)
    summary = batch_summary(decisions)
    if changes:
        listed = "\n".join(change.line() for change in changes)
        body = f"{body}\n\nChanged decisions:\n{listed}"
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


def flush_under_lock(repo: Repo, *, body: str = BROWSER_BODY) -> int:
    """`flush_pending_screening` for a caller outside any operation (the web layer, the command
    line's pre-flight): under the repository lock, and only when something is pending.

    The lock is taken only then so that an idle repository's lock is never touched: taking it
    "reclaims" a dead process's lock, and the operation that follows is the one that should say so.
    If another process holds the lock for the whole timeout, skip: whatever commits next flushes
    them itself, under the lock it holds.
    """
    if not pending_screening_actors(repo):
        return 0
    try:
        with repo_lock(repo):
            return flush_pending_screening(repo, body=body)
    except LockTimeoutError:
        return 0


class BatchTracker:
    """When a server's screening batches are due: a count and a last-decision time per reviewer.

    It holds no decision. Those are in the event files the moment they are made, and what is
    committed is whatever git says is uncommitted, so a tracker that is lost (a restart) or wrong
    costs nothing but the timing of a commit. `clock` is injectable for the tests.
    """

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        size: int = BATCH_SIZE,
        idle: float = BATCH_IDLE,
    ) -> None:
        self._clock = clock
        self.size = size
        self.idle = idle
        self._guard = threading.Lock()
        self._pending: dict[str, tuple[int, float]] = {}
        self._reasons: dict[tuple[str, str], str] = {}

    def note(self, actor: str, decisions: int = 1) -> bool:
        """`actor` recorded a decision; whether their batch has reached its size."""
        with self._guard:
            count = self._pending.get(actor, (0, 0.0))[0] + decisions
            self._pending[actor] = (count, self._clock())
            return count >= self.size

    def pending(self, actor: str | None = None) -> int:
        with self._guard:
            if actor is not None:
                return self._pending.get(actor, (0, 0.0))[0]
            return sum(count for count, _last in self._pending.values())

    def idle_actors(self) -> list[str]:
        """Reviewers whose last decision was at least `idle` seconds ago."""
        now = self._clock()
        with self._guard:
            return sorted(a for a, (_n, last) in self._pending.items() if now - last >= self.idle)

    def clear(self, actor: str | None = None) -> None:
        with self._guard:
            if actor is None:
                self._pending.clear()
            else:
                self._pending.pop(actor, None)

    # The reason a reviewer last gave for changing a decision at a stage, offered again on the
    # next stale record: one criterion change usually turns many decisions for the same reason.
    def remember_reason(self, actor: str, stage: str, reason: str) -> None:
        with self._guard:
            self._reasons[(actor, stage)] = reason

    def last_reason(self, actor: str, stage: str) -> str:
        with self._guard:
            return self._reasons.get((actor, stage), "")
