import json
from pathlib import Path
from typing import Any

import pytest

from strata.core.review_ci import (
    MARKER,
    criteria_changed,
    main,
    render_pool_impact_comment,
)

HEADER = "### strata: effect of this change on the review"
NO_EFFECT = "No effect on the records, decisions, or conflicts."


def _stage(name: str, *, stale: int = 0, conflicts: int = 0) -> dict[str, Any]:
    return {
        "stage": name,
        "total": 100,
        "resolved": 0,
        "unscreened": 0,
        "partial": 0,
        "conflicts": conflicts,
        "stale": stale,
    }


def _status(
    *, records: int = 100, criteria: int = 1, stages: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    return {
        "title": "T",
        "slug": "t",
        "actor_count": 2,
        "commit_count": 10,
        "is_clean": True,
        "criteria_version": criteria,
        "record_count": records,
        "search_count": 1,
        "pending_searches": [],
        "stages": stages if stages is not None else [],
        "next_action": None,
    }


def test_criteria_changed_is_true_when_the_version_differs() -> None:
    assert criteria_changed(_status(criteria=3), _status(criteria=4))


def test_criteria_changed_is_false_when_the_version_is_the_same() -> None:
    assert not criteria_changed(_status(criteria=3), _status(criteria=3))


def test_criteria_changed_treats_a_missing_version_as_zero() -> None:
    assert not criteria_changed({}, {})
    assert criteria_changed({}, {"criteria_version": 1})


def test_tightened_criterion_comment_is_exactly_as_specified() -> None:
    base = _status(records=1200, criteria=3, stages=[_stage("title-abstract"), _stage("full-text")])
    head = _status(
        records=1158,
        criteria=4,
        stages=[_stage("title-abstract", stale=120, conflicts=2), _stage("full-text", stale=60)],
    )
    assert render_pool_impact_comment(base, head) == (
        f"{MARKER}\n"
        f"{HEADER}\n"
        "\n"
        "- **Protocol amendment:** criteria v3 → v4\n"
        "- **Records:** 1200 → 1158 (0 entered, 42 left)\n"
        "- **Decisions invalidated:** 180\n"
        "  - title-abstract: 120\n"
        "  - full-text: 60\n"
        "- **Conflicts opened:** 2\n"
        "  - title-abstract: 2\n"
    )


def test_comment_without_any_effect_says_so() -> None:
    status = _status(stages=[_stage("title-abstract")])
    assert render_pool_impact_comment(status, status) == f"{MARKER}\n{HEADER}\n\n{NO_EFFECT}\n"


def test_missing_keys_are_tolerated() -> None:
    assert render_pool_impact_comment({}, {}) == f"{MARKER}\n{HEADER}\n\n{NO_EFFECT}\n"


def test_decreases_in_stale_or_conflicts_are_not_reported_as_impact() -> None:
    base = _status(stages=[_stage("title-abstract", stale=50, conflicts=4)])
    head = _status(stages=[_stage("title-abstract", stale=20, conflicts=1)])
    assert NO_EFFECT in render_pool_impact_comment(base, head)


def test_records_entering_are_counted_and_the_other_bullets_show_zero() -> None:
    comment = render_pool_impact_comment(_status(records=10), _status(records=15))
    assert comment.endswith("\n")
    assert not comment.endswith("\n\n")
    assert comment.splitlines() == [
        MARKER,
        HEADER,
        "",
        "- **Records:** 10 → 15 (5 entered, 0 left)",
        "- **Decisions invalidated:** 0",
        "- **Conflicts opened:** 0",
    ]


def test_a_stage_missing_from_the_base_counts_from_zero() -> None:
    head = _status(stages=[_stage("full-text", stale=3, conflicts=1)])
    comment = render_pool_impact_comment(_status(stages=[]), head)
    assert "- **Decisions invalidated:** 3\n  - full-text: 3\n" in comment
    assert "- **Conflicts opened:** 1\n  - full-text: 1\n" in comment


def test_a_stage_missing_from_the_head_is_ignored() -> None:
    base = _status(stages=[_stage("full-text", stale=9)])
    assert NO_EFFECT in render_pool_impact_comment(base, _status(stages=[]))


def test_only_stages_with_new_stale_decisions_get_a_sub_bullet() -> None:
    base = _status(stages=[_stage("title-abstract", stale=5), _stage("full-text")])
    head = _status(stages=[_stage("title-abstract", stale=5), _stage("full-text", stale=2)])
    comment = render_pool_impact_comment(base, head)
    assert "  - full-text: 2\n" in comment
    assert "title-abstract" not in comment


def _write(tmp_path: Path, name: str, value: dict[str, Any]) -> str:
    path = tmp_path / name
    path.write_text(json.dumps(value), encoding="utf-8")
    return str(path)


def test_main_comment_prints_the_rendered_comment(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    base, head = _status(records=10), _status(records=12)
    argv = ["comment", _write(tmp_path, "b.json", base), _write(tmp_path, "h.json", head)]
    assert main(argv) == 0
    assert capsys.readouterr().out == render_pool_impact_comment(base, head)


@pytest.mark.parametrize(("head_version", "expected"), [(2, "true\n"), (1, "false\n")])
def test_main_criteria_changed_prints_true_or_false(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], head_version: int, expected: str
) -> None:
    base_file = _write(tmp_path, "b.json", _status(criteria=1))
    head_file = _write(tmp_path, "h.json", _status(criteria=head_version))
    assert main(["criteria-changed", base_file, head_file]) == 0
    assert capsys.readouterr().out == expected


@pytest.mark.parametrize(
    "argv",
    [[], ["comment"], ["comment", "only-one.json"], ["frobnicate", "a.json", "b.json"]],
)
def test_main_rejects_bad_usage_with_exit_code_2(
    argv: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(argv) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err != ""


def test_main_reports_missing_or_invalid_json_with_exit_code_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    good = _write(tmp_path, "good.json", _status())
    invalid = tmp_path / "invalid.json"
    invalid.write_text("{not json", encoding="utf-8")
    assert main(["comment", good, str(invalid)]) == 2
    assert main(["comment", good, str(tmp_path / "missing.json")]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err != ""


def test_a_head_stage_without_a_name_is_skipped() -> None:
    head = _status(stages=[{"stale": 5, "conflicts": 5}])
    assert NO_EFFECT in render_pool_impact_comment(_status(), head)
