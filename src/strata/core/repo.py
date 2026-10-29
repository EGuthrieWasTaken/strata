"""Repository discovery, configuration, and locking.

Implements the repository-facing half of openspec:repository-format
and the locking model in openspec:architecture#concurrency-and-locking.
"""

from __future__ import annotations

import contextlib
import tomllib
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from strata.core import lockfile

MANIFEST_NAME = "strata.toml"
SCHEMA_VERSION_PATH = ".strata/schema-version"
LOCK_PATH = ".strata/lock"
DEFAULT_LOCK_TIMEOUT = 30.0
CURRENT_SCHEMA_VERSION = 1


class RepoNotFoundError(Exception):
    """No `strata.toml` found in `start` or any parent directory (exit code 3)."""


class LockTimeoutError(Exception):
    """Could not acquire the repository lock within the timeout."""


class SchemaTooNewError(Exception):
    """`E_SCHEMA_TOO_NEW`: the repository's schema version exceeds what this tool supports."""


@dataclass
class Repo:
    root: Path
    config: dict[str, Any]

    def path(self, *parts: str) -> Path:
        return self.root.joinpath(*parts)

    @property
    def schema_version(self) -> int:
        path = self.path(*SCHEMA_VERSION_PATH.split("/"))
        if not path.exists():
            return 0
        return int(path.read_text().strip())


def find_repo_root(start: Path | None = None) -> Path:
    """Walk upward from `start` (default: cwd) looking for `strata.toml`, like git."""
    current = (start or Path.cwd()).resolve()
    while True:
        if (current / MANIFEST_NAME).is_file():
            return current
        if current.parent == current:
            raise RepoNotFoundError(
                "not a strata repository (or any parent up to the filesystem root)"
            )
        current = current.parent


def load_config(root: Path) -> dict[str, Any]:
    with open(root / MANIFEST_NAME, "rb") as f:
        return tomllib.load(f)


def open_repo(start: Path | None = None) -> Repo:
    root = find_repo_root(start)
    config = load_config(root)
    repo = Repo(root=root, config=config)
    if repo.schema_version > CURRENT_SCHEMA_VERSION:
        raise SchemaTooNewError(
            f"this repository's schema version ({repo.schema_version}) is newer than "
            f"this build of strata supports ({CURRENT_SCHEMA_VERSION}); upgrade strata"
        )
    return repo


@dataclass(frozen=True)
class HeldLock:
    """What a holder of the repository lock is told about how it got it."""

    #: The process id found in the lock file when it was taken, if that process did not release
    #: it cleanly (it died while holding the lock). `None` for an ordinary acquisition.
    reclaimed_from: int | None = None


@contextlib.contextmanager
def repo_lock(repo: Repo, timeout: float = DEFAULT_LOCK_TIMEOUT) -> Iterator[HeldLock]:
    """Advisory lock guarding mutating operations, per
    openspec:architecture#concurrency-and-locking.

    Readers never take this lock. Held for the duration of an append-plus-commit. The lock is the
    operating system's, so a holder that dies releases it with its last breath
    (`strata.core.lockfile`); the result says when that happened to the previous holder.
    """
    lock_path = repo.path(*LOCK_PATH.split("/"))
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd, reclaimed_from = lockfile.acquire(lock_path, timeout)
    except lockfile.LockTimeout as exc:
        holder = "unknown" if exc.holder is None else str(exc.holder)
        raise LockTimeoutError(
            f"repository is locked (held by process {holder}); timed out after {timeout:g}s"
        ) from None
    try:
        yield HeldLock(reclaimed_from=reclaimed_from)
    finally:
        lockfile.release(lock_path, fd)
