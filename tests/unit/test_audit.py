import json
from pathlib import Path

from strata.core.init import init_repository
from strata.core.repo import open_repo
from strata.protocol.audit import all_exclusions, sample_exclusions
from strata.protocol.criteria import add_criterion
from strata.protocol.screening import record_screen_decision


def _init(tmp_path: Path):  # type: ignore[no-untyped-def]
    root = tmp_path / "review"
    init_repository(root, title="T", actor_handle="ethan", actor_name="Ethan")
    return open_repo(root)


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


def test_all_exclusions_empty_before_any_screening(tmp_path: Path) -> None:
    repo = _init(tmp_path)
    assert all_exclusions(repo) == []


def test_all_exclusions_skips_includes_and_maybes(tmp_path: Path) -> None:
    repo = _init(tmp_path)
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
        record_id="rec_0000000000000002",
        decision="maybe",
        actor="ethan",
    )
    assert all_exclusions(repo) == []


def test_all_exclusions_reports_current_opinion_only(tmp_path: Path) -> None:
    """A reviewer who excluded and then changed their mind should not show
    up as a live exclusion to audit."""
    repo = _init(tmp_path)
    _add_records(repo, ["rec_0000000000000001"])
    add_criterion(
        repo,
        kind="exclusion",
        label="A",
        definition="def a",
        applies_at=["title-abstract"],
        actor="ethan",
        rationale="Establishing the initial protocol criteria.",
        criterion_id="EXC-01",
    )
    record_screen_decision(
        repo,
        stage="title-abstract",
        record_id="rec_0000000000000001",
        decision="exclude",
        actor="ethan",
        cited=["EXC-01"],
        note="wrong population",
    )
    record_screen_decision(
        repo,
        stage="title-abstract",
        record_id="rec_0000000000000001",
        decision="include",
        actor="ethan",
    )
    assert all_exclusions(repo) == []


def test_all_exclusions_reports_criteria_and_note(tmp_path: Path) -> None:
    repo = _init(tmp_path)
    _add_records(repo, ["rec_0000000000000001"])
    add_criterion(
        repo,
        kind="exclusion",
        label="Animal model",
        definition="Non-human sample.",
        applies_at=["title-abstract"],
        actor="ethan",
        rationale="Establishing the initial protocol criteria.",
        criterion_id="EXC-02",
    )
    record_screen_decision(
        repo,
        stage="title-abstract",
        record_id="rec_0000000000000001",
        decision="exclude",
        actor="ethan",
        cited=["EXC-02"],
        note="rodent model",
    )
    items = all_exclusions(repo)
    assert len(items) == 1
    assert items[0].record_id == "rec_0000000000000001"
    assert items[0].stage == "title-abstract"
    assert items[0].actor == "ethan"
    assert items[0].criteria == ("EXC-02",)
    assert items[0].note == "rodent model"


def test_sample_exclusions_is_reproducible_with_same_seed(tmp_path: Path) -> None:
    repo = _init(tmp_path)
    ids = [f"rec_{i:016x}" for i in range(20)]
    _add_records(repo, ids)
    add_criterion(
        repo,
        kind="exclusion",
        label="A",
        definition="def a",
        applies_at=["title-abstract"],
        actor="ethan",
        rationale="Establishing the initial protocol criteria.",
        criterion_id="EXC-01",
    )
    for rid in ids:
        record_screen_decision(
            repo,
            stage="title-abstract",
            record_id=rid,
            decision="exclude",
            actor="ethan",
            cited=["EXC-01"],
        )

    sample_a, seed_a = sample_exclusions(repo, sample_size=5, seed=42)
    sample_b, seed_b = sample_exclusions(repo, sample_size=5, seed=42)
    assert seed_a == seed_b == 42
    assert [i.record_id for i in sample_a] == [i.record_id for i in sample_b]
    assert len(sample_a) == 5


def test_sample_exclusions_generates_a_seed_when_none_given(tmp_path: Path) -> None:
    repo = _init(tmp_path)
    _add_records(repo, ["rec_0000000000000001"])
    add_criterion(
        repo,
        kind="exclusion",
        label="A",
        definition="def a",
        applies_at=["title-abstract"],
        actor="ethan",
        rationale="Establishing the initial protocol criteria.",
        criterion_id="EXC-01",
    )
    record_screen_decision(
        repo,
        stage="title-abstract",
        record_id="rec_0000000000000001",
        decision="exclude",
        actor="ethan",
        cited=["EXC-01"],
    )
    sample, seed = sample_exclusions(repo, sample_size=5)
    assert isinstance(seed, int)
    assert len(sample) == 1


def test_sample_exclusions_caps_at_available_items(tmp_path: Path) -> None:
    repo = _init(tmp_path)
    _add_records(repo, ["rec_0000000000000001"])
    add_criterion(
        repo,
        kind="exclusion",
        label="A",
        definition="def a",
        applies_at=["title-abstract"],
        actor="ethan",
        rationale="Establishing the initial protocol criteria.",
        criterion_id="EXC-01",
    )
    record_screen_decision(
        repo,
        stage="title-abstract",
        record_id="rec_0000000000000001",
        decision="exclude",
        actor="ethan",
        cited=["EXC-01"],
    )
    sample, _ = sample_exclusions(repo, sample_size=1000, seed=1)
    assert len(sample) == 1
