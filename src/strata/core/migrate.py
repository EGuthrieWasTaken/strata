"""Format migrations: `strata migrate`.

Implements openspec:repository-format#format-versioning. A migration is forward-only and
idempotent, never rewrites history, and never runs implicitly: a repository stays in the format
it is in until a person asks (`strata migrate`) or asks for something that needs a newer one
(`strata ai enable`, which runs this).

This module changes files and commits nothing; `strata.core.operations.migrate_repository` wraps it
in the lock, the rationale and the commit. The framework is deliberately small: a table of steps,
each taking the repository from version N to N + 1, and one place that stamps the new version into
both records of it (`.strata/schema-version` and `schema_version` in `strata.toml`).

Version 1 to 2 changes no data. Version 2 is the format that *permits* an `agent` envelope key, the
suggestion event types and agent actors (openspec:ai-participation), and that an older build must
refuse (`E_SCHEMA_TOO_NEW`) rather than fold an agent's opinion as a person's.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from strata.core import manifest as manifest_mod
from strata.core.repo import (
    MAX_SCHEMA_VERSION,
    MIN_SCHEMA_VERSION,
    SCHEMA_VERSION_PATH,
    Repo,
)

#: What a stamp writes, relative to the repository root.
STAMPED_PATHS = (SCHEMA_VERSION_PATH, "strata.toml")


class MigrationError(ValueError):
    """The repository cannot be taken to the requested version."""


@dataclass(frozen=True)
class MigrationResult:
    from_version: int
    to_version: int

    @property
    def changed(self) -> bool:
        return self.from_version != self.to_version

    @property
    def paths(self) -> tuple[str, ...]:
        """The files a changing migration wrote (none when nothing changed)."""
        return STAMPED_PATHS if self.changed else ()


def _one_to_two(repo: Repo) -> None:
    """Format 2 permits AI participation. Nothing on disk needs rewriting to allow it."""
    del repo


#: `STEPS[n]` takes a repository from version `n` to `n + 1`; `migrate_files` applies the stamp.
STEPS: dict[int, Callable[[Repo], None]] = {1: _one_to_two}


def pending(repo: Repo) -> bool:
    """Whether `migrate_files` would change anything."""
    return repo.migration_available


def _stamp(repo: Repo, version: int) -> None:
    repo.path(*SCHEMA_VERSION_PATH.split("/")).write_text(f"{version}\n", encoding="utf-8")
    doc = manifest_mod.load_manifest_doc(repo.root)
    doc["schema_version"] = version
    manifest_mod.write_manifest(repo.root, doc)


def migrate_files(repo: Repo, *, target: int | None = None) -> MigrationResult:
    """Take the repository's files to `target` (default: the newest this build knows).

    Idempotent: at the target already, nothing is written. Raises `MigrationError` for a repository
    with no recorded version, a target this build does not know, or a target below the current
    version (migrations only go forward).
    """
    start = repo.schema_version
    goal = MAX_SCHEMA_VERSION if target is None else target
    if start < MIN_SCHEMA_VERSION:
        raise MigrationError(
            f"this repository records no schema version ({SCHEMA_VERSION_PATH} is missing or "
            "zero), so strata cannot tell what to migrate; `strata doctor` and `strata verify` "
            "say what is wrong"
        )
    if goal > MAX_SCHEMA_VERSION or goal < MIN_SCHEMA_VERSION:
        raise MigrationError(
            f"this build of strata knows schema versions {MIN_SCHEMA_VERSION} to "
            f"{MAX_SCHEMA_VERSION}, not {goal}"
        )
    if goal < start:
        raise MigrationError(
            f"migrations only go forward: the repository is at schema version {start}, "
            f"which cannot be taken back to {goal}"
        )
    version = start
    while version < goal:
        STEPS[version](repo)
        version += 1
    if version != start:
        _stamp(repo, version)
    return MigrationResult(from_version=start, to_version=version)
