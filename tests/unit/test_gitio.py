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
