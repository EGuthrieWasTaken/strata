"""Shared builders for the M3 (full text, studies, extraction, risk of bias) tests.

Everything writes through the real service functions where one exists, and straight to the
records file where the test is not about import, so a test stays fast and focused.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from strata.core.actor import add_actor
from strata.core.init import init_repository
from strata.core.repo import Repo, open_repo
from strata.protocol.screening import record_screen_decision


def rec(n: int) -> str:
    """The n-th fixture record id (16 characters after the prefix, as real ids have)."""
    return f"rec_{n:016d}"


def rpt(n: int) -> str:
    return f"rpt_{n:016d}"


def init_review(tmp_path: Path, *, actors: tuple[str, ...] = ("sam",)) -> Repo:
    root = tmp_path / "review"
    init_repository(root, title="Spacing review", actor_handle="ethan", actor_name="Ethan")
    repo = open_repo(root)
    for handle in actors:
        add_actor(repo, handle=handle, name=handle.title(), role="screener")
    return open_repo(root)


def record(n: int, **fields: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": rec(n),
        "type": "article-journal",
        "title": f"Title {n}",
        "author": [{"family": f"Author{n}", "given": "A."}],
        "issued": {"date-parts": [[2000 + n]]},
        "container-title": "Journal of Testing",
        "DOI": f"10.1000/test.{n}",
        "strata": {
            "canonical_key": f"sig:{n}",
            "canonical": True,
            "sources": [{"import": "imp_01arz3ndektsv4rrffq69g5fav", "database": "manual"}],
        },
    }
    base.update(fields)
    return base


def add_records(repo: Repo, count: int | list[dict[str, Any]]) -> list[str]:
    """Write `count` default records (or the given record dicts); return their ids."""
    records = [record(i) for i in range(1, count + 1)] if isinstance(count, int) else count
    path = repo.path("records", "records.ndjson")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    return [r["id"] for r in records]


def decide(
    repo: Repo,
    stage: str,
    record_ids: list[str],
    decision: str = "include",
    actors: tuple[str, ...] = ("ethan", "sam"),
) -> None:
    for record_id in record_ids:
        for actor in actors:
            record_screen_decision(
                repo,
                stage=stage,
                record_id=record_id,
                decision=decision,
                actor=actor,  # type: ignore[arg-type]
            )
