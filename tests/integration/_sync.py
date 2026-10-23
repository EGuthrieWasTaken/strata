"""Fixtures for `strata sync` tests: a shared remote and two collaborators' clones."""

# ruff: noqa: E501

from __future__ import annotations

from pathlib import Path
from typing import Any

from typer.testing import CliRunner

from strata import gitio
from strata.cli.main import app
from strata.core.actor import add_actor
from strata.core.init import init_repository
from strata.core.repo import Repo, open_repo
from strata.protocol import criteria as criteria_mod
from strata.protocol import screening as screening_mod
from tests.unit._m5 import import_into, search

runner = CliRunner()
WHY = ("--why", "Working on the shared review.")


def commit(repo: Repo, message: str, actor: str = "ethan") -> None:
    gitio.add_all(repo.root)
    gitio.commit(repo.root, f"{message}\n\nStrata-Op: test\nStrata-Actor: {actor}")


def cli(repo: Repo, *args: str, code: int = 0) -> Any:
    result = runner.invoke(app, [*WHY, "-C", str(repo.root), *args])
    assert result.exit_code == code, result.output
    return result


def shared_review(tmp_path: Path, *, records: int = 8) -> tuple[Repo, Repo, Path]:
    """A review with two actors, criteria and `records` imported papers, pushed to a bare remote and
    cloned twice (with merge drivers and hooks installed): `(ethan's clone, sam's clone, remote)`."""
    seed_root = tmp_path / "seed"
    init_repository(seed_root, title="Shared review", actor_handle="ethan", actor_name="Ethan")
    seed = open_repo(seed_root)
    add_actor(seed, handle="sam", name="Sam", role="screener")
    seed = open_repo(seed_root)
    for kind, label in (("inclusion", "Human participants"), ("exclusion", "Wrong population")):
        criteria_mod.add_criterion(
            seed, kind=kind, label=label, definition=label + ".",  # type: ignore[arg-type]
            applies_at=["title-abstract", "full-text"], actor="ethan", rationale="Protocol.",
        )  # fmt: skip
    import_into(
        seed,
        tmp_path,
        "export.json",
        list(range(1, records + 1)),
        search_id=search(seed, "MEDLINE"),
    )
    commit(seed, "seed: the shared review")
    bare = tmp_path / "remote.git"
    gitio.run(["init", "--bare", "--initial-branch=main", str(bare)], cwd=tmp_path)
    gitio.run(["remote", "add", "origin", str(bare)], cwd=seed.root)
    gitio.run(["push", "-u", "origin", "HEAD:main"], cwd=seed.root)
    clones = []
    for name in ("ethan-clone", "sam-clone"):
        path = tmp_path / name
        gitio.clone(str(bare), path)
        gitio.run(["checkout", "-B", "main", "origin/main"], cwd=path)
        result = runner.invoke(app, ["-C", str(path), "doctor", "--fix"])
        assert result.exit_code == 0, result.output
        clones.append(open_repo(path))
    return clones[0], clones[1], bare


def record_ids(repo: Repo) -> list[str]:
    from strata.core import records as records_mod

    return sorted(r["id"] for r in records_mod.read_records(repo))


def screen(
    repo: Repo,
    actor: str,
    ids: list[str],
    decision: str = "include",
    cited: list[str] | None = None,
) -> None:
    for record_id in ids:
        screening_mod.record_screen_decision(
            repo, stage="title-abstract", record_id=record_id, decision=decision,  # type: ignore[arg-type]
            actor=actor, cited=cited,
        )  # fmt: skip
    commit(repo, f"screen: {actor} screened {len(ids)} records", actor)
