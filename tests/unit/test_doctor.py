from pathlib import Path
from types import SimpleNamespace

from strata import gitio
from strata.core.doctor import _git_version, run_doctor
from strata.core.hooks import HOOKS_DIR
from strata.core.init import MERGE_DRIVERS
from strata.core.repo import Repo

_VALID_MANIFEST = """\
schema_version = 1
created_with = "strata/0.1.0"

[project]
id = "prj_x"
title = "T"
slug = "t"
created = "2026-01-01"

[[actors]]
handle = "ethan"
name = "Ethan"
role = "lead"
"""


def _bare_git_repo(tmp_path: Path) -> Repo:
    gitio.init(tmp_path)
    gitio.set_config(tmp_path, "user.name", "Test")
    gitio.set_config(tmp_path, "user.email", "test@example.invalid")
    (tmp_path / "strata.toml").write_text(_VALID_MANIFEST, encoding="utf-8")
    return Repo(root=tmp_path, config={})


def test_git_version_none_on_nonzero_exit(tmp_path: Path, monkeypatch) -> None:
    repo = _bare_git_repo(tmp_path)
    monkeypatch.setattr(
        "strata.core.doctor.gitio.run", lambda *a, **kw: SimpleNamespace(returncode=1, stdout="")
    )
    assert _git_version(repo) is None


def test_git_version_none_on_too_few_parts(tmp_path: Path, monkeypatch) -> None:
    repo = _bare_git_repo(tmp_path)
    monkeypatch.setattr(
        "strata.core.doctor.gitio.run",
        lambda *a, **kw: SimpleNamespace(returncode=0, stdout="git"),
    )
    assert _git_version(repo) is None


def test_git_version_none_on_unparseable_numbers(tmp_path: Path, monkeypatch) -> None:
    repo = _bare_git_repo(tmp_path)
    monkeypatch.setattr(
        "strata.core.doctor.gitio.run",
        lambda *a, **kw: SimpleNamespace(returncode=0, stdout="git version abc.def.ghi"),
    )
    assert _git_version(repo) is None


def test_git_version_parses_real_output(tmp_path: Path) -> None:
    repo = _bare_git_repo(tmp_path)
    version = _git_version(repo)
    assert version is not None
    assert version >= (2, 0)


def test_run_doctor_reports_everything_missing_without_fix(tmp_path: Path) -> None:
    repo = _bare_git_repo(tmp_path)
    report = run_doctor(repo, fix=False)
    assert not report.healthy
    messages = [f.message for f in report.findings]
    assert any("core.hooksPath is not set" in m for m in messages)
    assert any("is missing" in m for m in messages)
    assert any("is not installed" in m for m in messages)
    assert not (repo.path(*HOOKS_DIR.split("/")) / "pre-commit").exists()


def test_run_doctor_fixes_everything(tmp_path: Path) -> None:
    repo = _bare_git_repo(tmp_path)
    report = run_doctor(repo, fix=True)
    assert report.healthy
    assert any(f.fixed for f in report.findings)
    assert gitio.get_config(repo.root, "core.hooksPath") == HOOKS_DIR
    for hook_name in ("pre-commit", "commit-msg", "post-merge", "post-checkout"):
        assert (repo.path(*HOOKS_DIR.split("/")) / hook_name).exists()
    for driver_name, cfg in MERGE_DRIVERS.items():
        assert gitio.get_config(repo.root, f"merge.{driver_name}.driver") == cfg["driver"]

    # Running doctor again with fix=True should now report everything already ok.
    second_report = run_doctor(repo, fix=True)
    assert second_report.healthy
    assert not any(f.fixed for f in second_report.findings)
