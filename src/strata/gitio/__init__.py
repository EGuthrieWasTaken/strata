"""The only module that shells out to git.

Implements openspec:git-integration and the module boundary in
openspec:architecture#only-gitio-invokes-git: everything else in `strata`
operates on the working tree, never on git directly. This keeps the tool
usable on a non-git directory for testing and makes the git dependency
swappable.
"""

from __future__ import annotations

import io
import os
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

GIT_TIMEOUT_SECONDS = 60


class GitError(RuntimeError):
    def __init__(self, args: list[str], returncode: int, stderr: str) -> None:
        self.args_ = args
        self.returncode = returncode
        self.stderr = stderr
        super().__init__(f"git {' '.join(args)} failed ({returncode}): {stderr.strip()}")


_SCRIPT_NAMES = ("strata", "strata.exe")


def _own_script_dir() -> Path | None:
    """The directory of the `strata` script this process is running as, if it can be found."""
    candidates = [
        Path(os.path.abspath(sys.argv[0])),
        *(Path(sys.executable).parent / name for name in _SCRIPT_NAMES),
    ]
    for candidate in candidates:
        if candidate.name in _SCRIPT_NAMES and candidate.is_file():
            return candidate.parent
    return None


def _env_for_hooks() -> dict[str, str] | None:
    """The environment to run git in, or `None` to inherit this process's.

    The hooks git triggers call `strata` by name (openspec:git-integration#versioned-hooks).
    When this process was started by a path that is not on `PATH` (`/opt/venv/bin/strata ...`,
    an environment that is not activated), they would fail with `strata: not found` and block
    the commit. So when `strata` does not resolve, the directory of the running script goes on
    the *end* of `PATH` for git: it is found only if nothing earlier on `PATH` is, so it never
    shadows a tool the user has.
    """
    if shutil.which("strata") is not None:
        return None
    directory = _own_script_dir()
    if directory is None:
        return None
    env = dict(os.environ)
    env["PATH"] = os.pathsep.join(filter(None, [env.get("PATH"), str(directory)]))
    return env


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
        env=_env_for_hooks(),
    )
    if check and result.returncode != 0:
        # `git commit` says "nothing to commit" on stdout, so a failure can have an empty stderr.
        raise GitError(args, result.returncode, result.stderr.strip() or result.stdout)
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


def has_staged_changes(path: Path) -> bool:
    """Whether the index differs from HEAD, i.e. whether a commit would record anything."""
    return run(["diff", "--cached", "--quiet"], cwd=path, check=False).returncode == 1


def is_dirty(path: Path) -> bool:
    result = run(["status", "--porcelain"], cwd=path)
    return bool(result.stdout.strip())


def has_changes(path: Path, pathspecs: list[str]) -> bool:
    """Whether any of `pathspecs` is modified, staged, or untracked."""
    result = run(["status", "--porcelain", "--", *pathspecs], cwd=path)
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


def resolve_commit(path: Path, ref: str) -> str:
    """The full commit id `ref` names; a ref starting with `-` is refused, never given to git."""
    if ref.startswith("-"):
        raise GitError(["rev-parse", ref], 128, f"not a valid revision: {ref}")
    result = run(["rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"], cwd=path, check=False)
    if result.returncode != 0 or not result.stdout.strip():
        raise GitError(["rev-parse", ref], 128, f"unknown revision: {ref}")
    return result.stdout.strip()


def export_tree(path: Path, commit: str, dest: Path) -> None:
    """Write the files of `commit` into `dest` without touching the working tree or the index."""
    archived = subprocess.run(
        ["git", "archive", "--format=tar", commit],
        cwd=path,
        capture_output=True,
        timeout=GIT_TIMEOUT_SECONDS,
    )
    if archived.returncode != 0:
        raise GitError(
            ["archive", commit], archived.returncode, archived.stderr.decode("utf-8", "replace")
        )
    with tarfile.open(fileobj=io.BytesIO(archived.stdout)) as tar:
        tar.extractall(dest, filter="data")


def commits_adding(path: Path, needle: str, pathspecs: list[str]) -> list[str]:
    """Commits that introduced `needle` under `pathspecs`, oldest first (`git log -S`).

    A needle that is not a string git can search for as given (it starts with `-`) is refused.
    """
    if not needle or needle.startswith("-"):
        return []
    result = run(
        ["log", "--reverse", "--format=%H", f"-S{needle}", "--", *pathspecs], cwd=path, check=False
    )
    if result.returncode != 0:
        return []
    return [line for line in result.stdout.splitlines() if line]


def commit_message(path: Path, commit: str) -> str:
    """The full message of `commit`."""
    return run(["log", "-1", "--format=%B", commit], cwd=path).stdout.strip()
