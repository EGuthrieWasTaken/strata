"""The hosted sync loop: openspec:hosted-deployment#automatic-git-sync-loop.

Every project with a remote is kept in step with it by running `strata sync`'s own algorithm
(`strata.core.sync.sync`), so union-merged event files, regenerated derived views, verification
and the domain-terms conflict report are exactly what a local collaborator gets
(openspec:hosted-deployment#hosted-and-local-collaborators-interoperate):

- **Pull before read.** Before a page that reads the repository is served, the project is synced
  if its last fetch is older than `sync.interval_seconds` (30 s by default). This makes one
  attempt only: a page never waits out a retry schedule, and if the remote cannot be reached the
  page is served from the instance's copy and says so.
- **Push after commit.** Every commit the instance makes for a member marks the project as having
  work to push, and the background worker pushes it (fetching and merging first, as `strata sync`
  does). A failed push is retried with exponential backoff, 30 s doubling to at most 15 minutes,
  for as long as it keeps failing; the dashboard shows the failure, and nothing is lost because
  the commits stay in the instance's working copy.
- **Screening batches.** Screening decisions are appended (and fsynced) at once but committed in
  batches, per actor (openspec:git-integration#batched-screening-commits): when 200 decisions
  accumulate, after 15 minutes without a decision, when the member signs out, and before any sync,
  because a sync needs a clean tree.
- **Conflicts.** A genuine conflict in a human-authored file (two different edits to `EXC-03`,
  say) stops the sync where `strata sync` would stop: the instance's copy is left exactly as it
  was, pushes for that project stop, and the conflict is held, in domain terms (mine, theirs, and
  a summary), for a member with the lead role to resolve by keeping the instance's version,
  keeping the remote's, or writing the text themselves. Nothing is resolved silently or dropped.

Each project's syncs are serialised by a lock of their own and run under the repository lock
(openspec:architecture#concurrency-and-locking), so a sync never interleaves with a member's
operation. Commits the loop makes have the acting reviewer as author and the instance as committer
(openspec:hosted-deployment#commit-attribution).
"""

from __future__ import annotations

import json
import threading
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from strata import gitio
from strata.core import sync as sync_mod
from strata.core.commit import StructuredCommit, fit_subject
from strata.core.repo import LockTimeoutError, Repo, repo_lock
from strata.hosted.instance import Instance, Project
from strata.hosted.secrets import SecretError
from strata.protocol import pool as pool_mod

BATCH_SIZE = 200
BATCH_IDLE = 15 * 60.0
RETRY_BASE = 30.0
RETRY_CAP = 15 * 60.0


@dataclass(frozen=True)
class SyncStatus:
    project: str
    remote: str | None
    last_fetch: float | None = None
    last_success: float | None = None
    last_push: float | None = None
    last_error: str | None = None
    failures: int = 0
    next_retry: float | None = None
    push_pending: bool = False
    conflicts: list[dict[str, Any]] = field(default_factory=list)
    pending_decisions: int = 0

    @property
    def blocked(self) -> bool:
        return bool(self.conflicts)

    def as_view(self) -> dict[str, Any]:
        """What a page shows about the project's sync (never a credential)."""
        return {
            "remote": self.remote,
            "last_success": _iso(self.last_success),
            "last_push": _iso(self.last_push),
            "last_error": self.last_error,
            "push_pending": self.push_pending,
            "failures": self.failures,
            "next_retry": _iso(self.next_retry),
            "conflicts": len(self.conflicts),
            "pending_decisions": self.pending_decisions,
        }


def _iso(ts: float | None) -> str | None:
    if ts is None:
        return None
    return time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(ts))


def actor_identity(repo: Repo, handle: str) -> tuple[str, str]:
    """`handle`'s name and email from `strata.toml`, as git records them."""
    for actor in repo.config.get("actors", []):
        if actor.get("handle") == handle:
            return str(actor.get("name") or handle), str(
                actor.get("email") or f"{handle}@users.noreply.local"
            )
    return handle, f"{handle}@users.noreply.local"


def identity_for(instance: Instance, repo: Repo, handle: str) -> dict[str, str]:
    """The git environment that makes `handle` the author and the instance the committer."""
    return gitio.identity_env(
        author=actor_identity(repo, handle), committer=instance.settings.committer
    )


class SyncLoop:
    """The sync loop for every project of one instance."""

    def __init__(
        self,
        instance: Instance,
        *,
        clock: Callable[[], float] = time.time,
        on_change: Callable[[], None] | None = None,
    ) -> None:
        self.instance = instance
        self._clock = clock
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()
        self._on_change = on_change

    # -- state -----------------------------------------------------------------------------

    def _lock(self, project_id: str) -> threading.Lock:
        with self._locks_guard:
            return self._locks.setdefault(project_id, threading.Lock())

    def status(self, project_id: str) -> SyncStatus:
        project = self.instance.get_project(project_id)
        row = self.instance.store.one("SELECT * FROM sync_status WHERE project = ?", (project_id,))
        pending = self.instance.store.one(
            "SELECT COALESCE(SUM(pending), 0) AS n FROM screening_batches WHERE project = ?",
            (project_id,),
        )
        remote = project.remote if project is not None else None
        if row is None:
            return SyncStatus(project_id, remote, pending_decisions=_count(pending))
        return SyncStatus(
            project=project_id,
            remote=remote,
            last_fetch=row["last_fetch"],
            last_success=row["last_success"],
            last_push=row["last_push"],
            last_error=row["last_error"],
            failures=row["failures"],
            next_retry=row["next_retry"],
            push_pending=bool(row["push_pending"]),
            conflicts=json.loads(row["conflicts"]) if row["conflicts"] else [],
            pending_decisions=_count(pending),
        )

    def _update(self, project_id: str, **values: Any) -> None:
        columns = ", ".join(f"{name} = ?" for name in values)
        with self.instance.store.connect() as db:
            db.execute("INSERT OR IGNORE INTO sync_status (project) VALUES (?)", (project_id,))
            db.execute(
                f"UPDATE sync_status SET {columns} WHERE project = ?",  # noqa: S608
                (*values.values(), project_id),
            )

    # -- what members did ------------------------------------------------------------------

    def note_commit(self, project_id: str, actor: str) -> None:
        """The instance committed for `actor`: push it (now, and with backoff if that fails)."""
        project = self.instance.get_project(project_id)
        if project is None or project.remote is None:
            return
        values: dict[str, Any] = {"push_pending": 1, "pending_actor": actor}
        if self.status(project_id).failures == 0:
            values["next_retry"] = None  # push now; after a failure, the backoff stands
        self._update(project_id, **values)
        if self._on_change is not None:
            self._on_change()

    def note_screening(self, project_id: str, actor: str, decisions: int = 1) -> bool:
        """`actor` recorded screening decisions that are not yet committed; commits the batch when
        it reaches `BATCH_SIZE`. Whether it committed."""
        now = self._clock()
        with self.instance.store.connect() as db:
            db.execute(
                "INSERT INTO screening_batches (project, actor, pending, first, last) "
                "VALUES (?, ?, ?, ?, ?) ON CONFLICT (project, actor) DO UPDATE SET "
                "pending = pending + excluded.pending, last = excluded.last",
                (project_id, actor, decisions, now, now),
            )
            row = db.execute(
                "SELECT pending FROM screening_batches WHERE project = ? AND actor = ?",
                (project_id, actor),
            ).fetchone()
        if row["pending"] < BATCH_SIZE:
            return False
        return self.flush(project_id, actor=actor) > 0

    def flush(self, project_id: str, *, actor: str | None = None) -> int:
        """Commit pending screening batches (one actor's, or everyone's); how many commits."""
        with self._lock(project_id):
            repo = self.instance.open_project(project_id)
            with repo_lock(repo):
                made = self._flush_locked(repo, project_id, actor=actor)
        if made:
            self.note_commit(project_id, actor or self._last_actor(project_id) or "")
        return made

    def _last_actor(self, project_id: str) -> str | None:
        row = self.instance.store.one(
            "SELECT pending_actor FROM sync_status WHERE project = ?", (project_id,)
        )
        return str(row["pending_actor"]) if row is not None and row["pending_actor"] else None

    def _flush_locked(self, repo: Repo, project_id: str, *, actor: str | None = None) -> int:
        if actor is None:
            rows = self.instance.store.all(
                "SELECT actor FROM screening_batches WHERE project = ? ORDER BY actor",
                (project_id,),
            )
            actors = [str(row["actor"]) for row in rows]
        else:
            actors = [actor]
        made = 0
        for handle in actors:
            with gitio.environment(identity_for(self.instance, repo, handle)):
                if commit_screening_batch(repo, handle):
                    made += 1
            self.instance.store.execute(
                "DELETE FROM screening_batches WHERE project = ? AND actor = ?",
                (project_id, handle),
            )
        return made

    # -- syncing ---------------------------------------------------------------------------

    def pull_before_read(self, project_id: str, actor: str) -> None:
        """Sync once if the last fetch is older than the interval; never waits on a busy sync."""
        project = self.instance.get_project(project_id)
        if project is None or project.remote is None:
            return
        now = self._clock()
        status = self.status(project_id)
        if status.blocked or (status.next_retry is not None and now < status.next_retry):
            return
        if status.last_fetch is not None and now - status.last_fetch < (
            self.instance.settings.sync_interval
        ):
            return
        lock = self._lock(project_id)
        if not lock.acquire(blocking=False):
            return  # a sync is already running; this page is served from the current copy
        try:
            self._sync_locked(project, actor, push=status.push_pending)
        finally:
            lock.release()

    def push(self, project_id: str) -> bool:
        """Push a project's committed work now (fetching and merging first); whether it pushed."""
        project = self.instance.get_project(project_id)
        if project is None or project.remote is None:
            return False
        actor = self._last_actor(project_id) or ""
        with self._lock(project_id):
            report = self._sync_locked(project, actor, push=True)
        return bool(report is not None and report.pushed)

    def sync_now(self, project_id: str, actor: str) -> SyncStatus:
        """Sync (and push) a project now, whatever the interval; a member asked for it."""
        project = self.instance.get_project(project_id)
        if project is not None and project.remote is not None:
            with self._lock(project_id):
                self._sync_locked(project, actor, push=True)
        return self.status(project_id)

    def resolve(
        self, project_id: str, actor: str, choices: dict[str, str | sync_mod.Edited]
    ) -> SyncStatus:
        """A lead's resolution of the held conflicts: `mine` (the instance's version), `theirs`
        (the remote's), or `Edited` text, by path. Syncs and pushes with it."""
        project = self.instance.get_project(project_id)
        if project is None or project.remote is None:
            return self.status(project_id)

        def resolver(conflict: sync_mod.Conflict) -> str | sync_mod.Edited | None:
            return choices.get(conflict.path)

        with self._lock(project_id):
            self._sync_locked(project, actor, push=True, resolver=resolver)
        return self.status(project_id)

    def run_due(self) -> list[str]:
        """One pass of the background worker: commit idle screening batches, then push what is
        due. The projects it pushed."""
        now = self._clock()
        idle = self.instance.store.all(
            "SELECT DISTINCT project FROM screening_batches WHERE last <= ?", (now - BATCH_IDLE,)
        )
        for row in idle:
            stale = self.instance.store.all(
                "SELECT actor FROM screening_batches WHERE project = ? AND last <= ?",
                (row["project"], now - BATCH_IDLE),
            )
            for batch in stale:
                self.flush(str(row["project"]), actor=str(batch["actor"]))
        pushed = []
        for project in self.instance.list_projects():
            if project.remote is None:
                continue
            status = self.status(project.id)
            if not status.push_pending or status.blocked:
                continue
            if status.next_retry is not None and now < status.next_retry:
                continue
            if self.push(project.id):
                pushed.append(project.id)
        return pushed

    def _sync_locked(
        self,
        project: Project,
        actor: str,
        *,
        push: bool,
        resolver: sync_mod.Resolver | None = None,
    ) -> sync_mod.SyncReport | None:
        """Run `strata sync` for `project` as `actor` and record what happened. The caller holds
        the project's lock."""
        now = self._clock()
        try:
            repo = self.instance.open_project(project.id)
            with repo_lock(repo), self.instance.git_env(project):
                # A sync needs a clean tree, and what was just committed should go out with it.
                push = self._flush_locked(repo, project.id) > 0 or push
                handle = actor or _first_lead_actor(repo)
                with gitio.environment(identity_for(self.instance, repo, handle)):
                    report = sync_mod.sync(
                        repo, actor=handle, push=push, resolver=resolver, backoff=()
                    )
        except sync_mod.ConflictError as exc:
            self._update(
                project.id,
                last_fetch=now,
                last_error="a human-authored file was edited differently here and on the remote",
                conflicts=json.dumps([_conflict_view(c) for c in exc.conflicts]),
            )
            return None
        except (sync_mod.SyncError, LockTimeoutError, SecretError, gitio.GitError) as exc:
            status = self.status(project.id)
            failures = status.failures + 1
            delay = min(RETRY_BASE * 2 ** (failures - 1), RETRY_CAP)
            self._update(
                project.id,
                last_fetch=now,
                last_error=_describe_failure(exc),
                failures=failures,
                next_retry=now + delay,
            )
            return None
        values: dict[str, Any] = {
            "last_fetch": now,
            "last_success": now,
            "last_error": None,
            "failures": 0,
            "next_retry": None,
            "conflicts": None,
        }
        if report.pushed:
            values.update(last_push=now, push_pending=0)
        self._update(project.id, **values)
        return report


def _count(row: Any) -> int:
    return int(row["n"] or 0) if row is not None else 0


def _first_lead_actor(repo: Repo) -> str:
    actors = [a for a in repo.config.get("actors", []) if a.get("role") != "inactive"]
    leads = [a for a in actors if a.get("role") == "lead"]
    chosen = (leads or actors or [{"handle": "strata"}])[0]
    return str(chosen["handle"])


def _conflict_view(conflict: sync_mod.Conflict) -> dict[str, Any]:
    return {
        "path": conflict.path,
        "mine": conflict.mine,
        "theirs": conflict.theirs,
        "summary": list(conflict.summary),
    }


def _describe_failure(exc: Exception) -> str:
    if isinstance(exc, sync_mod.DirtyTreeError):
        return "the project has uncommitted changes the instance did not make; see its working copy"
    if isinstance(exc, sync_mod.VerifyFailedError):
        return f"{exc} ({'; '.join(exc.issues[:3])})"
    if isinstance(exc, gitio.GitError):
        return exc.stderr.strip() or str(exc)
    return str(exc)


# ------------------------------------------------------------------------- screening batches


def _event_ids(text: str) -> set[str]:
    ids = set()
    for line in text.splitlines():
        try:
            ids.add(str(json.loads(line)["id"]))
        except (ValueError, KeyError, TypeError):
            continue
    return ids


def commit_screening_batch(repo: Repo, actor: str) -> bool:
    """Commit `actor`'s uncommitted screening decisions as one batch with a generated summary
    (openspec:git-integration#batched-screening-commits); whether there was anything to commit.

    Only that actor's screening files are committed, with the derived views they move, so two
    reviewers' batches never share a commit.
    """
    directory = repo.path("events", "screen")
    files = sorted(directory.glob(f"*.{actor}.ndjson")) if directory.is_dir() else []
    changed = [
        f"events/screen/{path.name}"
        for path in files
        if gitio.has_changes(repo.root, [f"events/screen/{path.name}"])
    ]
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
            body = event.get("body", {})
            decisions[str(body.get("decision"))] += 1
            stages.add(str(body.get("stage")))
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
        body="Screening decisions recorded in the browser on a hosted instance.",
        trailers=trailers,
    ).message()
    gitio.add(repo.root, [*changed, "derived"])
    gitio.commit(repo.root, message)
    return True


class SyncWorker:
    """Runs `SyncLoop.run_due` in a background thread, every `interval` seconds or when woken."""

    def __init__(self, loop: SyncLoop, *, interval: float = 5.0) -> None:
        self.loop = loop
        self.interval = interval
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="strata-sync", daemon=True)
        self._thread.start()

    def wake(self) -> None:
        self._wake.set()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout=30)
            self._thread = None

    def _run(self) -> None:  # pragma: no cover - timing; `run_due` is tested directly
        while not self._stop.is_set():
            try:
                self.loop.run_due()
            except Exception:  # noqa: BLE001 - one bad pass must not stop the loop
                import logging

                logging.getLogger("strata.hosted").exception("sync pass failed")
            self._wake.wait(self.interval)
            self._wake.clear()
