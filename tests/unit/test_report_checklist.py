"""The PRISMA 2020 checklist: states, auto-filled content and the author's remainder."""

# ruff: noqa: E501
from __future__ import annotations

import json
from pathlib import Path

import pytest

from strata import gitio
from strata.core.validate import SchemaValidationError, validate
from strata.report import checklist as cl
from strata.report import facts as facts_mod
from tests.unit._m5 import finished_review, full_review

EXPECTED_IDS = [
    "1", "2", "3", "4", "5", "6", "7", "8", "9", "10a", "10b", "11", "12", "13a", "13b", "13c",
    "13d", "13e", "13f", "14", "15", "16a", "16b", "17", "18", "19", "20a", "20b", "20c", "20d",
    "21", "22", "23a", "23b", "23c", "23d", "24a", "24b", "24c", "25", "26", "27",
]  # fmt: skip


def _items(repo):  # type: ignore[no-untyped-def]
    return {i.id: i for i in cl.build(facts_mod.collect(repo))}


def test_every_item_and_sub_item_of_the_statement_is_present(tmp_path: Path) -> None:
    repo, _ = finished_review(tmp_path)
    items = cl.build(facts_mod.collect(repo))
    assert [i.id for i in items] == EXPECTED_IDS
    assert {i.status for i in items} <= {cl.AUTO_FILLED, cl.AUTO_LOCATED, cl.AUTHOR}
    assert all(i.wording and i.topic and i.section for i in items)


def test_the_file_carries_the_attribution_and_says_the_wording_is_unverified(
    tmp_path: Path,
) -> None:
    repo, _ = finished_review(tmp_path)
    text = cl.render(facts_mod.collect(repo))
    assert "CC BY 4.0" in text and "doi.org/10.1136/bmj.n71" in text
    assert "Not yet verified" in text and cl.WORDING_VERIFIED is False
    assert (
        "| Item | Section / topic | Checklist item | Status | Repository source | Location where item is reported |"
        in text
    )
    assert text.count("\n| ") >= len(EXPECTED_IDS)


def test_search_strategy_is_the_verbatim_query_of_every_search(tmp_path: Path) -> None:
    repo, _ = finished_review(tmp_path)
    item = _items(repo)["7"]
    assert item.status == cl.AUTO_FILLED
    for query in (
        "spaced practice AND recall (MEDLINE)",
        "spaced practice AND recall (Embase)",
        "spaced practice AND recall (CENTRAL)",
    ):
        assert f"```\n{query}\n```" in item.content


def test_information_sources_name_each_source_and_date(tmp_path: Path) -> None:
    repo, _ = finished_review(tmp_path)
    content = _items(repo)["6"].content
    assert "MEDLINE (Ovid), last searched 2026-01-05" in content
    assert "CENTRAL (Cochrane)" in content
    assert "citation-searching: 3 record(s)" in content and "website: 2 record(s)" in content


def test_eligibility_lists_the_current_criteria_with_their_stages(tmp_path: Path) -> None:
    repo, criteria = finished_review(tmp_path)
    content = _items(repo)["5"].content
    assert f"Exclusion {criteria['Wrong population']} (Wrong population)" in content
    assert "[applies at: title-abstract, full-text]" in content and "Criteria version 5" in content


def test_selection_and_collection_describe_the_process(tmp_path: Path) -> None:
    repo, _ = full_review(tmp_path)
    items = _items(repo)
    assert "two reviewers, working independently" in items["8"].content
    assert (
        "Cohen's kappa" in items["8"].content
        and "4 duplicate record(s) removed" in items["8"].content
    )
    assert "One reviewer (ethan)" in items["9"].content and "investigators" in items["9"].content
    assert items["11"].status == cl.AUTO_FILLED and "RoB 2" in items["11"].content


def test_the_analysis_items_follow_the_specification_and_results(tmp_path: Path) -> None:
    repo, _ = full_review(tmp_path)
    items = _items(repo)
    assert "standardised" not in items["12"].content and "SMD" in items["12"].content
    assert "random-effects model, tau^2 estimated by REML" in items["13d"].content
    assert "validated" in items["13d"].content
    assert (
        "leave_one_out" in items["13f"].content.replace(" ", "_")
        or "leave one out" in items["13f"].content
    )
    assert "egger" in items["14"].content
    assert "pooled SMD" in items["20b"].content
    assert items["21"].status == cl.AUTO_LOCATED
    assert items["20c"].status == cl.AUTHOR  # no moderators were analysed


def test_without_an_analysis_the_synthesis_items_are_the_authors(tmp_path: Path) -> None:
    repo, _ = finished_review(tmp_path)
    items = _items(repo)
    for item_id in ("12", "13a", "13d", "14", "19", "20b"):
        assert items[item_id].status == cl.AUTHOR, item_id


def test_certainty_and_the_discussion_are_flagged_as_author_work(tmp_path: Path) -> None:
    repo, _ = full_review(tmp_path)
    items = _items(repo)
    for item_id in ("15", "22", "23a", "23b", "23c", "23d"):
        assert items[item_id].status == cl.AUTHOR and items[item_id].note, item_id
    assert (
        "does not assess it" in items["22"].note
        and "does not generate a discussion" in items["23a"].note
    )


def test_funding_and_competing_interests_come_from_the_manifest(tmp_path: Path) -> None:
    repo, _ = finished_review(tmp_path)
    assert _items(repo)["25"].status == cl.AUTHOR and _items(repo)["26"].status == cl.AUTHOR
    repo.config["project"]["funding"] = {
        "sources": ["Example Foundation grant 123"],
        "role_of_funders": "The funder had no role in the review.",
    }
    repo.config["project"]["competing_interests"] = {
        "statement": "No competing interests.",
        "declarations": [{"author": "ethan", "statement": "Ethan is employed by the sponsor."}],
    }
    items = _items(repo)
    assert items["25"].status == cl.AUTO_FILLED
    assert (
        "Example Foundation grant 123" in items["25"].content and "no role" in items["25"].content
    )
    assert (
        items["26"].status == cl.AUTO_FILLED and "ethan: Ethan is employed" in items["26"].content
    )


def test_registration_is_filled_from_the_manifest(tmp_path: Path) -> None:
    repo, _ = finished_review(tmp_path)
    assert _items(repo)["24a"].status == cl.AUTHOR
    repo.config["project"]["registry"] = {"name": "PROSPERO", "id": "CRD42026000000"}
    assert (
        "PROSPERO" in _items(repo)["24a"].content and _items(repo)["24a"].status == cl.AUTO_FILLED
    )


def test_amendments_are_generated_not_left_to_memory(tmp_path: Path) -> None:
    from strata.protocol import criteria as criteria_mod

    repo, _ = finished_review(tmp_path)
    assert "not amended after screening began" in _items(repo)["24c"].content
    criteria_mod.add_criterion(
        repo, kind="exclusion", label="Participants under 18", definition="Younger than 18.",
        applies_at=["title-abstract", "full-text"], actor="ethan", rationale="Children were out of scope.",
    )  # fmt: skip
    item = _items(repo)["24c"]
    assert item.status == cl.AUTO_FILLED and "Participants under 18" in item.content
    assert '"Children were out of scope."' in item.content


def test_availability_names_the_repository_and_the_commit(tmp_path: Path) -> None:
    repo, _ = finished_review(tmp_path)
    gitio.add_all(repo.root)
    gitio.commit(repo.root, "test: fixture\n\nStrata-Op: test\nStrata-Actor: ethan")
    gitio.run(["remote", "add", "origin", "https://example.org/review.git"], cwd=repo.root)
    content = _items(repo)["27"].content
    assert (
        "https://example.org/review.git" in content and gitio.current_commit(repo.root) in content
    )


def test_status_counts_add_up_and_name_the_authors_items(tmp_path: Path) -> None:
    repo, _ = full_review(tmp_path)
    summary = cl.status(cl.build(facts_mod.collect(repo)))
    assert (
        summary["auto_filled"] + summary["auto_located"] + summary["author"]
        == summary["items"]
        == 42
    )
    assert summary["author"] == len(summary["needs_author"]) and "22" in summary["needs_author"]
    assert json.loads(json.dumps(summary)) == summary


def test_the_checklist_is_deterministic(tmp_path: Path) -> None:
    repo, _ = full_review(tmp_path)
    facts = facts_mod.collect(repo)
    assert cl.render(facts) == cl.render(facts)


def test_the_manifest_schema_accepts_funding_and_competing_interests() -> None:
    base = {
        "schema_version": 1, "created_with": "strata 0.1.0",
        "project": {"id": "p", "title": "T", "slug": "t", "created": "2026-01-01"},
        "actors": [{"handle": "ethan", "name": "Ethan", "email": "e@example.org", "role": "lead"}],
    }  # fmt: skip
    good = json.loads(json.dumps(base))
    good["project"]["funding"] = {"sources": ["A"], "role_of_funders": "None."}
    good["project"]["competing_interests"] = {
        "statement": "None.",
        "declarations": [{"author": "ethan", "statement": "x"}],
    }
    validate("manifest", good)
    for bad in ({"sources": "A"}, {"unknown": 1}):
        broken = json.loads(json.dumps(base))
        broken["project"]["funding"] = bad
        with pytest.raises(SchemaValidationError):
            validate("manifest", broken)
