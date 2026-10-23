"""Builders for reporting tests: a review that went through the real import, screening and
retrieval functions, so the counts are those a user's repository would have."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from strata.core import records as records_mod
from strata.core.ids import report_id
from strata.core.repo import Repo
from strata.ingest.pipeline import import_file
from strata.protocol import criteria as criteria_mod
from strata.protocol import retrieval, screening
from strata.protocol import studies as studies_mod
from strata.protocol.searches import add_search
from tests.unit._m3 import init_review

ACTORS = ("ethan", "sam")


def paper(n: int, *, title: str | None = None, year: int | None = None) -> dict[str, Any]:
    """A fixture paper whose identity depends only on `n`, so two files that both contain
    `paper(3)` carry the same record."""
    return {
        "id": str(n),
        "type": "article-journal",
        "title": title or f"Spaced practice and recall, experiment {n}",
        "author": [{"family": f"Author{n}", "given": "A."}],
        "issued": {"date-parts": [[year or 2000 + n % 20]]},
        "container-title": "Journal of Testing",
        "DOI": f"10.5555/m5.{n}",
        "abstract": f"Abstract of paper {n}.",
    }


def write_csl(tmp_path: Path, name: str, numbers: list[int]) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps([paper(n) for n in numbers]), encoding="utf-8")
    return path


def add_criteria(repo: Repo) -> dict[str, str]:
    """Two inclusion and three exclusion criteria, all applying at both stages."""
    found: dict[str, str] = {}
    for kind, label in (
        ("inclusion", "Human participants"),
        ("inclusion", "Reports a recall outcome"),
        ("exclusion", "Wrong population"),
        ("exclusion", "No comparison group"),
        ("exclusion", "Not peer reviewed"),
    ):
        criterion = criteria_mod.add_criterion(
            repo, kind=kind, label=label, definition=label + ".",  # type: ignore[arg-type]
            applies_at=["title-abstract", "full-text"], actor="ethan", rationale="Protocol.",
        )  # fmt: skip
        found[label] = str(criterion["id"])
    return found


def search(repo: Repo, database: str, platform: str = "Ovid") -> str:
    record = add_search(
        repo, database=database, platform=platform, executed="2026-01-05", executed_by="ethan",
        query=f"spaced practice AND recall ({database})",
    )  # fmt: skip
    return str(record["id"])


def import_into(repo: Repo, tmp_path: Path, name: str, numbers: list[int], **where: str) -> None:
    import_file(repo, write_csl(tmp_path, name, numbers), imported_by="ethan", **where)


def import_papers(
    repo: Repo, tmp_path: Path, name: str, papers: list[dict[str, Any]], **where: str
) -> None:
    path = tmp_path / name
    path.write_text(json.dumps(papers), encoding="utf-8")
    import_file(repo, path, imported_by="ethan", **where)


def decide(
    repo: Repo, stage: str, record_ids: list[str], decision: str, cited: list[str] | None = None
) -> None:
    for record_id in record_ids:
        for actor in ACTORS:
            screening.record_screen_decision(
                repo, stage=stage, record_id=record_id, decision=decision,  # type: ignore[arg-type]
                actor=actor, cited=cited,
            )  # fmt: skip


def retrieve(repo: Repo, record_ids: list[str], reason: str | None = None) -> None:
    for record_id in record_ids:
        if reason is None:
            retrieval.record_retrieval(
                repo, report=report_id(record_id), status="retrieved", actor="ethan",
                source="institutional-access", version="version-of-record",
                locator={"url": f"https://example.org/{record_id}"},
            )  # fmt: skip
        else:
            retrieval.record_retrieval(
                repo, report=report_id(record_id), status="not-retrieved", actor="ethan",
                reason=reason,
            )  # fmt: skip


def merge_duplicates(repo: Repo) -> int:
    """Run the deduplication pass and merge everything it queues for review; returns how many."""
    from strata.dedup import engine as dedup_engine

    outcome = dedup_engine.run_dedup(repo, actor="ethan")
    for candidate in outcome.review_queue:
        dedup_engine.apply_review_decision(
            repo, record_a_id=candidate.record_a, record_b_id=candidate.record_b,
            result=candidate.result, decision="merge", actor="ethan",
        )  # fmt: skip
    return len(outcome.auto_merged) + len(outcome.review_queue)


def canonical_ids(repo: Repo) -> list[str]:
    return sorted(
        r["id"]
        for r in records_mod.read_records(repo)
        if r.get("strata", {}).get("canonical", True)
    )


def finished_review(tmp_path: Path, *, finish: bool = True) -> tuple[Repo, dict[str, str]]:
    """Searches that overlap, a register, two other methods, and a complete screening.

    Rows imported: MEDLINE 10 (papers 1-10), Embase 8 (papers 8-15; 8, 9, 10 repeat MEDLINE's),
    CENTRAL 4 (papers 16-19), citation searching 3 (papers 1, 20, 21; paper 1 repeats MEDLINE's),
    website 2 (papers 22, 23). 27 rows identified, 4 of them repeats, 23 records screened.
    Title/abstract: 6 excluded, 17 sought. Of those, 15 retrieved and 2 not; at full text 3 are
    excluded for "No comparison group", 1 for "Not peer reviewed" and 11 included, two of which
    report one study (10 studies). With `finish=False` the last 3 reports are still to retrieve.
    """
    repo = init_review(tmp_path, actors=("sam",))
    criteria = add_criteria(repo)
    medline, embase = search(repo, "MEDLINE"), search(repo, "Embase")
    central = search(repo, "CENTRAL", "Cochrane")
    import_into(repo, tmp_path, "medline.json", list(range(1, 11)), search_id=medline)
    import_into(repo, tmp_path, "embase.json", list(range(8, 16)), search_id=embase)
    import_into(repo, tmp_path, "central.json", list(range(16, 20)), search_id=central)
    import_into(repo, tmp_path, "cites.json", [1, 20, 21], via="citation-searching")
    import_into(repo, tmp_path, "web.json", [22, 23], via="website")
    ids = canonical_ids(repo)
    kept = ids[6:]
    decide(repo, "title-abstract", ids[:6], "exclude", [criteria["Wrong population"]])
    decide(repo, "title-abstract", kept, "include")
    assessed = kept[:15] if finish else kept[:12]
    retrieve(repo, assessed)
    if finish:
        retrieve(repo, kept[15:], reason="no-access")
    decide(repo, "full-text", assessed[:3], "exclude", [criteria["No comparison group"]])
    decide(repo, "full-text", assessed[3:4], "exclude", [criteria["Not peer reviewed"]])
    decide(repo, "full-text", assessed[4:], "include")
    studies_mod.group_reports(
        repo, reports=[report_id(assessed[4]), report_id(assessed[5])], actor="ethan",
        rationale="Same trial, reported twice.",
    )  # fmt: skip
    return repo, criteria
