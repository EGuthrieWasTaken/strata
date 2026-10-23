"""`strata sync`: fetch, merge, resolve, verify, push, reported in domain terms.

Implements openspec:collaboration-sync. The shape of every step is the specification's: refuse a
dirty tree; fetch with the 2/4/8/16-second retry; fast-forward when nothing diverged, otherwise
merge;
put merged event files in canonical order and re-link their chains (recording a `relink` event);
regenerate the derived views; verify, and if that fails restore the state from before the sync and
push nothing; commit the merge as `Strata-Op: sync`; push with the same retry; and say what changed
in terms of people, decisions and conflicts rather than commits.

Git is never the interface (openspec:git-integration#git-is-never-the-user-interface): the user sees
`mine` and `theirs` and the criterion or file they disagree about, never a conflict marker, unless
they choose to open an editor.
"""

from __future__ import annotations

import difflib
import json
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from strata import gitio
from strata.core import merge as merge_mod
from strata.core import verify as verify_mod
from strata.core.canon import canonical_json, load_yaml_str
from strata.core.commit import StructuredCommit
from strata.core.events import append_new_event
from strata.core.repo import Repo, open_repo
from strata.protocol import pool as pool_mod
from strata.report import counts as counts_mod

BACKOFF = (2, 4, 8, 16)
MAX_ROUNDS = 3
_NETWORK_HINTS = (
    "could not resolve host", "unable to access", "connection", "timed out", "timeout",
    "network is unreachable", "early eof", "remote end hung up", "temporary failure",
    "couldn't connect", "could not read from remote", "ssl", "tls",
)  # fmt: skip

Resolver = Callable[["Conflict"], str | None]


class SyncError(Exception):
    """The sync could not finish; the message says why and what the user can do."""

    exit_kind = "generic"


class DirtyTreeError(SyncError):
    pass


class VerifyFailedError(SyncError):
    exit_kind = "validation"

    def __init__(self, message: str, issues: list[str]) -> None:
        super().__init__(message)
        self.issues = issues


class ConflictError(SyncError):
    exit_kind = "conflict"

    def __init__(self, message: str, conflicts: list[Conflict]) -> None:
        super().__init__(message)
        self.conflicts = conflicts


@dataclass
class Conflict:
    """Two incompatible edits to one human-authored file, held in domain terms."""

    path: str
    mine: str
    theirs: str
    summary: list[str] = field(default_factory=list)


@dataclass
class SyncReport:
    status: str = "up-to-date"  # up-to-date | fast-forward | merged | pushed-only
    pushed: bool = False
    incoming_commits: int = 0
    incoming_authors: dict[str, int] = field(default_factory=dict)
    screened: dict[tuple[str, str], dict[str, int]] = field(default_factory=dict)
    other_events: dict[str, int] = field(default_factory=dict)
    union_merged: list[str] = field(default_factory=list)
    relinked: list[merge_mod.Relink] = field(default_factory=list)
    auto_resolutions: list[dict[str, Any]] = field(default_factory=list)
    resolved_conflicts: list[tuple[str, str]] = field(default_factory=list)
    totals_before: dict[str, int] = field(default_factory=dict)
    totals_after: dict[str, int] = field(default_factory=dict)
    conflicts_before: int = 0
    conflicts_after: int = 0

    @property
    def new_conflicts(self) -> int:
        return max(self.conflicts_after - self.conflicts_before, 0)


# --- git helpers ----------------------------------------------------------------------------


def _git(repo: Repo, *args: str, check: bool = True) -> Any:
    return gitio.run(list(args), cwd=repo.root, check=check)


def _is_network_failure(stderr: str) -> bool:
    text = stderr.lower()
    return any(hint in text for hint in _NETWORK_HINTS)


def _retrying(action: Callable[[], Any], what: str, sleep: Callable[[float], None]) -> Any:
    """Run a network step, retrying network failures up to four times with 2, 4, 8, 16 s backoff."""
    attempt = 0
    while True:
        try:
            return action()
        except gitio.GitError as exc:
            if not _is_network_failure(exc.stderr):
                raise SyncError(f"{what} failed: {exc.stderr.strip()}") from None
            if attempt >= len(BACKOFF):
                tries = len(BACKOFF) + 1
                raise SyncError(
                    f"{what} failed after {tries} attempts (network): {exc.stderr.strip()}"
                ) from None
            sleep(BACKOFF[attempt])
            attempt += 1


def _remote_name(repo: Repo, remote: str | None) -> str:
    name = remote or str(repo.config.get("git", {}).get("remote") or "origin")
    known = _git(repo, "remote").stdout.split()
    if name not in known:
        raise SyncError(
            f"there is no shared remote called {name!r} to sync with; add it once with "
            f"`git remote add {name} <url>` (or name another with `strata config git.remote`)"
        )
    return name


def _unmerged(repo: Repo) -> list[str]:
    out = _git(repo, "diff", "--name-only", "--diff-filter=U", check=False).stdout
    return sorted(line for line in out.splitlines() if line)


def _stage_text(repo: Repo, stage: int, path: str) -> str:
    result = _git(repo, "show", f":{stage}:{path}", check=False)
    return result.stdout if result.returncode == 0 else ""


def _criteria_summary(mine: str, theirs: str) -> list[str]:
    try:
        a = {c["id"]: c for c in (load_yaml_str(mine) or {}).get("criteria", [])}
        b = {c["id"]: c for c in (load_yaml_str(theirs) or {}).get("criteria", [])}
    except (ValueError, TypeError, KeyError):
        return []
    lines = []
    for cid in sorted({*a, *b}):
        if cid not in b or cid not in a:
            side = "mine" if cid in a else "theirs"
            lines.append(f"{cid}: only in {side}")
        elif a[cid] != b[cid]:
            for name in ("label", "definition", "applies_at", "status"):
                if a[cid].get(name) != b[cid].get(name):
                    lines.append(
                        f"{cid} {name}: mine {a[cid].get(name)!r} | theirs {b[cid].get(name)!r}"
                    )
    return lines


def describe(repo: Repo, path: str) -> Conflict:
    mine, theirs = _stage_text(repo, 2, path), _stage_text(repo, 3, path)
    if path == "protocol/criteria.yaml":
        summary = _criteria_summary(mine, theirs)
    else:
        diff = list(
            difflib.unified_diff(
                mine.splitlines(), theirs.splitlines(), "mine", "theirs", lineterm="", n=0
            )
        )
        summary = [line for line in diff if not line.startswith(("---", "+++", "@@"))][:12]
    return Conflict(path, mine, theirs, summary)


_REGENERATED = ("derived/", "reports/", "analysis/results/")
_UNIONED = ("records/aliases.ndjson", "fulltext/manifest.ndjson")


def _auto_resolve(repo: Repo, path: str) -> bool:
    """Settle a conflict in a file strata owns the way its merge driver would have, so that a
    clone without the drivers installed still syncs
    (openspec:git-integration#merge-drivers)."""
    target = repo.path(*path.split("/"))
    if path.startswith(_REGENERATED):
        _git(repo, "checkout", "--ours", "--", path)  # rebuilt from the merged events below
    elif (path.startswith("events/") and path.endswith(".ndjson")) or path in _UNIONED:
        lines: list[str] = []
        for stage in (2, 3):
            for line in _stage_text(repo, stage, path).splitlines():
                if line.strip() and line not in lines:
                    lines.append(line)
        target.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8", newline="\n")
    elif path == "records/records.ndjson":
        trust = [str(t).lower() for t in repo.config.get("dedup", {}).get("source_trust", [])]
        text, resolutions = merge_mod.merge_records_text(
            _stage_text(repo, 1, path),
            _stage_text(repo, 2, path),
            _stage_text(repo, 3, path),
            trust=trust,
        )
        target.write_text(text, encoding="utf-8", newline="\n")
        notes = repo.path(*merge_mod.NOTES_PATH)
        notes.parent.mkdir(parents=True, exist_ok=True)
        with notes.open("a", encoding="utf-8", newline="\n") as handle:
            for resolution in resolutions:
                handle.write(canonical_json(resolution.to_dict()) + "\n")
    else:
        return False
    _git(repo, "add", "--", path)
    return True


def _resolve_conflicts(repo: Repo, resolver: Resolver | None, report: SyncReport) -> None:
    for path in _unmerged(repo):
        _auto_resolve(repo, path)
    conflicts = [describe(repo, p) for p in _unmerged(repo)]
    if not conflicts:
        return
    if resolver is None:
        raise ConflictError("a human-authored file was edited differently by two people", conflicts)
    for conflict in conflicts:
        choice = resolver(conflict)
        if choice == "mine":
            _git(repo, "checkout", "--ours", "--", conflict.path)
        elif choice == "theirs":
            _git(repo, "checkout", "--theirs", "--", conflict.path)
        elif choice == "editor":
            _git(repo, "checkout", "--merge", "--", conflict.path)
            edit_file(repo.path(*conflict.path.split("/")))
            text = repo.path(*conflict.path.split("/")).read_text(encoding="utf-8")
            if any(marker in text for marker in ("<<<<<<< ", "\n=======\n", ">>>>>>> ")):
                raise ConflictError(
                    f"{conflict.path} still has unresolved edits; run strata sync again", [conflict]
                )
        else:
            raise ConflictError("the conflict was left for a person to resolve", conflicts)
        _git(repo, "add", "--", conflict.path)
        report.resolved_conflicts.append((conflict.path, choice))


def edit_file(path: Path) -> None:  # pragma: no cover - needs a person at an editor
    import click

    click.edit(filename=str(path))


# --- what changed ---------------------------------------------------------------------------


def _event_ids(text: str) -> set[str]:
    ids = set()
    for line in text.splitlines():
        try:
            ids.add(str(json.loads(line)["id"]))
        except (ValueError, KeyError, TypeError):
            continue
    return ids


def _new_events(repo: Repo, before: str) -> list[dict[str, Any]]:
    """The events now in the tree that were not in `before`, parsed."""
    changed = _git(repo, "diff", "--name-only", before, "--", "events", check=False).stdout.split()
    others = _git(repo, "ls-files", "--others", "--exclude-standard", "--", "events").stdout.split()
    found: list[dict[str, Any]] = []
    for relative in sorted({*changed, *others}):
        path = repo.path(*relative.split("/"))
        if not path.is_file():
            continue
        old = _git(repo, "show", f"{before}:{relative}", check=False)
        known = _event_ids(old.stdout) if old.returncode == 0 else set()
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if str(event.get("id")) not in known:
                found.append(event)
    return found


def _summarise(events: list[dict[str, Any]], report: SyncReport, own_actor: str) -> None:
    for event in events:
        if event.get("ev") == "relink":
            continue
        if event.get("ev") == "screen":
            body = event.get("body", {})
            key = (str(event.get("actor")), str(body.get("stage")))
            report.screened.setdefault(key, Counter())[str(body.get("decision"))] += 1
        else:
            name = str(event.get("ev"))
            report.other_events[name] = report.other_events.get(name, 0) + 1


def _conflict_rows(repo: Repo, ref: str | None) -> int:
    if ref is None:
        text = repo.path("derived", "conflicts.tsv")
        content = text.read_text(encoding="utf-8") if text.exists() else ""
    else:
        shown = _git(repo, "show", f"{ref}:derived/conflicts.tsv", check=False)
        content = shown.stdout if shown.returncode == 0 else ""
    return max(len([ln for ln in content.splitlines() if ln.strip()]) - 1, 0)


def _totals(repo: Repo) -> dict[str, int]:
    t = counts_mod.compute(repo).totals
    return {
        "records": t.records_screened,
        "title-abstract included": t.reports_sought,
        "full-text included": t.reports_included,
    }


# --- the sync -------------------------------------------------------------------------------


def _normalise(repo: Repo, before: str, actor: str, report: SyncReport) -> None:
    changed = _git(repo, "diff", "--name-only", before, "--", "events", check=False).stdout.split()
    others = _git(repo, "ls-files", "--others", "--exclude-standard", "--", "events").stdout.split()
    for relative in sorted({*changed, *others}):
        path = repo.path(*relative.split("/"))
        if (
            not path.is_file()
            or not relative.endswith(".ndjson")
            or relative.startswith("events/relink/")
        ):
            continue
        relink = merge_mod.normalise_event_file(path, relative=relative)
        if relink is not None:
            report.relinked.append(relink)
    for relink in report.relinked:
        append_new_event(
            repo.path("events", "relink", f"{actor}.ndjson"),
            ev="relink",
            actor=actor,
            body={
                "file": relink.file,
                "lines_reordered": relink.lines_reordered,
                "duplicates_dropped": relink.duplicates_dropped,
                "reason": relink.reason,
            },
        )


def _apply_merge_notes(repo: Repo, actor: str, report: SyncReport) -> None:
    notes_path = repo.path(*merge_mod.NOTES_PATH)
    notes = merge_mod.read_notes(notes_path)
    if notes:
        for note in notes:
            append_new_event(
                repo.path("events", "fix", f"{actor}.ndjson"),
                ev="record-amend",
                actor=actor,
                body={
                    "record": note["record"],
                    "field": note["field"],
                    "old": note["old"],
                    "new": note["new"],
                    "source": "merge",
                },
            )
        report.auto_resolutions.extend(notes)
    notes_path.unlink(missing_ok=True)


def _abort(repo: Repo, before: str, merging: bool) -> None:
    if merging:
        _git(repo, "merge", "--abort", check=False)
    _git(repo, "reset", "--hard", before, check=False)
    _git(repo, "clean", "-fdq", "--", "events", "derived", check=False)
    repo.path(*merge_mod.NOTES_PATH).unlink(missing_ok=True)


def _verify_or_abort(repo: Repo, before: str, merging: bool) -> None:
    result = verify_mod.verify_repository(open_repo(repo.root))
    errors = [f"{i.code}: {i.message}" for i in result.issues if i.severity != "warning"]
    if errors:
        _abort(repo, before, merging)
        raise VerifyFailedError(
            "the merged repository does not verify, so nothing was pushed and your repository "
            "is exactly as it was before the sync",
            errors,
        )


def _sync_round(
    repo: Repo,
    *,
    actor: str,
    remote: str,
    strategy: str,
    resolver: Resolver | None,
    sleep: Callable[[float], None],
    log: Callable[[str], None],
    report: SyncReport,
) -> bool:
    """One fetch-integrate-verify-commit pass; True when something was integrated or is to push."""
    branch = gitio.current_branch(repo.root)
    if branch == "HEAD":
        raise SyncError("the repository is not on a branch; switch to one before syncing")
    log("Fetching " + remote)
    _retrying(lambda: gitio.fetch(repo.root, remote), "fetching", sleep)
    upstream = f"refs/remotes/{remote}/{branch}"
    has_upstream = (
        _git(repo, "rev-parse", "--verify", "--quiet", upstream, check=False).returncode == 0
    )
    before = gitio.current_commit(repo.root)
    report.conflicts_before = _conflict_rows(repo, None)
    report.totals_before = _totals(repo)
    ahead = behind = 0
    if has_upstream:
        counts = _git(
            repo, "rev-list", "--left-right", "--count", f"HEAD...{upstream}"
        ).stdout.split()
        ahead, behind = int(counts[0]), int(counts[1])
    merging = False
    if behind:
        report.incoming_commits = behind
        authors = _git(repo, "log", "--format=%B", f"HEAD..{upstream}").stdout
        for line in authors.splitlines():
            if line.startswith("Strata-Actor:"):
                name = line.split(":", 1)[1].strip()
                report.incoming_authors[name] = report.incoming_authors.get(name, 0) + 1
        if ahead == 0:
            log("Fast-forwarding")
            _git(repo, "merge", "--ff-only", upstream)
            report.status = "fast-forward"
        elif strategy == "rebase":
            log("Rebasing")
            result = _git(repo, "rebase", upstream, check=False)
            if result.returncode != 0:
                conflicts = [describe(repo, p) for p in _unmerged(repo)]
                _git(repo, "rebase", "--abort", check=False)
                raise ConflictError(
                    "a human-authored file was edited differently by two people", conflicts
                )
            report.status = "merged"
        else:
            log("Merging")
            result = _git(repo, "merge", "--no-commit", "--no-ff", upstream, check=False)
            merging = (
                _git(repo, "rev-parse", "--verify", "--quiet", "MERGE_HEAD", check=False).returncode
                == 0
            )
            report.status = "merged"
            if result.returncode != 0 and _unmerged(repo):
                try:
                    _resolve_conflicts(repo, resolver, report)
                except SyncError:
                    _abort(repo, before, True)
                    raise
            elif result.returncode != 0:
                _abort(repo, before, merging)
                raise SyncError(f"merging failed: {result.stderr.strip() or result.stdout.strip()}")
    if behind and ahead:
        log("Normalising merged event files")
        _normalise(repo, before, actor, report)
    _apply_merge_notes(repo, actor, report)
    log("Regenerating derived views")
    fresh = open_repo(repo.root)
    pool_mod.regenerate_all(fresh)
    log("Verifying")
    _verify_or_abort(repo, before, merging)
    _summarise(_new_events(repo, before), report, actor)
    report.conflicts_after = _conflict_rows(repo, None)
    report.totals_after = _totals(open_repo(repo.root))
    if merging or gitio.is_dirty(repo.root):
        _git(repo, "add", "-A")
        summary = "sync with " + remote
        message = StructuredCommit(
            op="sync", scope=None, summary=summary,
            body="Merged the shared remote into this repository and regenerated the derived views.",
            trailers={"Op": "sync", "Actor": actor},
        ).message()  # fmt: skip
        gitio.commit(repo.root, message, allow_empty=merging)
    return bool(behind or ahead or not has_upstream or gitio.current_commit(repo.root) != before)


def sync(
    repo: Repo,
    *,
    actor: str,
    remote: str | None = None,
    strategy: str | None = None,
    push: bool = True,
    resolver: Resolver | None = None,
    sleep: Callable[[float], None] = time.sleep,
    log: Callable[[str], None] = lambda message: None,
) -> SyncReport:
    """Run `strata sync` on `repo` as `actor`; returns what happened."""
    if gitio.is_dirty(repo.root):
        raise DirtyTreeError(
            "there are uncommitted changes; finish or record them with `strata` first (every "
            "strata command commits its own work), then sync"
        )
    name = _remote_name(repo, remote)
    chosen = strategy or str(repo.config.get("git", {}).get("sync_strategy") or "merge")
    report = SyncReport()
    branch = gitio.current_branch(repo.root)
    for _ in range(MAX_ROUNDS):
        _sync_round(
            repo,
            actor=actor,
            remote=name,
            strategy=chosen,
            resolver=resolver,
            sleep=sleep,
            log=log,
            report=report,
        )
        if not push:
            return report
        log("Pushing")
        try:
            _retrying(
                lambda: _git(repo, "push", "-u", name, f"HEAD:refs/heads/{branch}"),
                "pushing",
                sleep,
            )
        except SyncError as exc:
            if (
                "rejected" in str(exc).lower()
                or "non-fast-forward" in str(exc).lower()
                or "fetch first" in str(exc).lower()
            ):
                continue  # someone pushed since we fetched: integrate theirs and try again
            raise
        report.pushed = True
        return report
    raise SyncError("the remote kept changing while syncing; run strata sync again")
