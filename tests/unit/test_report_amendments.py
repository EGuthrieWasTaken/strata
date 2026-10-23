"""Protocol amendments generated from the criteria-change events (PRISMA 2020 item 24c)."""

# ruff: noqa: E501
from __future__ import annotations

from pathlib import Path

from strata import gitio
from strata.protocol import criteria as criteria_mod
from strata.protocol import rescreen as rescreen_mod
from strata.protocol import screening as screening_mod
from strata.report import amendments as am
from tests.unit._m5 import ACTORS, finished_review


def _amend(repo, label: str = "Participants under 18") -> dict:  # type: ignore[no-untyped-def]
    return criteria_mod.add_criterion(
        repo, kind="exclusion", label=label, definition="Participants younger than 18 years.",
        applies_at=["title-abstract", "full-text"], actor="ethan",
        rationale="Reviewers noticed trials in children that the protocol did not intend.",
    )  # fmt: skip


def test_setting_up_the_criteria_before_screening_is_not_an_amendment(tmp_path: Path) -> None:
    from tests.unit._m3 import init_review
    from tests.unit._m5 import add_criteria

    repo = init_review(tmp_path)
    add_criteria(repo)
    assert am.amendments(repo) == []
    assert "not amended after screening began" in am.text(repo)


def test_a_review_with_no_later_changes_reports_none(tmp_path: Path) -> None:
    repo, _ = finished_review(tmp_path)
    assert am.amendments(repo) == []
    assert am.text(repo) == "The eligibility criteria were not amended after screening began.\n"


def test_an_amendment_counts_what_it_invalidated(tmp_path: Path) -> None:
    repo, _ = finished_review(tmp_path)
    _amend(repo)
    stale = rescreen_mod.compute_stale_records(repo)
    (amendment,) = am.amendments(repo)
    assert amendment.invalidated == len(stale) > 0
    assert amendment.rescreened == 0 and amendment.still_stale == amendment.invalidated
    assert amendment.from_version + 1 == amendment.to_version and amendment.actor == "ethan"
    assert sum(amendment.stages.values()) == amendment.invalidated
    assert "Reviewers noticed trials in children" in amendment.rationale


def test_rescreening_after_the_change_is_counted_from_history(tmp_path: Path) -> None:
    repo, _ = finished_review(tmp_path)
    criterion = _amend(repo)
    stale = [s for s in rescreen_mod.compute_stale_records(repo) if s.stage == "title-abstract"]
    invalidated_at_first = am.amendments(repo)[0].invalidated
    redone = stale[:4]
    for index, item in enumerate(redone):
        for actor in ACTORS:
            screening_mod.record_screen_decision(
                repo, stage="title-abstract", record_id=item.record_id, actor=actor,
                decision="exclude" if index < 3 else "include",
                cited=[criterion["id"]] if index < 3 else None,
            )  # fmt: skip
    (amendment,) = am.amendments(repo)
    still = len(rescreen_mod.compute_stale_records(repo))
    assert amendment.rescreened >= 4 and amendment.now_excluded >= 3 and amendment.now_included >= 1
    assert amendment.rescreened + amendment.still_stale == amendment.invalidated
    assert amendment.still_stale <= still
    # What the change invalidated does not shrink as the work is redone.
    assert amendment.invalidated == invalidated_at_first


def test_the_paragraph_states_date_criterion_numbers_and_the_authors_rationale(
    tmp_path: Path,
) -> None:
    repo, _ = finished_review(tmp_path)
    criterion = _amend(repo)
    stale = [s for s in rescreen_mod.compute_stale_records(repo) if s.stage == "title-abstract"]
    for item in stale[:2]:
        for actor in ACTORS:
            screening_mod.record_screen_decision(
                repo, stage="title-abstract", record_id=item.record_id, actor=actor,
                decision="exclude", cited=[criterion["id"]],
            )  # fmt: skip
    (amendment,) = am.amendments(repo)
    paragraph = am.paragraph(amendment)
    assert amendment.date in paragraph
    assert f"{criterion['id']} (Participants under 18) was added" in paragraph
    assert 'The stated rationale was: "Reviewers noticed trials in children' in paragraph
    assert f"made {amendment.invalidated} screening decision(s) stale" in paragraph
    assert "ended excluded" in paragraph and "still await re-screening" in paragraph


def test_an_amendment_is_joined_to_the_commit_that_carried_it(tmp_path: Path) -> None:
    repo, _ = finished_review(tmp_path)
    gitio.add_all(repo.root)
    gitio.commit(repo.root, "test: before the amendment\n\nStrata-Op: test\nStrata-Actor: ethan")
    _amend(repo)
    gitio.add_all(repo.root)
    gitio.commit(
        repo.root, "criteria: add EXC-06\n\nStrata-Op: criteria-change\nStrata-Actor: ethan"
    )
    (amendment,) = am.amendments(repo)
    assert amendment.commit == gitio.current_commit(repo.root)
    assert f"(commit {amendment.commit[:10]})" in am.paragraph(amendment)


def test_edits_and_retirements_are_described_with_their_direction(tmp_path: Path) -> None:
    repo, criteria = finished_review(tmp_path)
    criteria_mod.edit_criterion(
        repo, criteria["No comparison group"], direction="loosened", actor="ethan",
        rationale="Single-arm studies are acceptable.", definition="A study with no control of any kind.",
    )  # fmt: skip
    criteria_mod.retire_criterion(
        repo, criteria["Not peer reviewed"], actor="ethan", rationale="Grey literature is in scope."
    )
    first, second = am.amendments(repo)
    assert "was edited, a change that loosened it" in am.paragraph(first)
    assert "was retired" in am.paragraph(second)
