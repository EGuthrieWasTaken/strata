import os
import sys
from pathlib import Path

import pytest

from strata import gitio


def _repo(tmp_path: Path) -> Path:
    gitio.init(tmp_path)
    gitio.set_config(tmp_path, "user.name", "Test")
    gitio.set_config(tmp_path, "user.email", "test@example.invalid")
    return tmp_path


def test_run_raises_git_error_on_failure(tmp_path: Path) -> None:
    _repo(tmp_path)
    with pytest.raises(gitio.GitError, match="failed"):
        gitio.run(["not-a-real-git-subcommand"], cwd=tmp_path)


def test_run_check_false_does_not_raise(tmp_path: Path) -> None:
    _repo(tmp_path)
    result = gitio.run(["not-a-real-git-subcommand"], cwd=tmp_path, check=False)
    assert result.returncode != 0


def test_is_git_repo_true_and_false(tmp_path: Path) -> None:
    repo_dir = tmp_path / "repo"
    not_repo_dir = tmp_path / "not-a-repo"
    not_repo_dir.mkdir()
    _repo(repo_dir)
    assert gitio.is_git_repo(repo_dir) is True
    assert gitio.is_git_repo(not_repo_dir) is False


def test_commit_with_allow_empty(tmp_path: Path) -> None:
    _repo(tmp_path)
    (tmp_path / "a.txt").write_text("1", encoding="utf-8")
    gitio.add_all(tmp_path)
    gitio.commit(tmp_path, "first commit")
    sha = gitio.commit(tmp_path, "empty follow-up", allow_empty=True)
    assert sha == gitio.current_commit(tmp_path)


def test_has_staged_changes_follows_the_index(tmp_path: Path) -> None:
    _repo(tmp_path)
    (tmp_path / "a.txt").write_text("1", encoding="utf-8")
    assert gitio.has_staged_changes(tmp_path) is False  # untracked is not staged
    gitio.add_all(tmp_path)
    assert gitio.has_staged_changes(tmp_path) is True
    gitio.commit(tmp_path, "first commit")
    assert gitio.has_staged_changes(tmp_path) is False


def test_a_failure_that_git_reports_on_stdout_still_carries_its_message(tmp_path: Path) -> None:
    """`git commit` with nothing to commit says so on stdout and leaves stderr empty."""
    _repo(tmp_path)
    (tmp_path / "a.txt").write_text("1", encoding="utf-8")
    gitio.add_all(tmp_path)
    gitio.commit(tmp_path, "first commit")
    with pytest.raises(gitio.GitError, match="nothing to commit"):
        gitio.commit(tmp_path, "second commit")


def test_current_branch(tmp_path: Path) -> None:
    _repo(tmp_path)
    (tmp_path / "a.txt").write_text("1", encoding="utf-8")
    gitio.add_all(tmp_path)
    gitio.commit(tmp_path, "first commit")
    assert gitio.current_branch(tmp_path) == "main"


def test_log_with_max_count(tmp_path: Path) -> None:
    _repo(tmp_path)
    for i in range(3):
        (tmp_path / "a.txt").write_text(str(i), encoding="utf-8")
        gitio.add_all(tmp_path)
        gitio.commit(tmp_path, f"commit {i}")
    assert len(gitio.log(tmp_path)) == 3
    assert len(gitio.log(tmp_path, max_count=1)) == 1


def test_log_returns_empty_list_on_failure(tmp_path: Path) -> None:
    not_repo_dir = tmp_path / "not-a-repo"
    not_repo_dir.mkdir()
    assert gitio.log(not_repo_dir) == []


# --- the hooks git triggers call `strata` by name -----------------------------------------------


# On Windows `shutil.which` finds a command only through a PATHEXT extension, so a bare `strata`
# file would not be found there.
SCRIPT = "strata.exe" if sys.platform == "win32" else "strata"


def _fake_script_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "venv" / "bin"
    directory.mkdir(parents=True)
    (directory / SCRIPT).write_text("#!/bin/sh\n", encoding="utf-8")
    return directory


def test_git_inherits_the_environment_when_strata_is_on_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    on_path = _fake_script_dir(tmp_path)
    (on_path / SCRIPT).chmod(0o755)
    monkeypatch.setenv("PATH", str(on_path))
    assert gitio._env_for_hooks() is None


def test_the_running_script_is_appended_to_path_not_prepended(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    script_dir = _fake_script_dir(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.setenv("PATH", str(elsewhere))
    monkeypatch.setattr("sys.argv", [str(script_dir / SCRIPT), "actor", "add"])
    env = gitio._env_for_hooks()
    assert env is not None
    assert env["PATH"].split(os.pathsep) == [str(elsewhere), str(script_dir)]


def test_the_interpreters_directory_is_used_when_not_started_as_strata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    script_dir = _fake_script_dir(tmp_path)
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setattr("sys.argv", ["pytest"])
    monkeypatch.setattr("sys.executable", str(script_dir / "python"))
    env = gitio._env_for_hooks()
    assert env is not None and env["PATH"].split(os.pathsep)[-1] == str(script_dir)


def test_nothing_changes_when_strata_cannot_be_found_anywhere(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setattr("sys.argv", ["pytest"])
    monkeypatch.setattr("sys.executable", str(tmp_path / "nowhere" / "python"))
    assert gitio._env_for_hooks() is None


def test_ensure_local_exclude_ignores_a_path_without_touching_a_tracked_file(
    tmp_path: Path,
) -> None:
    _repo(tmp_path)
    (tmp_path / ".strata" / "tmp").mkdir(parents=True)
    (tmp_path / ".strata" / "tmp" / "upload.ris").write_text("x", encoding="utf-8")
    assert gitio.is_dirty(tmp_path)

    gitio.ensure_local_exclude(tmp_path, ["/.strata/tmp/"])

    assert not gitio.is_dirty(tmp_path)
    assert not (tmp_path / ".gitignore").exists()


def test_ensure_local_exclude_is_idempotent_and_keeps_existing_entries(tmp_path: Path) -> None:
    _repo(tmp_path)
    exclude = tmp_path / ".git" / "info" / "exclude"
    exclude.parent.mkdir(parents=True, exist_ok=True)
    exclude.write_text("# mine\n*.swp", encoding="utf-8")  # no trailing newline

    gitio.ensure_local_exclude(tmp_path, ["/.strata/tmp/", "*.swp"])
    gitio.ensure_local_exclude(tmp_path, ["/.strata/tmp/"])

    assert exclude.read_text(encoding="utf-8").splitlines() == ["# mine", "*.swp", "/.strata/tmp/"]


def test_ensure_local_exclude_outside_a_repository_does_nothing(tmp_path: Path) -> None:
    gitio.ensure_local_exclude(tmp_path, ["/.strata/tmp/"])

    assert not (tmp_path / ".git").exists()
