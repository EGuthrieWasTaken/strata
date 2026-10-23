"""P11 (count reconciliation): the PRISMA identities hold for any random review history
(openspec:test-suite#property-invariants,
openspec:prisma-reporting#counts-and-reconciliation-identities).

A history is built by the functions a user's commands call: several searches and other-method
imports whose files overlap (and repeat rows within a file), near-duplicate variants merged by the
deduplication pass, then random title/abstract decisions, retrieval outcomes, full-text decisions
and study groupings, any of them left unfinished.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from strata.core.ids import report_id
from strata.protocol import studies as studies_mod
from strata.report import counts as counts_mod
from tests.unit._m3 import init_review
from tests.unit._m5 import (
    add_criteria,
    canonical_ids,
    decide,
    import_papers,
    merge_duplicates,
    paper,
    retrieve,
    search,
)

papers = st.lists(st.integers(min_value=1, max_value=30), min_size=1, max_size=12)
choice = st.sampled_from(["include", "exclude", "leave"])
retrieval_choice = st.sampled_from(["retrieved", "not-retrieved", "leave"])


@st.composite
def histories(draw: st.DrawFn) -> dict[str, object]:
    return {
        "searches": draw(st.lists(papers, min_size=1, max_size=3)),
        "databases": draw(
            st.lists(st.sampled_from(["MEDLINE", "Embase", "CENTRAL"]), min_size=3, max_size=3)
        ),
        "via": draw(
            st.lists(
                st.tuples(
                    st.sampled_from(["citation-searching", "website", "organisation"]), papers
                ),
                max_size=2,
            )
        ),
        "variants": draw(st.lists(st.integers(1, 30), max_size=3)),
        "tiab": draw(st.lists(choice, min_size=60, max_size=60)),
        "retrieval": draw(st.lists(retrieval_choice, min_size=60, max_size=60)),
        "ft": draw(st.lists(choice, min_size=60, max_size=60)),
        "group": draw(st.booleans()),
        "dedup": draw(st.booleans()),
    }


def _build(root: Path, history: dict[str, object]) -> counts_mod.Counts:
    repo = init_review(root, actors=("sam",))
    criteria = add_criteria(repo)
    for index, numbers in enumerate(history["searches"]):  # type: ignore[arg-type]
        database = history["databases"][index]  # type: ignore[index]
        search_id = search(repo, database, "Cochrane" if database == "CENTRAL" else "Ovid")
        import_papers(
            repo, root, f"s{index}.json", [paper(n) for n in numbers], search_id=search_id
        )
    for index, (via, numbers) in enumerate(history["via"]):  # type: ignore[arg-type]
        import_papers(repo, root, f"v{index}.json", [paper(n) for n in numbers], via=via)
    if history["variants"]:
        # The same papers exported without a DOI: new record ids that the dedup pass can merge.
        variants = [{**paper(n), "DOI": ""} for n in history["variants"]]  # type: ignore[attr-defined]
        import_papers(repo, root, "variants.json", variants, via="website")
    if history["dedup"]:
        merge_duplicates(repo)
    ids = canonical_ids(repo)
    pick = lambda values, wanted: [i for i, v in zip(ids, values, strict=False) if v == wanted]  # noqa: E731
    tiab = history["tiab"]
    decide(repo, "title-abstract", pick(tiab, "exclude"), "exclude", [criteria["Wrong population"]])
    included = pick(tiab, "include")
    decide(repo, "title-abstract", included, "include")
    marks = dict(zip(included, history["retrieval"], strict=False))  # type: ignore[arg-type]
    got = [i for i in included if marks.get(i) == "retrieved"]
    retrieve(repo, got)
    retrieve(repo, [i for i in included if marks.get(i) == "not-retrieved"], reason="not-found")
    ft = dict(zip(got, history["ft"], strict=False))  # type: ignore[arg-type]
    decide(
        repo,
        "full-text",
        [i for i in got if ft.get(i) == "exclude"],
        "exclude",
        [criteria["No comparison group"]],
    )
    kept = [i for i in got if ft.get(i) == "include"]
    decide(repo, "full-text", kept, "include")
    if history["group"] and len(kept) >= 2:
        studies_mod.group_reports(
            repo,
            reports=[report_id(kept[0]), report_id(kept[1])],
            actor="ethan",
            rationale="Same trial.",
        )
    return counts_mod.compute(repo)


@settings(max_examples=20, deadline=None, suppress_health_check=list(HealthCheck))
@given(histories())
def test_p11_the_identities_hold_for_any_review_history(history: dict[str, object]) -> None:
    with tempfile.TemporaryDirectory(prefix="strata-p11-") as tmp:
        counts = _build(Path(tmp), history)
        assert counts.reconciled, counts.failures
        t = counts.totals
        assert t.identified == counts.identification["identified_total"]
        assert t.records_screened == t.identified - t.removed_before_screening
        assert t.reports_included <= t.reports_assessed <= t.reports_sought <= t.records_screened
        assert counts.studies_included <= t.reports_included
        finished = t.awaiting_tiab + t.awaiting_retrieval + t.awaiting_ft == 0
        assert counts.complete == (finished and counts.stale_decisions == 0)
