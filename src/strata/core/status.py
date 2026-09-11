"""`strata status`: the repository dashboard.

Full fidelity with docs/spec/10-cli.md §4 depends on dedup, screening, and
analysis state that land in M1/M2. This is the M0 slice: project identity,
actors, commit count, working-tree cleanliness, criteria version, and record
count.
"""

from __future__ import annotations

from dataclasses import dataclass

from strata import gitio
from strata.core.canon import load_yaml_str
from strata.core.repo import Repo


@dataclass
class StatusReport:
    title: str
    slug: str
    actor_count: int
    commit_count: int
    is_clean: bool
    criteria_version: int
    record_count: int


def _count_ndjson_lines(path) -> int:  # type: ignore[no-untyped-def]
    if not path.exists():
        return 0
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


def _read_criteria_version(repo: Repo) -> int:
    path = repo.path("protocol", "criteria.yaml")
    if not path.exists():
        return 0
    data = load_yaml_str(path.read_text(encoding="utf-8"))
    if not data:
        return 0
    return int(data.get("version", 0))


def compute_status(repo: Repo) -> StatusReport:
    project = repo.config.get("project", {})
    actors = repo.config.get("actors", [])
    commits = gitio.log(repo.root)
    return StatusReport(
        title=project.get("title", "(untitled)"),
        slug=project.get("slug", ""),
        actor_count=len(actors),
        commit_count=len(commits),
        is_clean=not gitio.is_dirty(repo.root),
        criteria_version=_read_criteria_version(repo),
        record_count=_count_ndjson_lines(repo.path("records", "records.ndjson")),
    )
