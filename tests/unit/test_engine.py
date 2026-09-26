"""Unit tests for strata.dedup.engine, per
openspec:deduplication#sticky-reversible-conservative-explainable,
openspec:deduplication#thresholds-and-actions, openspec:deduplication#review-queue."""

from __future__ import annotations

from pathlib import Path

import pytest

from strata.core.aliases import read_aliases
from strata.core.events import append_new_event, read_events
from strata.core.init import init_repository
from strata.core.records import read_records, write_records
from strata.core.repo import Repo, open_repo
from strata.dedup.engine import (
    apply_review_decision,
    judged_pairs,
    preview_dedup,
    run_dedup,
    source_trust_order,
    thresholds,
    undo_merge,
)
from strata.dedup.scoring import score_pair


def _repo(tmp_path: Path) -> Repo:
    root = tmp_path / "review"
    init_repository(root, title="T", actor_handle="ethan", actor_name="Ethan")
    return open_repo(root)


def _record(record_id: str, database: str = "manual", **fields) -> dict:
    return {
        "id": record_id,
        "type": "article-journal",
        "title": fields.pop("title", "A Title"),
        "strata": {
            "canonical_key": f"sig:{record_id}",
            "canonical": True,
            "sources": [{"import": "imp_01arz3ndektsv4rrffq69g5fav", "database": database}],
        },
        **fields,
    }


def test_thresholds_reads_config(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    auto, review = thresholds(repo, strict=False)
    assert auto == 0.95
    assert review == 0.80


def test_thresholds_strict_auto_merge_one_review_zero(tmp_path: Path) -> None:
    # openspec:deduplication#thresholds-and-actions: --strict means only an exact/DOI match
    # auto-merges, and every
    # other blocked pair is queued for review rather than silently dropped
    # -- see the docstring on `thresholds()` for why that isn't literally
    # (1.0, 1.0).
    repo = _repo(tmp_path)
    assert thresholds(repo, strict=True) == (1.0, 0.0)


def test_source_trust_order_reads_config(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    assert source_trust_order(repo) == [
        "crossref",
        "pubmed",
        "scopus",
        "wos",
        "embase",
        "ebsco",
        "manual",
    ]


def test_run_dedup_auto_merges_doi_match(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    a = _record("rec_0000000000000001", DOI="10.1000/aaa")
    b = _record("rec_0000000000000002", DOI="10.1000/aaa", author=[{"family": "Cepeda"}])
    write_records(repo, [a, b])

    outcome = run_dedup(repo, actor="ethan")

    assert outcome.candidate_pairs_considered == 1
    assert len(outcome.auto_merged) == 1
    assert outcome.review_queue == []

    records = {r["id"]: r for r in read_records(repo)}
    canonical_id, absorbed_id = outcome.auto_merged[0]
    assert records[canonical_id]["strata"]["canonical"] is True
    assert records[absorbed_id]["strata"]["canonical"] is False
    assert records[canonical_id]["author"] == [{"family": "Cepeda"}]

    events = read_events(repo.path("events", "dedup", "ethan.ndjson"))
    assert [e["ev"] for e in events] == ["dedup-merge"]
    assert events[0]["body"]["canonical"] == canonical_id
    assert events[0]["body"]["absorbed"] == absorbed_id
    assert events[0]["body"]["score"] == 1.0


def test_run_dedup_queues_pair_for_review(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    a = _record(
        "rec_0000000000000001",
        title="Spacing effects in learning: A meta-analysis",
        author=[{"family": "Cepeda"}, {"family": "Vul"}],
        **{"issued": {"date-parts": [[2008]]}},
    )
    b = _record(
        "rec_0000000000000002",
        title="Spacing effects in learning - A meta analysis",
        author=[{"family": "Cepeda"}, {"family": "Vul"}],
        **{"issued": {"date-parts": [[2008]]}},
    )
    write_records(repo, [a, b])

    outcome = run_dedup(repo, actor="ethan")

    assert outcome.auto_merged == []
    assert len(outcome.review_queue) == 1
    assert 0.80 <= outcome.review_queue[0].result.score < 0.95
    candidate = outcome.review_queue[0]
    assert {candidate.record_a, candidate.record_b} == {
        "rec_0000000000000001",
        "rec_0000000000000002",
    }
    # No event recorded yet -- a review candidate is not a decision.
    events_path = repo.path("events", "dedup", "ethan.ndjson")
    assert not events_path.exists() or read_events(events_path) == []


def test_run_dedup_ignores_pair_scoring_below_review_threshold(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    a = _record("rec_0000000000000001", title="Alpha paper about frogs")
    b = _record("rec_0000000000000002", title="A totally unrelated jazz history study")
    write_records(repo, [a, b])

    outcome = run_dedup(repo, actor="ethan")

    assert outcome.candidate_pairs_considered == 0  # not even blocked together
    assert outcome.auto_merged == []
    assert outcome.review_queue == []


def test_run_dedup_blocked_but_scores_distinct_is_a_no_op(tmp_path: Path) -> None:
    """A shared PMID (data error) blocks two genuinely distinct papers together;
    the low weighted score still yields no event and no queue entry
    (openspec:deduplication#thresholds-and-actions:
    absence is the default)."""
    repo = _repo(tmp_path)
    a = _record("rec_0000000000000001", title="Alpha paper about frogs", PMID="12345")
    b = _record(
        "rec_0000000000000002", title="A totally unrelated jazz history study", PMID="12345"
    )
    write_records(repo, [a, b])

    outcome = run_dedup(repo, actor="ethan")

    assert outcome.candidate_pairs_considered == 1
    assert outcome.auto_merged == []
    assert outcome.review_queue == []


def test_run_dedup_doi_conflict_goes_to_review_not_auto_merge(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    a = _record(
        "rec_0000000000000001",
        title="Spacing effects in learning",
        author=[{"family": "Cepeda"}, {"family": "Vul"}],
        DOI="10.1000/aaa",
        **{"issued": {"date-parts": [[2008]]}},
    )
    b = _record(
        "rec_0000000000000002",
        title="Spacing effects in learning",
        author=[{"family": "Cepeda"}, {"family": "Vul"}],
        DOI="10.1000/bbb",
        **{"issued": {"date-parts": [[2008]]}},
    )
    write_records(repo, [a, b])

    outcome = run_dedup(repo, actor="ethan")

    assert outcome.auto_merged == []
    assert len(outcome.review_queue) == 1
    assert outcome.review_queue[0].doi_conflict is True
    assert outcome.review_queue[0].result.score == 0.0  # the official score is still vetoed


def test_run_dedup_sticky_after_merge(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    a = _record("rec_0000000000000001", DOI="10.1000/aaa")
    b = _record("rec_0000000000000002", DOI="10.1000/aaa")
    write_records(repo, [a, b])

    first = run_dedup(repo, actor="ethan")
    assert len(first.auto_merged) == 1

    second = run_dedup(repo, actor="ethan")
    assert second.auto_merged == []
    assert second.candidate_pairs_considered == 0  # only one canonical record remains


def test_run_dedup_sticky_after_manual_distinct(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    a = _record(
        "rec_0000000000000001",
        title="Spacing effects in learning: A meta-analysis",
        author=[{"family": "Cepeda"}, {"family": "Vul"}],
        **{"issued": {"date-parts": [[2008]]}},
    )
    b = _record(
        "rec_0000000000000002",
        title="Spacing effects in learning - A meta analysis",
        author=[{"family": "Cepeda"}, {"family": "Vul"}],
        **{"issued": {"date-parts": [[2008]]}},
    )
    write_records(repo, [a, b])

    first = run_dedup(repo, actor="ethan")
    assert len(first.review_queue) == 1
    candidate = first.review_queue[0]

    apply_review_decision(
        repo,
        record_a_id=candidate.record_a,
        record_b_id=candidate.record_b,
        result=candidate.result,
        decision="distinct",
        actor="ethan",
    )

    second = run_dedup(repo, actor="ethan")
    assert second.review_queue == []  # the pair is now judged, never re-raised


def test_run_dedup_strict_doi_match_still_auto_merges(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    a = _record("rec_0000000000000001", DOI="10.1000/aaa", author=[{"family": "Cepeda"}])
    b = _record("rec_0000000000000002", DOI="10.1000/aaa")
    write_records(repo, [a, b])

    outcome = run_dedup(repo, actor="ethan", strict=True)

    # DOI match still scores exactly 1.0, which clears even a strict 1.0 threshold.
    assert len(outcome.auto_merged) == 1


def test_run_dedup_strict_routes_near_duplicate_to_review(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    # Same title/author/year, no DOI/journal/volume/page: title 0.50 + author
    # 0.20 + year 0.15 = 0.85, well short of a strict 1.0 auto-merge but
    # still above the (lowered) strict review floor, so it must be queued
    # rather than silently discarded.
    a = _record(
        "rec_0000000000000001",
        title="Learning and spacing effects",
        author=[{"family": "Cepeda"}, {"family": "Vul"}],
        issued={"date-parts": [[2008]]},
    )
    b = _record(
        "rec_0000000000000002",
        title="Learning and spacing effects",
        author=[{"family": "Cepeda"}, {"family": "Vul"}],
        issued={"date-parts": [[2008]]},
    )
    write_records(repo, [a, b])

    outcome = run_dedup(repo, actor="ethan", strict=True)

    assert outcome.auto_merged == []
    assert len(outcome.review_queue) == 1


def test_run_dedup_chain_of_three_merges_within_one_run(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    records = [_record(f"rec_000000000000000{i}", DOI="10.1000/same") for i in (1, 2, 3)]
    write_records(repo, records)

    outcome = run_dedup(repo, actor="ethan")

    assert len(outcome.auto_merged) == 2  # three records collapse to one canonical
    remaining = [r for r in read_records(repo) if r["strata"]["canonical"]]
    assert len(remaining) == 1
    assert len(remaining[0]["strata"]["absorbed"]) == 2


def test_apply_review_decision_merge(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    a = _record("rec_0000000000000001", DOI="10.1000/aaa")
    b = _record("rec_0000000000000002", DOI="10.1000/aaa")
    write_records(repo, [a, b])
    result = score_pair(a, b)

    apply_review_decision(
        repo,
        record_a_id="rec_0000000000000001",
        record_b_id="rec_0000000000000002",
        result=result,
        decision="merge",
        actor="ethan",
    )

    records = {r["id"]: r for r in read_records(repo)}
    canonical = [r for r in records.values() if r["strata"]["canonical"]]
    assert len(canonical) == 1
    events = read_events(repo.path("events", "dedup", "ethan.ndjson"))
    assert events[0]["ev"] == "dedup-merge"
    assert events[0]["body"]["method"] == "manual-review"


def test_apply_review_decision_distinct_leaves_records_untouched(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    a = _record("rec_0000000000000001")
    b = _record("rec_0000000000000002")
    write_records(repo, [a, b])
    result = score_pair(a, b)

    apply_review_decision(
        repo,
        record_a_id="rec_0000000000000001",
        record_b_id="rec_0000000000000002",
        result=result,
        decision="distinct",
        actor="ethan",
    )

    records = {r["id"]: r for r in read_records(repo)}
    assert records["rec_0000000000000001"]["strata"]["canonical"] is True
    assert records["rec_0000000000000002"]["strata"]["canonical"] is True
    events = read_events(repo.path("events", "dedup", "ethan.ndjson"))
    assert [e["ev"] for e in events] == ["dedup-distinct"]
    assert events[0]["body"] == {
        "a": "rec_0000000000000001",
        "b": "rec_0000000000000002",
        "score": result.score,
        "method": "manual-review",
    }


def test_undo_merge_restores_flag_and_removes_alias(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    a = _record("rec_0000000000000001", DOI="10.1000/aaa")
    b = _record("rec_0000000000000002", DOI="10.1000/aaa")
    write_records(repo, [a, b])

    outcome = run_dedup(repo, actor="ethan")
    canonical_id, absorbed_id = outcome.auto_merged[0]

    undo_merge(repo, canonical_id=canonical_id, absorbed_id=absorbed_id, actor="ethan")

    records = {r["id"]: r for r in read_records(repo)}
    assert records[absorbed_id]["strata"]["canonical"] is True
    assert read_aliases(repo) == []

    events = read_events(repo.path("events", "dedup", "ethan.ndjson"))
    assert events[-1]["ev"] == "dedup-unmerge"
    assert events[-1]["body"] == {"canonical": canonical_id, "restored": absorbed_id}


def test_undo_then_rerun_does_not_immediately_remerge(tmp_path: Path) -> None:
    """`dedup-unmerge` is sticky too: undo shouldn't be immediately undone by re-running."""
    repo = _repo(tmp_path)
    a = _record("rec_0000000000000001", DOI="10.1000/aaa")
    b = _record("rec_0000000000000002", DOI="10.1000/aaa")
    write_records(repo, [a, b])

    outcome = run_dedup(repo, actor="ethan")
    canonical_id, absorbed_id = outcome.auto_merged[0]
    undo_merge(repo, canonical_id=canonical_id, absorbed_id=absorbed_id, actor="ethan")

    second = run_dedup(repo, actor="ethan")
    assert second.auto_merged == []
    assert second.review_queue == []


def test_judged_pairs_reads_merge_distinct_and_unmerge(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    a = _record("rec_0000000000000001", DOI="10.1000/aaa")
    b = _record("rec_0000000000000002", DOI="10.1000/aaa")
    write_records(repo, [a, b])
    outcome = run_dedup(repo, actor="ethan")
    canonical_id, absorbed_id = outcome.auto_merged[0]
    assert judged_pairs(repo) == {tuple(sorted((canonical_id, absorbed_id)))}


def test_judged_pairs_ignores_events_from_other_domains(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    append_new_event(
        repo.path("events", "import", "ethan.ndjson"),
        ev="record-add",
        actor="ethan",
        body={"record": "rec_0000000000000001", "import_id": "imp_01arz3ndektsv4rrffq69g5fav"},
    )
    assert judged_pairs(repo) == set()


def test_preview_dedup_reports_would_be_auto_merge_without_writing(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    a = _record("rec_0000000000000001", DOI="10.1000/aaa")
    b = _record("rec_0000000000000002", DOI="10.1000/aaa")
    write_records(repo, [a, b])

    outcome = preview_dedup(repo)

    assert outcome.candidate_pairs_considered == 1
    assert len(outcome.auto_merged) == 1
    assert outcome.review_queue == []

    # Nothing was persisted: both records are still their own canonical,
    # no dedup event exists, and no alias was recorded.
    records = {r["id"]: r for r in read_records(repo)}
    assert records["rec_0000000000000001"]["strata"]["canonical"] is True
    assert records["rec_0000000000000002"]["strata"]["canonical"] is True
    events_path = repo.path("events", "dedup", "ethan.ndjson")
    assert not events_path.exists() or read_events(events_path) == []
    assert read_aliases(repo) == []


def test_preview_dedup_reports_review_queue_same_as_run_dedup(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    a = _record(
        "rec_0000000000000001",
        title="Spacing effects in learning: A meta-analysis",
        author=[{"family": "Cepeda"}, {"family": "Vul"}],
        **{"issued": {"date-parts": [[2008]]}},
    )
    b = _record(
        "rec_0000000000000002",
        title="Spacing effects in learning - A meta analysis",
        author=[{"family": "Cepeda"}, {"family": "Vul"}],
        **{"issued": {"date-parts": [[2008]]}},
    )
    write_records(repo, [a, b])

    preview = preview_dedup(repo)
    assert len(preview.review_queue) == 1
    preview_candidate = preview.review_queue[0]

    # Calling preview again is idempotent -- it never consumes the pair.
    second_preview = preview_dedup(repo)
    assert len(second_preview.review_queue) == 1

    real = run_dedup(repo, actor="ethan")
    assert len(real.review_queue) == 1
    real_candidate = real.review_queue[0]
    assert preview_candidate.record_a == real_candidate.record_a
    assert preview_candidate.record_b == real_candidate.record_b
    assert preview_candidate.result.score == real_candidate.result.score


def test_preview_dedup_does_not_consume_an_auto_merge_run_dedup_still_applies(
    tmp_path: Path,
) -> None:
    """Previewing must never be mistaken for judging a pair: calling
    `preview_dedup` first must not change what a subsequent real
    `run_dedup` does with the same pair."""
    repo = _repo(tmp_path)
    a = _record("rec_0000000000000001", DOI="10.1000/aaa")
    b = _record("rec_0000000000000002", DOI="10.1000/aaa")
    write_records(repo, [a, b])

    preview_dedup(repo)
    preview_dedup(repo)

    real = run_dedup(repo, actor="ethan")
    assert len(real.auto_merged) == 1
    events = read_events(repo.path("events", "dedup", "ethan.ndjson"))
    assert [e["ev"] for e in events] == ["dedup-merge"]


def test_preview_dedup_chain_of_three_matches_run_dedup(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    records = [_record(f"rec_000000000000000{i}", DOI="10.1000/same") for i in (1, 2, 3)]
    write_records(repo, records)

    preview = preview_dedup(repo)
    assert len(preview.auto_merged) == 2  # three records collapse to one canonical, dry-run

    # Nothing written: all three still canonical.
    records_after = {r["id"]: r for r in read_records(repo)}
    assert all(r["strata"]["canonical"] for r in records_after.values())


@pytest.mark.parametrize("decision", ["merge", "distinct"])
def test_apply_review_decision_accepts_both_decisions(tmp_path: Path, decision: str) -> None:
    repo = _repo(tmp_path)
    a = _record("rec_0000000000000001", DOI="10.1000/aaa")
    b = _record("rec_0000000000000002", DOI="10.1000/aaa")
    write_records(repo, [a, b])
    result = score_pair(a, b)
    apply_review_decision(
        repo,
        record_a_id="rec_0000000000000001",
        record_b_id="rec_0000000000000002",
        result=result,
        decision=decision,  # type: ignore[arg-type]
        actor="ethan",
    )
    assert judged_pairs(repo) == {("rec_0000000000000001", "rec_0000000000000002")}
