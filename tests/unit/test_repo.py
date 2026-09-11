from pathlib import Path

import pytest

from strata.core.repo import (
    CURRENT_SCHEMA_VERSION,
    LockTimeoutError,
    Repo,
    RepoNotFoundError,
    SchemaTooNewError,
    find_repo_root,
    open_repo,
    repo_lock,
)


def test_find_repo_root_walks_up_from_subdirectory(tmp_path: Path) -> None:
    (tmp_path / "strata.toml").write_text("schema_version = 1\n", encoding="utf-8")
    sub = tmp_path / "a" / "b"
    sub.mkdir(parents=True)
    assert find_repo_root(sub) == tmp_path.resolve()


def test_find_repo_root_raises_when_not_found(tmp_path: Path) -> None:
    with pytest.raises(RepoNotFoundError):
        find_repo_root(tmp_path)


def _write_minimal_manifest(root: Path, schema_version: int = 1) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "strata.toml").write_text(
        f'schema_version = {schema_version}\ncreated_with = "strata/0.1.0"\n'
        '[project]\nid = "prj_x"\ntitle = "T"\nslug = "t"\ncreated = "2026-01-01"\n'
        '[[actors]]\nhandle = "ethan"\nname = "Ethan"\nrole = "lead"\n',
        encoding="utf-8",
    )


def test_open_repo_succeeds_on_current_schema_version(tmp_path: Path) -> None:
    _write_minimal_manifest(tmp_path)
    repo = open_repo(tmp_path)
    assert repo.root == tmp_path.resolve()
    assert repo.config["project"]["title"] == "T"


def test_repo_schema_version_defaults_to_zero_without_marker_file(tmp_path: Path) -> None:
    _write_minimal_manifest(tmp_path)
    repo = open_repo(tmp_path)
    assert repo.schema_version == 0


def test_repo_schema_version_reads_marker_file(tmp_path: Path) -> None:
    _write_minimal_manifest(tmp_path)
    (tmp_path / ".strata").mkdir()
    (tmp_path / ".strata" / "schema-version").write_text("1\n", encoding="utf-8")
    repo = Repo(root=tmp_path, config={})
    assert repo.schema_version == 1


def test_open_repo_refuses_schema_too_new(tmp_path: Path) -> None:
    _write_minimal_manifest(tmp_path)
    (tmp_path / ".strata").mkdir()
    (tmp_path / ".strata" / "schema-version").write_text(
        str(CURRENT_SCHEMA_VERSION + 1), encoding="utf-8"
    )
    with pytest.raises(SchemaTooNewError):
        open_repo(tmp_path)


def test_repo_lock_acquires_and_releases(tmp_path: Path) -> None:
    _write_minimal_manifest(tmp_path)
    repo = open_repo(tmp_path)
    lock_path = repo.path(".strata", "lock")
    with repo_lock(repo):
        assert lock_path.exists()
        assert repo.path(".strata", "lock").read_text().strip().isdigit()
    assert not lock_path.exists()


def test_repo_lock_times_out_when_already_held(tmp_path: Path) -> None:
    _write_minimal_manifest(tmp_path)
    repo = open_repo(tmp_path)
    lock_path = repo.path(".strata", "lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text("999999\n", encoding="utf-8")
    try:
        with pytest.raises(LockTimeoutError, match="999999"), repo_lock(repo, timeout=0.2):
            pass
    finally:
        lock_path.unlink(missing_ok=True)


def test_repo_lock_releases_on_exception(tmp_path: Path) -> None:
    _write_minimal_manifest(tmp_path)
    repo = open_repo(tmp_path)
    lock_path = repo.path(".strata", "lock")
    with pytest.raises(ValueError, match="boom"), repo_lock(repo):
        raise ValueError("boom")
    assert not lock_path.exists()
