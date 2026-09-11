"""`strata log`: a domain-level `git log` read through `Strata-` trailers.

Implements docs/spec/04-git-integration.md §6.2.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from strata import gitio
from strata.core.repo import Repo

_TRAILER_PREFIX = "Strata-"
_UNIT_SEP = "\x1f"
_RECORD_SEP = "\x1e"


@dataclass
class DomainCommit:
    sha: str
    subject: str
    trailers: dict[str, str] = field(default_factory=dict)


def _parse_trailers(body: str) -> dict[str, str]:
    trailers: dict[str, str] = {}
    for line in body.splitlines():
        if line.startswith(_TRAILER_PREFIX) and ":" in line:
            key, _, value = line.partition(":")
            trailers[key[len(_TRAILER_PREFIX) :]] = value.strip()
    return trailers


def domain_log(
    repo: Repo,
    *,
    criteria_only: bool = False,
    stage: str | None = None,
    actor: str | None = None,
) -> list[DomainCommit]:
    result = gitio.run(
        ["log", f"--format=%H{_UNIT_SEP}%B{_RECORD_SEP}"], cwd=repo.root, check=False
    )
    if result.returncode != 0 or not result.stdout:
        return []

    commits: list[DomainCommit] = []
    for record in result.stdout.split(_RECORD_SEP):
        record = record.strip("\n")
        if not record:
            continue
        sha, _, body = record.partition(_UNIT_SEP)
        subject = body.splitlines()[0] if body else ""
        commits.append(DomainCommit(sha=sha, subject=subject, trailers=_parse_trailers(body)))

    if criteria_only:
        commits = [c for c in commits if c.trailers.get("Op") == "criteria-change"]
    if stage:
        commits = [c for c in commits if c.trailers.get("Stage") == stage]
    if actor:
        commits = [c for c in commits if c.trailers.get("Actor") == actor]
    return commits
