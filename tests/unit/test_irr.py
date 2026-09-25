import json
from pathlib import Path

import pytest

from strata.core.actor import add_actor
from strata.core.init import init_repository
from strata.core.repo import open_repo
from strata.protocol.irr import IrrError, compute_pair_irr, compute_stage_irr, regenerate_irr_json
from strata.protocol.screening import record_screen_decision


def _init(tmp_path: Path):  # type: ignore[no-untyped-def]
    root = tmp_path / "review"
    init_repository(root, title="T", actor_handle="ethan", actor_name="Ethan")
    repo = open_repo(root)
    add_actor(repo, handle="sam", name="Sam", role="screener")
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


def test_compute_pair_irr_matches_hand_computed_2x2_example(tmp_path: Path) -> None:
    """5 both-include, 1 (ethan include/sam exclude), 0 (ethan exclude/sam
    include), 4 both-exclude -- po=0.9, pe=0.5, kappa=0.8, pabak=0.8 by hand."""
    from strata.protocol.criteria import add_criterion

    repo = _init(tmp_path)
    ids = [f"rec_{i:016x}" for i in range(10)]
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

    ethan_decisions = ["include"] * 6 + ["exclude"] * 4
    sam_decisions = ["include"] * 5 + ["exclude", "exclude"] + ["exclude"] * 3
    # both_include=5, ethan-include/sam-exclude=1, ethan-exclude/sam-include=0, both_exclude=4
    for rid, d in zip(ids, ethan_decisions, strict=True):
        cited = ["EXC-01"] if d == "exclude" else None
        record_screen_decision(
            repo, stage="title-abstract", record_id=rid, decision=d, actor="ethan", cited=cited
        )
    for rid, d in zip(ids, sam_decisions, strict=True):
        cited = ["EXC-01"] if d == "exclude" else None
        record_screen_decision(
            repo, stage="title-abstract", record_id=rid, decision=d, actor="sam", cited=cited
        )

    pair = compute_pair_irr(repo, "title-abstract", "ethan", "sam")
    assert pair.n == 10
    assert pair.excluded_maybe == 0
    assert pair.table == {
        "both_include": 5,
        "a_include_b_exclude": 1,
        "a_exclude_b_include": 0,
        "both_exclude": 4,
    }
    assert pair.raw_agreement == pytest.approx(0.9)
    assert pair.kappa == pytest.approx(0.8)
    assert pair.pabak == pytest.approx(0.8)


def test_compute_pair_irr_a_exclude_b_include_cell(tmp_path: Path) -> None:
    from strata.protocol.criteria import add_criterion

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
    record_screen_decision(
        repo,
        stage="title-abstract",
        record_id="rec_0000000000000001",
        decision="include",
        actor="sam",
    )
    pair = compute_pair_irr(repo, "title-abstract", "ethan", "sam")
    assert pair.table["a_exclude_b_include"] == 1


def test_compute_pair_irr_uses_first_opinion_only(tmp_path: Path) -> None:
    """A reviewer who changes their mind after the fact must not count their
    revised opinion for IRR -- only the original, independent first one."""
    repo = _init(tmp_path)
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
        decision="include",
        actor="sam",
    )
    # ethan changes their mind (perhaps after seeing sam's) -- IRR must still
    # reflect the *original* agreement, not this later exclude.
    record_screen_decision(
        repo,
        stage="title-abstract",
        record_id="rec_0000000000000001",
        decision="maybe",
        actor="ethan",
    )

    pair = compute_pair_irr(repo, "title-abstract", "ethan", "sam")
    assert pair.table["both_include"] == 1
    assert pair.n == 1
    assert pair.excluded_maybe == 0


def test_compute_pair_irr_excludes_maybe_from_binary_table(tmp_path: Path) -> None:
    repo = _init(tmp_path)
    _add_records(repo, ["rec_0000000000000001", "rec_0000000000000002"])
    record_screen_decision(
        repo,
        stage="title-abstract",
        record_id="rec_0000000000000001",
        decision="maybe",
        actor="ethan",
    )
    record_screen_decision(
        repo,
        stage="title-abstract",
        record_id="rec_0000000000000001",
        decision="include",
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

    pair = compute_pair_irr(repo, "title-abstract", "ethan", "sam")
    assert pair.n == 1
    assert pair.excluded_maybe == 1
    assert pair.table["both_include"] == 1


def test_compute_pair_irr_only_counts_records_both_screened(tmp_path: Path) -> None:
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
        decision="include",
        actor="sam",
    )
    pair = compute_pair_irr(repo, "title-abstract", "ethan", "sam")
    assert pair.n == 0
    assert pair.raw_agreement == 0.0
    assert pair.kappa == 0.0
    assert pair.pabak == 0.0


def test_compute_pair_irr_perfect_agreement_pe_equals_one(tmp_path: Path) -> None:
    """Both reviewers always say include: pe == 1, kappa is defined as 1.0
    rather than raising a division-by-zero."""
    repo = _init(tmp_path)
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
        decision="include",
        actor="sam",
    )
    pair = compute_pair_irr(repo, "title-abstract", "ethan", "sam")
    assert pair.raw_agreement == 1.0
    assert pair.kappa == 1.0
    assert pair.pabak == 1.0


def test_compute_stage_irr_enumerates_all_pairs(tmp_path: Path) -> None:
    repo = _init(tmp_path)
    add_actor(repo, handle="pat", name="Pat", role="screener")
    repo = open_repo(repo.root)
    _add_records(repo, ["rec_0000000000000001"])
    for actor in ("ethan", "sam", "pat"):
        record_screen_decision(
            repo,
            stage="title-abstract",
            record_id="rec_0000000000000001",
            decision="include",
            actor=actor,
        )
    pairs = compute_stage_irr(repo, "title-abstract")
    assert {(p.actor_a, p.actor_b) for p in pairs} == {
        ("ethan", "pat"),
        ("ethan", "sam"),
        ("pat", "sam"),
    }


def test_compute_stage_irr_rejects_unknown_stage(tmp_path: Path) -> None:
    repo = _init(tmp_path)
    with pytest.raises(IrrError, match="unknown stage"):
        compute_stage_irr(repo, "bogus")


def test_compute_stage_irr_empty_before_any_screening(tmp_path: Path) -> None:
    repo = _init(tmp_path)
    assert compute_stage_irr(repo, "title-abstract") == []


def test_regenerate_irr_json_writes_all_configured_stages(tmp_path: Path) -> None:
    repo = _init(tmp_path)
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
        decision="include",
        actor="sam",
    )
    text = regenerate_irr_json(repo)
    payload = json.loads(text)
    assert set(payload.keys()) == {"title-abstract", "full-text"}
    assert payload["full-text"] == []
    assert len(payload["title-abstract"]) == 1
    assert payload["title-abstract"][0]["kappa"] == 1.0

    on_disk = repo.path("derived", "irr.json").read_text(encoding="utf-8")
    assert on_disk == text
