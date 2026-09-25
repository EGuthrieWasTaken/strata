import json
from pathlib import Path

from strata.core.actor import add_actor
from strata.core.init import init_repository
from strata.core.repo import open_repo
from strata.core.status import (
    _count_ndjson_lines,
    _next_action,
    _read_criteria_version,
    compute_status,
)
from strata.protocol.criteria import add_criterion
from strata.protocol.screening import record_screen_decision


def _init(tmp_path: Path) -> Path:
    root = tmp_path / "review"
    init_repository(root, title="T", actor_handle="ethan", actor_name="Ethan")
    return root


def _add_records(repo, ids: list[str]) -> None:  # type: ignore[no-untyped-def]
    records_path = repo.path("records", "records.ndjson")
    records_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        json.dumps(
            {
                "id": rid,
                "type": "article-journal",
                "title": f"Title for {rid}",
                "strata": {"canonical_key": f"sig:{rid}", "canonical": True, "sources": []},
            }
        )
        for rid in ids
    ]
    records_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_count_ndjson_lines_missing_file_returns_zero(tmp_path: Path) -> None:
    assert _count_ndjson_lines(tmp_path / "does-not-exist.ndjson") == 0


def test_read_criteria_version_missing_file_returns_zero(tmp_path: Path) -> None:
    repo = open_repo(_init(tmp_path))
    repo.path("protocol", "criteria.yaml").unlink()
    assert _read_criteria_version(repo) == 0


def test_read_criteria_version_empty_file_returns_zero(tmp_path: Path) -> None:
    repo = open_repo(_init(tmp_path))
    repo.path("protocol", "criteria.yaml").write_text("", encoding="utf-8")
    assert _read_criteria_version(repo) == 0


def test_compute_status_on_freshly_initialised_repo(tmp_path: Path) -> None:
    repo = open_repo(_init(tmp_path))
    status = compute_status(repo)
    assert status.title == "T"
    assert status.actor_count == 1
    assert status.record_count == 0
    assert status.criteria_version == 0
    assert status.is_clean is True
    assert {s.stage for s in status.stages} == {"title-abstract", "full-text"}
    assert all(s.total == 0 for s in status.stages)
    assert status.next_action is None


def test_compute_status_reports_unscreened_and_next_action(tmp_path: Path) -> None:
    root = _init(tmp_path)
    repo = open_repo(root)
    _add_records(repo, ["rec_0000000000000001"])
    status = compute_status(repo)
    tiab = next(s for s in status.stages if s.stage == "title-abstract")
    assert tiab.total == 1
    assert tiab.unscreened == 1
    assert status.next_action == "strata screen title-abstract"


def test_compute_status_reports_conflicts_and_stale(tmp_path: Path) -> None:
    root = _init(tmp_path)
    repo = open_repo(root)
    add_actor(repo, handle="sam", name="Sam", role="screener")
    repo = open_repo(root)
    _add_records(repo, ["rec_0000000000000001", "rec_0000000000000002"])

    record_screen_decision(
        repo,
        stage="title-abstract",
        record_id="rec_0000000000000001",
        decision="include",
        actor="ethan",
    )
    record_screen_decision(
        repo,
        stage="title-abstract",
        record_id="rec_0000000000000001",
        decision="maybe",
        actor="sam",
    )
    record_screen_decision(
        repo,
        stage="title-abstract",
        record_id="rec_0000000000000002",
        decision="include",
        actor="ethan",
    )
    record_screen_decision(
        repo,
        stage="title-abstract",
        record_id="rec_0000000000000002",
        decision="include",
        actor="sam",
    )
    add_criterion(
        repo,
        kind="exclusion",
        label="Under 18",
        definition="Mean sample age under 18.",
        applies_at=["title-abstract"],
        actor="ethan",
        rationale="Pilot extraction showed several child samples.",
        criterion_id="EXC-07",
    )

    status = compute_status(repo)
    tiab = next(s for s in status.stages if s.stage == "title-abstract")
    assert tiab.conflicts == 1
    assert tiab.stale == 1  # record 2's include is now stale (criterion-added)
    assert status.next_action == "strata adjudicate"  # conflicts outrank stale


def test_compute_status_reports_partial(tmp_path: Path) -> None:
    root = _init(tmp_path)
    repo = open_repo(root)
    add_actor(repo, handle="sam", name="Sam", role="screener")
    repo = open_repo(root)
    _add_records(repo, ["rec_0000000000000001"])
    record_screen_decision(
        repo,
        stage="title-abstract",
        record_id="rec_0000000000000001",
        decision="include",
        actor="ethan",
    )
    status = compute_status(repo)
    tiab = next(s for s in status.stages if s.stage == "title-abstract")
    assert tiab.partial == 1
    assert tiab.resolved == 0


def test_compute_status_counts_adjudicated_records_as_resolved(tmp_path: Path) -> None:
    from strata.core.events import append_new_event

    root = _init(tmp_path)
    repo = open_repo(root)
    add_actor(repo, handle="sam", name="Sam", role="screener")
    repo = open_repo(root)
    _add_records(repo, ["rec_0000000000000001"])
    record_screen_decision(
        repo,
        stage="title-abstract",
        record_id="rec_0000000000000001",
        decision="include",
        actor="ethan",
    )
    record_screen_decision(
        repo,
        stage="title-abstract",
        record_id="rec_0000000000000001",
        decision="maybe",
        actor="sam",
    )
    append_new_event(
        repo.path("events", "adjudication", "ethan.ndjson"),
        ev="adjudicate",
        actor="ethan",
        body={
            "stage": "title-abstract",
            "record": "rec_0000000000000001",
            "decision": "include",
            "criteria": [],
            "rationale": "Adjudicated in favour of inclusion.",
        },
    )
    status = compute_status(repo)
    tiab = next(s for s in status.stages if s.stage == "title-abstract")
    assert tiab.resolved == 1
    assert tiab.conflicts == 0


def test_next_action_prioritises_stale_over_unscreened() -> None:
    from strata.core.status import StageStatus

    stages = [
        StageStatus(
            stage="title-abstract",
            total=2,
            resolved=1,
            unscreened=1,
            partial=0,
            conflicts=0,
            stale=1,
        )
    ]
    assert _next_action(stages) == "strata rescreen"


def test_next_action_none_when_everything_resolved() -> None:
    from strata.core.status import StageStatus

    stages = [
        StageStatus(
            stage="title-abstract",
            total=1,
            resolved=1,
            unscreened=0,
            partial=0,
            conflicts=0,
            stale=0,
        )
    ]
    assert _next_action(stages) is None
