from pathlib import Path

from strata import gitio
from strata.core.logcmd import domain_log
from strata.core.repo import Repo


def _init_git_repo(path: Path) -> None:
    gitio.init(path)
    gitio.set_config(path, "user.name", "Test")
    gitio.set_config(path, "user.email", "test@example.invalid")


def test_domain_log_on_empty_repository_returns_empty_list(tmp_path: Path) -> None:
    repo_dir = tmp_path / "empty"
    repo_dir.mkdir()
    _init_git_repo(repo_dir)
    repo = Repo(root=repo_dir, config={})
    assert domain_log(repo) == []


def test_domain_log_parses_and_filters_trailers(tmp_path: Path) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    _init_git_repo(repo_dir)
    (repo_dir / "a.txt").write_text("1", encoding="utf-8")
    gitio.add_all(repo_dir)
    gitio.commit(
        repo_dir,
        "criteria(v2): tighten EXC-03\n\nStrata-Op: criteria-change\nStrata-Actor: ethan\n",
    )
    (repo_dir / "a.txt").write_text("2", encoding="utf-8")
    gitio.add_all(repo_dir)
    gitio.commit(
        repo_dir,
        "screen(title-abstract): screen 3 records\n\n"
        "Strata-Op: screen\nStrata-Stage: title-abstract\nStrata-Actor: sam\n",
    )

    repo = Repo(root=repo_dir, config={})
    all_commits = domain_log(repo)
    assert len(all_commits) == 2
    assert all_commits[0].subject == "screen(title-abstract): screen 3 records"
    assert all_commits[0].trailers["Op"] == "screen"

    criteria_only = domain_log(repo, criteria_only=True)
    assert len(criteria_only) == 1
    assert criteria_only[0].trailers["Op"] == "criteria-change"

    by_stage = domain_log(repo, stage="title-abstract")
    assert len(by_stage) == 1
    assert by_stage[0].trailers["Actor"] == "sam"

    by_actor = domain_log(repo, actor="ethan")
    assert len(by_actor) == 1
    assert by_actor[0].trailers["Op"] == "criteria-change"

    assert domain_log(repo, actor="nobody") == []
