"""The review-repository CI helpers: the pull-request comment and protocol-amendment detection
(openspec:review-repository-ci)."""

# ruff: noqa: E501
from __future__ import annotations

from typing import Any

from strata.ci import amendment as amendment_mod
from strata.ci import comment as comment_mod
from strata.ci import workflows


def _stage(name: str, **counts: int) -> dict[str, Any]:
    base = {
        "stage": name, "total": 120, "resolved": 100, "included": 60, "unscreened": 20,
        "partial": 0, "conflicts": 2, "stale": 0, "stale_included": 0,
    }  # fmt: skip
    return {**base, **counts}


def _status(
    *stages: dict[str, Any], analyses: list[dict[str, str]] | None = None
) -> dict[str, Any]:
    return {
        "title": "Review", "slug": "review", "record_count": stages[0]["total"] if stages else 0,
        "stages": list(stages), "analyses": analyses or [],
    }  # fmt: skip


def test_a_tightened_criterion_says_how_many_decisions_it_invalidates_and_who_could_leave() -> None:
    base = _status(_stage("title-abstract"))
    head = _status(_stage("title-abstract", stale=180, stale_included=138))
    text = comment_mod.render(base, head)
    assert text.startswith(comment_mod.MARKER)
    assert "**Decisions invalidated:** 180" in text
    assert "138 included papers could leave the pool" in text
    assert "42 excluded papers could re-enter it" in text
    assert "| title-abstract | 60 | 40 | 20 | 2 | 0 → 180 |" in text


def test_records_entering_and_leaving_and_conflicts_opened() -> None:
    base = _status(_stage("title-abstract", total=120, conflicts=2))
    head = _status(_stage("title-abstract", total=118, conflicts=5))
    text = comment_mod.render(base, head)
    assert "2 records leave it (120 → 118)" in text
    assert "**Screening conflicts opened:** 3." in text
    grown = comment_mod.render(base, _status(_stage("title-abstract", total=121, conflicts=1)))
    assert "1 record enter it (120 → 121)" in grown and "opened:** 0; 1 closed." in grown


def test_nothing_changing_is_said_plainly() -> None:
    status = _status(_stage("title-abstract"))
    text = comment_mod.render(status, status)
    assert "none enter or leave (120)" in text
    assert "**Decisions invalidated:** 0." in text and "→" not in text.split("| Stage")[1]


def test_stale_decisions_that_are_settled_are_counted_as_no_longer_stale() -> None:
    text = comment_mod.render(
        _status(_stage("title-abstract", stale=10, stale_included=4)),
        _status(_stage("title-abstract", stale=3, stale_included=1)),
    )
    assert "**Decisions invalidated:** 0; 7 no longer stale." in text


def test_a_base_that_is_not_a_strata_repository_is_shown_as_it_stands() -> None:
    text = comment_mod.render(None, _status(_stage("title-abstract", stale=2, stale_included=1)))
    assert "no strata repository" in text and "**Records in the pool:** 120." in text
    assert "→" not in text.split("| Stage")[1]  # nothing to compare with in the table


def test_analyses_that_became_stale_are_named() -> None:
    fresh = [{"id": "primary", "label": "Primary", "state": "fresh"}]
    stale = [{"id": "primary", "label": "Primary", "state": "stale-data"}]
    text = comment_mod.render(
        _status(_stage("title-abstract"), analyses=fresh),
        _status(_stage("title-abstract"), analyses=stale),
    )
    assert "**Analyses made stale:** Primary" in text
    already = comment_mod.render(
        _status(_stage("title-abstract"), analyses=stale),
        _status(_stage("title-abstract"), analyses=stale),
    )
    assert "made stale" not in already


def test_a_status_without_stages_or_the_newer_fields_still_renders() -> None:
    older = {"title": "T", "slug": "t", "record_count": 7, "stages": [{
        "stage": "title-abstract", "total": 7, "resolved": 3, "unscreened": 4, "partial": 0,
        "conflicts": 0, "stale": 1,
    }]}  # fmt: skip
    assert "**Records in the pool:** 7" in comment_mod.render(None, older)
    assert "none enter or leave (0)" in comment_mod.render({"record_count": 0}, {"record_count": 0})


def test_the_amendment_section_names_the_criteria_and_the_methodologist() -> None:
    found = amendment_mod.Amendment(
        changed=True, version_before=3, version_after=4, added=["INC-04"],
        changed_criteria={"EXC-01": ["definition", "applies_at"]}, retired=["EXC-02"],
    )  # fmt: skip
    status = _status(_stage("title-abstract"))
    text = comment_mod.render(status, status, amendment=found, methodologist="@octocat")
    assert "criteria version 3 → 4" in text
    assert "Added: INC-04" in text and "Changed: EXC-01 (definition, applies_at)" in text
    assert "Retired: EXC-02" in text
    assert "labelled `protocol-amendment` and review is requested from @octocat." in text
    nobody = comment_mod.render(status, status, amendment=found)
    assert "no methodologist is configured" in nobody
    assert "Protocol amendment" not in comment_mod.render(
        status, status, amendment=amendment_mod.Amendment(changed=False)
    )


def test_comparing_criteria_files() -> None:
    def criterion(cid: str, **fields: Any) -> dict[str, Any]:
        return {
            "id": cid,
            "kind": "inclusion",
            "label": cid,
            "definition": "d",
            "applies_at": ["title-abstract"],
            "status": "active",
            **fields,
        }

    before = {
        "version": 2,
        "criteria": [criterion("INC-01"), criterion("INC-02"), criterion("EXC-01")],
    }
    after = {
        "version": 3,
        "criteria": [
            criterion("INC-01", definition="stricter"),
            criterion("INC-02", status="retired"),
            criterion("EXC-01"),
            criterion("INC-03"),
        ],
    }
    found = amendment_mod.compare(before, after)
    assert found.changed and found.added == ["INC-03"]
    assert found.changed_criteria == {"INC-01": ["definition"]} and found.retired == ["INC-02"]
    assert (found.version_before, found.version_after) == (2, 3)
    assert not amendment_mod.compare(before, {**before, "version": 2}).changed
    assert amendment_mod.compare(None, after).added == ["EXC-01", "INC-01", "INC-02", "INC-03"]
    assert amendment_mod.compare(before, None).retired == ["EXC-01", "INC-01", "INC-02"]
    assert found.to_dict()["added"] == ["INC-03"]


def test_the_caller_workflow_pins_a_ref_and_passes_the_same_one_to_the_checks() -> None:
    text = workflows.caller_workflow(ref="v9.9.9", methodologist="@octocat")
    assert f"{workflows.STRATA_REPOSITORY}/{workflows.REUSABLE_WORKFLOW}@v9.9.9" in text
    assert 'strata-ref: "v9.9.9"' in text and 'methodologist: "octocat"' in text
    default = workflows.caller_workflow()
    assert f"@{workflows.default_ref()}" in default and 'methodologist: ""' in default
