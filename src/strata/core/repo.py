"""Repository discovery, configuration, and locking.

Implements the repository-facing half of docs/spec/02-repository-format.md
and the locking model in docs/spec/12-architecture.md §4.
"""

from __future__ import annotations

import contextlib
import os
import time
import tomllib
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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


@contextlib.contextmanager
def repo_lock(repo: Repo, timeout: float = DEFAULT_LOCK_TIMEOUT) -> Iterator[None]:
    """Advisory lock guarding mutating operations, per docs/spec/12-architecture.md §4.

    Readers never take this lock. Held for the duration of an append-plus-commit.
    """
    lock_path = repo.path(*LOCK_PATH.split("/"))
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout
    fd: int | None = None
    while fd is None:
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            if time.monotonic() >= deadline:
                holder = "unknown"
                if lock_path.exists():
                    with contextlib.suppress(OSError):
                        holder = lock_path.read_text().strip() or holder
                raise LockTimeoutError(
                    f"repository is locked (held by process {holder}); timed out after {timeout:g}s"
                ) from None
            time.sleep(0.1)
    try:
        os.write(fd, f"{os.getpid()}\n".encode())
        os.close(fd)
        fd = None
        yield
    finally:
        if fd is not None:
            os.close(fd)
        lock_path.unlink(missing_ok=True)
