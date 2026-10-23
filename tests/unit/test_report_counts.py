"""PRISMA counts and their reconciliation identities (openspec:prisma-reporting)."""

# ruff: noqa: E501
from __future__ import annotations

import json
from pathlib import Path

import pytest

from strata.report import counts as counts_mod
from tests.unit._m5 import finished_review


def test_a_finished_review_closes_every_identity(tmp_path: Path) -> None:
    repo, _ = finished_review(tmp_path)
    counts = counts_mod.compute(repo)
    assert counts.reconciled, counts.failures
    counts_mod.require_reconciled(counts)
    t = counts.totals
    assert (t.identified, t.duplicates_removed, t.records_screened) == (27, 4, 23)
    assert (t.records_excluded_tiab, t.reports_sought) == (6, 17)
    assert (t.reports_retrieved, t.reports_not_retrieved, t.reports_assessed) == (15, 2, 15)
    assert (t.reports_excluded_ft, t.reports_included) == (4, 11)
    assert t.marked_ineligible_by_automation == 0 and t.removed_other == 0
    assert t.removed_before_screening == 4
    assert counts.complete and counts.stale_decisions == 0


def test_identification_is_partitioned_by_search_register_and_method(tmp_path: Path) -> None:
    repo, _ = finished_review(tmp_path)
    box = counts_mod.compute(repo).identification
    assert box["databases"]["total"] == 18 and box["registers"]["total"] == 4
    assert sorted(box["databases"]["by_search"].values()) == [8, 10]
    assert box["other_methods"] == {
        "total": 5, "by_via": {"citation-searching": 3, "website": 2},
    }  # fmt: skip
    assert box["identified_total"] == 27


def test_every_origin_funnel_closes_and_they_sum_to_the_total(tmp_path: Path) -> None:
    repo, _ = finished_review(tmp_path)
    counts = counts_mod.compute(repo)
    assert set(counts.by_origin) == {"searches", "citation-searching", "website"}
    searches = counts.by_origin["searches"]
    assert (searches.identified, searches.duplicates_removed, searches.records_screened) == (
        22,
        3,
        19,
    )
    assert counts.by_origin["citation-searching"].duplicates_removed == 1  # paper 1 again
    assert counts.by_origin["website"].records_screened == 2
    other = counts.other_methods
    assert (other.identified, other.records_screened) == (5, 4)
    assert (
        sum(f.reports_included for f in counts.by_origin.values()) == counts.totals.reports_included
    )


def test_exclusion_reasons_use_criterion_labels_largest_first(tmp_path: Path) -> None:
    repo, criteria = finished_review(tmp_path)
    reasons = counts_mod.compute(repo).exclusion_reasons
    assert [(r.id, r.label, r.count) for r in reasons] == [
        (criteria["No comparison group"], "No comparison group", 3),
        (criteria["Not peer reviewed"], "Not peer reviewed", 1),
    ]


def test_studies_group_reports(tmp_path: Path) -> None:
    repo, _ = finished_review(tmp_path)
    counts = counts_mod.compute(repo)
    assert counts.studies_included == 10 and counts.reports_of_included_studies == 11
    assert counts.not_retrieved_reasons == {"no-access": 2}


def test_a_review_in_progress_still_closes_and_is_not_complete(tmp_path: Path) -> None:
    repo, _ = finished_review(tmp_path, finish=False)
    counts = counts_mod.compute(repo)
    assert counts.reconciled, counts.failures
    t = counts.totals
    assert t.awaiting_retrieval == 5 and t.reports_not_retrieved == 0
    assert not counts.complete
    assert counts.to_dict()["complete"] is False


def test_a_stale_decision_makes_the_counts_incomplete(tmp_path: Path) -> None:
    from strata.protocol import criteria as criteria_mod

    repo, _ = finished_review(tmp_path)
    criteria_mod.add_criterion(
        repo, kind="exclusion", label="Older than 2005", definition="Published before 2005.",
        applies_at=["title-abstract", "full-text"], actor="ethan", rationale="Protocol amendment.",
    )  # fmt: skip
    counts = counts_mod.compute(repo)
    assert counts.stale_decisions > 0 and not counts.complete and counts.reconciled


def test_records_no_import_accounts_for_break_the_identity(tmp_path: Path) -> None:
    repo, _ = finished_review(tmp_path)
    records_path = repo.path("records", "records.ndjson")
    rows = [json.loads(line) for line in records_path.read_text().splitlines()]
    stray = json.loads(json.dumps(rows[0]))
    stray["id"] = "rec_" + "0" * 16
    stray["strata"]["canonical_key"] = "sig:stray"
    records_path.write_text(
        "\n".join(json.dumps(r) for r in [*rows, stray]) + "\n", encoding="utf-8"
    )
    counts = counts_mod.compute(repo)
    assert not counts.reconciled
    assert any("duplicates_removed" in f for f in counts.failures)
    with pytest.raises(counts_mod.CountReconcileError) as raised:
        counts_mod.require_reconciled(counts)
    assert raised.value.code == "E_COUNT_RECONCILE" and "duplicates_removed" in str(raised.value)


def test_counts_json_is_deterministic_and_records_the_assertions(tmp_path: Path) -> None:
    repo, _ = finished_review(tmp_path)
    first = counts_mod.regenerate_counts_json(repo)
    assert counts_mod.regenerate_counts_json(repo) == first
    doc = json.loads(first)
    assert doc["reconciled"] is True and doc["totals"]["marked_ineligible_by_automation"] == 0
    assert all(a["holds"] for a in doc["assertions"]) and len(doc["assertions"]) > 20
    assert repo.path("derived", "counts.json").read_text() == first
    assert doc["by_origin"]["searches"]["identified"] == 22


def test_an_empty_review_has_all_zero_counts(tmp_path: Path) -> None:
    from tests.unit._m3 import init_review

    counts = counts_mod.compute(init_review(tmp_path))
    assert counts.reconciled and counts.totals.identified == 0 and counts.complete


def test_verify_reports_a_broken_identity_as_e_count_reconcile(tmp_path: Path) -> None:
    from strata.core.verify import verify_repository

    repo, _ = finished_review(tmp_path)
    assert not [i for i in verify_repository(repo).issues if i.code == "E_COUNT_RECONCILE"]
    records_path = repo.path("records", "records.ndjson")
    rows = [json.loads(line) for line in records_path.read_text().splitlines()]
    stray = json.loads(json.dumps(rows[0]))
    stray["id"] = "rec_" + "0" * 16
    stray["strata"]["canonical_key"] = "sig:stray"
    records_path.write_text(
        "\n".join(json.dumps(r) for r in [*rows, stray]) + "\n", encoding="utf-8"
    )
    report = verify_repository(repo)
    broken = [i for i in report.issues if i.code == "E_COUNT_RECONCILE"]
    assert broken and not report.ok and "duplicates_removed" in broken[0].message


def test_records_merged_away_are_duplicates_removed_from_the_origin_that_found_them(
    tmp_path: Path,
) -> None:
    from tests.unit._m3 import init_review
    from tests.unit._m5 import import_papers, merge_duplicates, paper, search

    repo = init_review(tmp_path)
    import_papers(repo, tmp_path, "a.json", [paper(3), paper(4)], search_id=search(repo, "MEDLINE"))
    variant = {**paper(3), "DOI": ""}  # the same paper exported without its DOI: a new record id
    import_papers(repo, tmp_path, "b.json", [variant], via="website")
    assert merge_duplicates(repo) == 1
    counts = counts_mod.compute(repo)
    assert counts.reconciled, counts.failures
    assert counts.totals.identified == 3 and counts.totals.duplicates_removed == 1
    assert counts.totals.records_screened == 2
    assert (
        counts.by_origin["website"].duplicates_removed == 1
    )  # found by a website, kept as MEDLINE's
    assert counts.by_origin["searches"].records_screened == 2
