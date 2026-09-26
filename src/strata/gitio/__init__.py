"""The only module that shells out to git.

Implements openspec:git-integration and the module boundary in
openspec:architecture#only-gitio-invokes-git: everything else in `strata`
operates on the working tree, never on git directly. This keeps the tool
usable on a non-git directory for testing and makes the git dependency
swappable.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

GIT_TIMEOUT_SECONDS = 60


class GitError(RuntimeError):
    def __init__(self, args: list[str], returncode: int, stderr: str) -> None:
        self.args_ = args
        self.returncode = returncode
        self.stderr = stderr
        super().__init__(f"git {' '.join(args)} failed ({returncode}): {stderr.strip()}")


def run(
    args: list[str],
    *,
    cwd: Path,
    check: bool = True,
    timeout: float = GIT_TIMEOUT_SECONDS,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if check and result.returncode != 0:
        raise GitError(args, result.returncode, result.stderr)
    return result


def is_git_repo(path: Path) -> bool:
    result = run(["rev-parse", "--is-inside-work-tree"], cwd=path, check=False)
    return result.returncode == 0 and result.stdout.strip() == "true"


def init(path: Path, *, initial_branch: str = "main") -> None:
    path.mkdir(parents=True, exist_ok=True)
    run(["init", "--initial-branch", initial_branch], cwd=path)


def clone(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    run(["clone", url, str(dest)], cwd=dest.parent)


def add(path: Path, pathspecs: list[str]) -> None:
    run(["add", *pathspecs], cwd=path)


def add_all(path: Path) -> None:
    run(["add", "-A"], cwd=path)


def is_dirty(path: Path) -> bool:
    result = run(["status", "--porcelain"], cwd=path)
    return bool(result.stdout.strip())


def commit(path: Path, message: str, *, allow_empty: bool = False) -> str:
    args = ["commit", "-m", message]
    if allow_empty:
        args.append("--allow-empty")
    run(args, cwd=path)
    return current_commit(path)


def current_commit(path: Path) -> str:
    return run(["rev-parse", "HEAD"], cwd=path).stdout.strip()


def current_branch(path: Path) -> str:
    return run(["rev-parse", "--abbrev-ref", "HEAD"], cwd=path).stdout.strip()


def set_config(path: Path, key: str, value: str, *, local: bool = True) -> None:
    scope = ["--local"] if local else []
    run(["config", *scope, key, value], cwd=path)


def get_config(path: Path, key: str) -> str | None:
    result = run(["config", "--get", key], cwd=path, check=False)
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def fetch(path: Path, remote: str = "origin") -> subprocess.CompletedProcess[str]:
    return run(["fetch", remote], cwd=path)


def log(path: Path, *, max_count: int | None = None, fmt: str = "%H") -> list[str]:
    args = ["log", f"--format={fmt}"]
    if max_count is not None:
        args.append(f"-{max_count}")
    result = run(args, cwd=path, check=False)
    if result.returncode != 0:
        return []
    return [line for line in result.stdout.splitlines() if line]
