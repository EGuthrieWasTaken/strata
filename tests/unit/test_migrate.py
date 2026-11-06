"""`strata migrate`'s file-level step: openspec:repository-format#format-versioning."""

from __future__ import annotations

from pathlib import Path

import pytest

from strata.core import migrate as migrate_mod
from strata.core.repo import MAX_SCHEMA_VERSION, open_repo
from tests.unit._m3 import init_review


def _marker(repo_root: Path) -> str:
    return (repo_root / ".strata" / "schema-version").read_text(encoding="utf-8")


def test_a_new_review_is_in_format_1_and_migration_is_pending(tmp_path: Path) -> None:
    repo = init_review(tmp_path)
    assert repo.schema_version == 1
    assert migrate_mod.pending(repo)


def test_migrating_stamps_both_records_of_the_version(tmp_path: Path) -> None:
    repo = init_review(tmp_path)
    result = migrate_mod.migrate_files(repo)
    assert (result.from_version, result.to_version, result.changed) == (1, MAX_SCHEMA_VERSION, True)
    assert result.paths == (".strata/schema-version", "strata.toml")
    assert _marker(repo.root) == f"{MAX_SCHEMA_VERSION}\n"
    reopened = open_repo(repo.root)
    assert reopened.config["schema_version"] == MAX_SCHEMA_VERSION
    assert reopened.schema_version == MAX_SCHEMA_VERSION
    assert not migrate_mod.pending(reopened)


def test_migrating_keeps_what_the_manifest_said(tmp_path: Path) -> None:
    repo = init_review(tmp_path)
    before = (repo.root / "strata.toml").read_text(encoding="utf-8")
    migrate_mod.migrate_files(repo)
    after = (repo.root / "strata.toml").read_text(encoding="utf-8")
    assert after == before.replace("schema_version = 1", f"schema_version = {MAX_SCHEMA_VERSION}")


def test_migrating_twice_changes_nothing_the_second_time(tmp_path: Path) -> None:
    repo = init_review(tmp_path)
    migrate_mod.migrate_files(repo)
    snapshot = {p: p.read_bytes() for p in repo.root.glob("strata.toml")}
    marker = _marker(repo.root)
    again = migrate_mod.migrate_files(open_repo(repo.root))
    assert not again.changed
    assert again.paths == ()
    assert {p: p.read_bytes() for p in repo.root.glob("strata.toml")} == snapshot
    assert _marker(repo.root) == marker


def test_a_repository_with_no_recorded_version_is_not_guessed_at(tmp_path: Path) -> None:
    repo = init_review(tmp_path)
    (repo.root / ".strata" / "schema-version").unlink()
    with pytest.raises(migrate_mod.MigrationError, match="records no schema version"):
        migrate_mod.migrate_files(open_repo(repo.root))


def test_migrations_only_go_forward(tmp_path: Path) -> None:
    repo = init_review(tmp_path)
    migrate_mod.migrate_files(repo)
    with pytest.raises(migrate_mod.MigrationError, match="only go forward"):
        migrate_mod.migrate_files(open_repo(repo.root), target=1)


def test_a_version_this_build_does_not_know_is_refused(tmp_path: Path) -> None:
    repo = init_review(tmp_path)
    with pytest.raises(migrate_mod.MigrationError, match="knows schema versions"):
        migrate_mod.migrate_files(repo, target=MAX_SCHEMA_VERSION + 1)
    assert _marker(repo.root) == "1\n"  # nothing was half-done
