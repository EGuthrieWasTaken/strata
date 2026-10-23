"""The PRISMA 2020 flow diagram and its JSON (openspec:prisma-reporting#flow-diagram)."""

# ruff: noqa: E501
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from strata.report import counts as counts_mod
from strata.report import flow
from strata.report.counts import Reason
from tests.unit._m5 import finished_review

# The `data` keys of the template that ships with the PRISMA2020 R package (prisma-flowdiagram).
R_PACKAGE_KEYS = [
    "previous_studies", "previous_reports", "database_results", "database_specific_results",
    "register_results", "register_specific_results", "website_results", "organisation_results",
    "citations_results", "duplicates", "excluded_automatic", "excluded_other", "records_screened",
    "records_excluded", "dbr_sought_reports", "dbr_notretrieved_reports", "other_sought_reports",
    "other_notretrieved_reports", "dbr_assessed", "dbr_excluded", "other_assessed",
    "other_excluded", "new_studies", "new_reports", "total_studies", "total_reports",
    "total_studies_ma", "total_reports_ma",
]  # fmt: skip


def _text(svg: str) -> str:
    """The words on the diagram, a wrapped label rejoined."""
    return " ".join(re.findall(r">([^<]+)</text>", svg))


def _reasons(counts: list[int]) -> list[Reason]:
    ordered = sorted(enumerate(counts, start=1), key=lambda kv: (-kv[1], kv[0]))
    return [Reason(f"EXC-{i:02d}", f"Reason {i}", n) for i, n in ordered]


def test_up_to_six_reasons_are_all_shown_and_zero_counts_never_are() -> None:
    shown, collapsed = flow.collapse_reasons(_reasons([5, 4, 3, 2, 1, 0]))
    assert not collapsed and [r.count for r in shown] == [5, 4, 3, 2, 1]
    shown, collapsed = flow.collapse_reasons(_reasons([6, 5, 4, 3, 2, 1]))
    assert not collapsed and len(shown) == 6


def test_nine_reasons_collapse_the_smallest_into_other_reasons() -> None:
    reasons = _reasons([9, 8, 7, 6, 5, 4, 3, 2, 1])
    shown, collapsed = flow.collapse_reasons(reasons)
    assert collapsed and len(shown) == 6
    assert [r.count for r in shown[:5]] == [9, 8, 7, 6, 5]
    assert (shown[5].label, shown[5].count) == ("Other reasons", 4 + 3 + 2 + 1)
    assert sum(r.count for r in shown) == sum(r.count for r in reasons)


def test_the_full_reasons_table_is_emitted_alongside(tmp_path: Path) -> None:
    repo, _ = finished_review(tmp_path)
    table = flow.reasons_table(counts_mod.compute(repo))
    assert table.splitlines() == ["id\tlabel\tcount", *[line for line in table.splitlines()[1:]]]
    assert "No comparison group\t3" in table and "Not peer reviewed\t1" in table


def test_the_diagram_carries_the_template_labels_and_the_counts(tmp_path: Path) -> None:
    repo, _ = finished_review(tmp_path)
    svg = _text(flow.render(counts_mod.compute(repo), fmt="svg", columns="one").decode())
    for label in (
        "Records identified from:", "Databases (n = 18)", "Registers (n = 4)", "Websites (n = 2)",
        "Citation searching (n = 3)", "Records removed before screening:",
        "Duplicate records removed (n = 4)", "Records marked as ineligible by automation tools (n = 0)",
        "Records removed for other reasons (n = 0)", "Records screened (n = 23)",
        "Records excluded (n = 6)", "Reports sought for retrieval (n = 17)",
        "Reports not retrieved (n = 2)", "Reports assessed for eligibility (n = 15)",
        "Reports excluded:", "No comparison group (n = 3)", "Not peer reviewed (n = 1)",
        "Studies included in review (n = 10)", "Reports of included studies (n = 11)",
        "Identification", "Screening", "Included", "CC BY 4.0",
    ):  # fmt: skip
        assert label in svg, label
    assert "DRAFT" not in svg


def test_two_columns_put_other_methods_in_their_own_flow(tmp_path: Path) -> None:
    repo, _ = finished_review(tmp_path)
    svg = _text(flow.render(counts_mod.compute(repo), fmt="svg", columns="both").decode())
    assert "Identification of studies via databases and registers" in svg
    assert "Identification of studies via other methods" in svg
    # Left: 22 rows identified in the databases and registers, 19 records screened; right: 4.
    assert "Records screened (n = 19)" in svg and "Records screened (n = 4)" in svg
    assert "Records screened (n = 23)" not in svg
    assert svg.count("Studies included in review") == 1


def test_a_diagram_in_progress_is_watermarked_and_a_finished_one_is_not(tmp_path: Path) -> None:
    repo, _ = finished_review(tmp_path, finish=False)
    counts = counts_mod.compute(repo)
    svg = flow.render(counts, fmt="svg").decode()
    assert svg.count("DRAFT — screening incomplete") == 2  # banner and watermark
    assert "awaiting retrieval (n = 5)" in svg
    assert b"DRAFT" not in flow.render(counts, fmt="svg", draft=False)


def test_output_is_deterministic_and_the_pdf_is_a_pdf(tmp_path: Path) -> None:
    repo, _ = finished_review(tmp_path)
    counts = counts_mod.compute(repo)
    assert flow.render(counts, fmt="svg", columns="both") == flow.render(
        counts, fmt="svg", columns="both"
    )
    pdf = flow.render(counts, fmt="pdf")
    assert pdf.startswith(b"%PDF") and b"DRAFT" not in pdf
    assert b"Records screened \\(n = 23\\)" in pdf


def test_unknown_formats_and_columns_are_refused(tmp_path: Path) -> None:
    repo, _ = finished_review(tmp_path)
    counts = counts_mod.compute(repo)
    with pytest.raises(flow.FlowError, match="format"):
        flow.render(counts, fmt="gif")
    with pytest.raises(flow.FlowError, match="columns"):
        flow.render(counts, columns="three")


def test_stale_decisions_refuse_unless_allowed(tmp_path: Path) -> None:
    from strata.protocol import criteria as criteria_mod

    repo, _ = finished_review(tmp_path)
    flow.require_final(counts_mod.compute(repo), allow_stale=False)
    criteria_mod.add_criterion(
        repo, kind="exclusion", label="Older than 2005", definition="Published before 2005.",
        applies_at=["title-abstract", "full-text"], actor="ethan", rationale="Amendment.",
    )  # fmt: skip
    counts = counts_mod.compute(repo)
    with pytest.raises(flow.StaleDecisionsError, match="--allow-stale"):
        flow.require_final(counts, allow_stale=False)
    flow.require_final(counts, allow_stale=True)
    assert b"DRAFT" in flow.render(counts, fmt="svg")


def test_the_json_has_the_r_package_input_shape(tmp_path: Path) -> None:
    repo, _ = finished_review(tmp_path)
    counts = counts_mod.compute(repo)
    names = {"S-01": "MEDLINE", "S-02": "Embase", "S-03": "CENTRAL"}
    for columns in ("one", "both"):
        rows = flow.prisma2020_rows(counts, names, columns)
        assert [r["data"] for r in rows] == R_PACKAGE_KEYS
        assert all(set(r) == {"data", "n"} and isinstance(r["n"], str) for r in rows)
    one = {r["data"]: r["n"] for r in flow.prisma2020_rows(counts, names, "one")}
    assert one["database_results"] == "18" and one["register_results"] == "4"
    assert one["citations_results"] == "3" and one["website_results"] == "2"
    assert one["duplicates"] == "4" and one["records_screened"] == "23"
    assert one["dbr_excluded"] == "No comparison group, 3; Not peer reviewed, 1"
    assert one["new_studies"] == "10" and one["new_reports"] == "11"
    both = {r["data"]: r["n"] for r in flow.prisma2020_rows(counts, names, "both")}
    assert both["records_screened"] == "19" and both["other_sought_reports"] == "3"
    assert both["duplicates"] == "3"


def test_flow_json_carries_counts_reasons_and_attribution(tmp_path: Path) -> None:
    repo, _ = finished_review(tmp_path)
    document = flow.flow_json(counts_mod.compute(repo), {}, columns="both")
    assert document["columns"] == "both" and document["draft"] is False
    assert document["counts"]["reconciled"] is True
    assert document["exclusion_reasons_collapsed"] is False
    assert "CC BY 4.0" in document["attribution"]
    assert json.loads(json.dumps(document)) == document
