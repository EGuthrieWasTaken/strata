import json
from pathlib import Path

import pytest

from strata.core import manifest as manifest_mod
from strata.core.init import init_repository
from strata.core.repo import open_repo
from strata.protocol.criteria import add_criterion, edit_criterion, retire_criterion
from strata.protocol.rescreen import (
    RescreenError,
    compute_stale_records,
    mark_manual_stale,
    regenerate_stale_tsv,
    rescreen_queue,
    stale_records_for_stage,
)
from strata.protocol.screening import record_screen_decision


def _init_single(tmp_path: Path, stages: tuple[str, ...] = ("title-abstract", "full-text")):  # type: ignore[no-untyped-def]
    """A repo where ethan alone resolves every stage (assignment of one) --
    the simplest way to get a *resolved* decision without needing a second
    reviewer to agree, matching effectively docs/spec's `single` mode."""
    root = tmp_path / "review"
    init_repository(root, title="T", actor_handle="ethan", actor_name="Ethan")
    doc = manifest_mod.load_manifest_doc(root)
    manifest_mod.set_value(doc, "screening.assignment", {s: ["ethan"] for s in stages})
    manifest_mod.write_manifest(root, doc)
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


def test_resolved_decision_defends_against_empty_opinions() -> None:
    """`resolve_screening` never actually produces `status="include"` with no
    opinions and no adjudication, but `_resolved_decision` still defends
    against it explicitly rather than raising on `min([])`."""
    from strata.core.fold import ScreeningState
    from strata.protocol.rescreen import _resolved_decision

    state = ScreeningState(status="include", opinions={}, first_opinions={}, adjudication=None)
    assert _resolved_decision(state) is None


def test_compute_stale_records_empty_on_fresh_repo(tmp_path: Path) -> None:
    repo = _init_single(tmp_path)
    assert compute_stale_records(repo) == []


def test_no_staleness_when_criteria_unchanged(tmp_path: Path) -> None:
    repo = _init_single(tmp_path)
    _add_records(repo, ["rec_0000000000000001"])
    record_screen_decision(
        repo,
        stage="title-abstract",
        record_id="rec_0000000000000001",
        decision="include",
        actor="ethan",
    )
    assert compute_stale_records(repo) == []


def test_criterion_added_stales_an_included_record(tmp_path: Path) -> None:
    repo = _init_single(tmp_path)
    _add_records(repo, ["rec_0000000000000001"])
    record_screen_decision(
        repo,
        stage="title-abstract",
        record_id="rec_0000000000000001",
        decision="include",
        actor="ethan",
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
    stale = compute_stale_records(repo)
    assert len(stale) == 1
    assert stale[0].record_id == "rec_0000000000000001"
    assert stale[0].stage == "title-abstract"
    assert stale[0].reason == "criterion-added"
    assert stale[0].prior_decision == "include"
    assert stale[0].since_version == 1


def test_loosening_does_not_stale_an_included_record(tmp_path: Path) -> None:
    repo = _init_single(tmp_path)
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
        decision="include",
        actor="ethan",
    )
    edit_criterion(
        repo,
        "EXC-01",
        direction="loosened",
        actor="ethan",
        rationale="Relaxing this criterion after a protocol review.",
        definition="def a, relaxed",
    )
    assert compute_stale_records(repo) == []


def test_criterion_loosened_stales_the_exclusion_that_cited_it(tmp_path: Path) -> None:
    repo = _init_single(tmp_path)
    _add_records(repo, ["rec_0000000000000001"])
    add_criterion(
        repo,
        kind="exclusion",
        label="Not in English",
        definition="Not in English.",
        applies_at=["title-abstract"],
        actor="ethan",
        rationale="Establishing the initial protocol criteria.",
        criterion_id="EXC-03",
    )
    record_screen_decision(
        repo,
        stage="title-abstract",
        record_id="rec_0000000000000001",
        decision="exclude",
        actor="ethan",
        cited=["EXC-03"],
    )
    edit_criterion(
        repo,
        "EXC-03",
        direction="loosened",
        actor="ethan",
        rationale="Relaxing the language criterion to include translations.",
        definition="Not in English, translations excepted.",
    )
    stale = compute_stale_records(repo)
    assert len(stale) == 1
    assert stale[0].reason == "criterion-loosened"
    assert stale[0].prior_criteria == ("EXC-03",)


def test_retiring_a_cited_criterion_stales_the_exclusion(tmp_path: Path) -> None:
    repo = _init_single(tmp_path)
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
    )
    retire_criterion(repo, "EXC-02", actor="ethan", rationale="No longer part of the protocol.")
    stale = compute_stale_records(repo)
    assert len(stale) == 1
    assert stale[0].reason == "criterion-retired"


def test_multi_opinion_uses_earliest_version_and_union_of_citations(tmp_path: Path) -> None:
    """The two contributing opinions were made at different criteria
    versions with different citations; staleness must use the *earliest*
    version (not the latest) as the baseline, or a change between the two
    opinions would be missed."""
    root = tmp_path / "review"
    init_repository(root, title="T", actor_handle="ethan", actor_name="Ethan")
    repo = open_repo(root)
    from strata.core.actor import add_actor

    add_actor(repo, handle="sam", name="Sam", role="screener")
    repo = open_repo(root)
    _add_records(repo, ["rec_0000000000000001"])

    add_criterion(
        repo,
        kind="exclusion",
        label="Not in English",
        definition="Not in English.",
        applies_at=["title-abstract"],
        actor="ethan",
        rationale="Establishing the initial protocol criteria.",
        criterion_id="EXC-03",
    )
    record_screen_decision(
        repo,
        stage="title-abstract",
        record_id="rec_0000000000000001",
        decision="exclude",
        actor="ethan",
        cited=["EXC-03"],
    )
    # Loosen EXC-03 (bumps version 1 -> 2) *between* the two opinions.
    edit_criterion(
        repo,
        "EXC-03",
        direction="loosened",
        actor="ethan",
        rationale="Relaxing the language criterion to include translations.",
        definition="Not in English, translations excepted.",
    )
    record_screen_decision(
        repo,
        stage="title-abstract",
        record_id="rec_0000000000000001",
        decision="exclude",
        actor="sam",
        cited=["EXC-03"],
    )

    stale = compute_stale_records(repo)
    assert len(stale) == 1
    assert stale[0].reason == "criterion-loosened"
    assert stale[0].since_version == 2


def test_upstream_stale_cascades_to_full_text(tmp_path: Path) -> None:
    repo = _init_single(tmp_path)
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
        stage="full-text",
        record_id="rec_0000000000000001",
        decision="include",
        actor="ethan",
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
    stale = compute_stale_records(repo)
    by_stage = {r.stage: r for r in stale}
    assert by_stage["title-abstract"].reason == "criterion-added"
    assert by_stage["full-text"].reason == "upstream-stale"


def test_native_full_text_reason_wins_over_upstream_stale(tmp_path: Path) -> None:
    repo = _init_single(tmp_path)
    _add_records(repo, ["rec_0000000000000001"])
    add_criterion(
        repo,
        kind="exclusion",
        label="Wrong outcome",
        definition="Wrong outcome measure.",
        applies_at=["full-text"],
        actor="ethan",
        rationale="Establishing the initial protocol criteria.",
        criterion_id="EXC-05",
    )
    record_screen_decision(
        repo,
        stage="title-abstract",
        record_id="rec_0000000000000001",
        decision="include",
        actor="ethan",
    )
    record_screen_decision(
        repo,
        stage="full-text",
        record_id="rec_0000000000000001",
        decision="exclude",
        actor="ethan",
        cited=["EXC-05"],
    )
    # Both a new title-abstract criterion (cascades upstream) and a
    # full-text-native change (retiring EXC-05) land in the same version bump.
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
    retire_criterion(repo, "EXC-05", actor="ethan", rationale="No longer part of the protocol.")

    stale = stale_records_for_stage(repo, "full-text")
    assert len(stale) == 1
    assert stale[0].reason == "criterion-retired"


def test_mark_manual_stale_and_consumption_by_a_fresh_decision(tmp_path: Path) -> None:
    repo = _init_single(tmp_path)
    _add_records(repo, ["rec_0000000000000001"])
    record_screen_decision(
        repo,
        stage="title-abstract",
        record_id="rec_0000000000000001",
        decision="include",
        actor="ethan",
    )
    assert compute_stale_records(repo) == []

    mark_manual_stale(
        repo,
        stage="title-abstract",
        record_id="rec_0000000000000001",
        actor="ethan",
        rationale="Reviewer wants a second look at this one.",
    )
    stale = compute_stale_records(repo)
    assert len(stale) == 1
    assert stale[0].reason == "manual"

    # A fresh decision "consumes" the mark -- no un-marking event needed.
    record_screen_decision(
        repo,
        stage="title-abstract",
        record_id="rec_0000000000000001",
        decision="include",
        actor="ethan",
    )
    assert compute_stale_records(repo) == []


def test_rescreen_queue_filters_by_assignment(tmp_path: Path) -> None:
    root = tmp_path / "review"
    init_repository(root, title="T", actor_handle="ethan", actor_name="Ethan")
    repo = open_repo(root)
    from strata.core.actor import add_actor

    add_actor(repo, handle="sam", name="Sam", role="screener")
    repo = open_repo(root)
    _add_records(repo, ["rec_0000000000000001", "rec_0000000000000002"])

    from strata.protocol.screening import assign_reviewers

    assign_reviewers(
        repo,
        stage="title-abstract",
        actors=["ethan"],
        record_ids=["rec_0000000000000001"],
        actor="ethan",
    )
    assign_reviewers(
        repo,
        stage="title-abstract",
        actors=["sam"],
        record_ids=["rec_0000000000000002"],
        actor="ethan",
    )
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

    ethan_queue = rescreen_queue(repo, "title-abstract", "ethan")
    sam_queue = rescreen_queue(repo, "title-abstract", "sam")
    assert [r.record_id for r in ethan_queue] == ["rec_0000000000000001"]
    assert [r.record_id for r in sam_queue] == ["rec_0000000000000002"]


def test_rescreen_queue_rejects_unknown_stage(tmp_path: Path) -> None:
    repo = _init_single(tmp_path)
    with pytest.raises(RescreenError, match="unknown stage"):
        rescreen_queue(repo, "bogus", "ethan")


def test_regenerate_stale_tsv_writes_expected_columns(tmp_path: Path) -> None:
    repo = _init_single(tmp_path)
    _add_records(repo, ["rec_0000000000000001"])
    record_screen_decision(
        repo,
        stage="title-abstract",
        record_id="rec_0000000000000001",
        decision="include",
        actor="ethan",
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
    text = regenerate_stale_tsv(repo)
    lines = text.splitlines()
    assert (
        lines[0] == "record_id\tstage\tprior_decision\tprior_criteria\treason\tsince_version\ttitle"
    )
    assert len(lines) == 2
    columns = lines[1].split("\t")
    assert columns[0] == "rec_0000000000000001"
    assert columns[1] == "title-abstract"
    assert columns[2] == "include"
    assert columns[4] == "criterion-added"

    on_disk = (repo.path("derived", "stale.tsv")).read_text(encoding="utf-8")
    assert on_disk == text


def test_compute_stale_records_skips_unconfigured_stages(tmp_path: Path) -> None:
    root = tmp_path / "review"
    init_repository(root, title="T", actor_handle="ethan", actor_name="Ethan")
    doc = manifest_mod.load_manifest_doc(root)
    manifest_mod.set_value(doc, "screening.stages", ["title-abstract"])
    manifest_mod.set_value(doc, "screening.assignment", {"title-abstract": ["ethan"]})
    manifest_mod.write_manifest(root, doc)
    repo = open_repo(root)
    _add_records(repo, ["rec_0000000000000001"])
    record_screen_decision(
        repo,
        stage="title-abstract",
        record_id="rec_0000000000000001",
        decision="include",
        actor="ethan",
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
    stale = compute_stale_records(repo)
    assert {r.stage for r in stale} == {"title-abstract"}


def test_manual_stale_alongside_an_adjudicated_decision(tmp_path: Path) -> None:
    """Exercises the adjudication branch of both `_resolved_decision` and
    `_latest_decision_order_key` together with a manual-stale mark."""
    from strata.core.events import append_new_event

    repo = _init_single(tmp_path)
    _add_records(repo, ["rec_0000000000000001"])
    append_new_event(
        repo.path("events", "adjudication", "ethan.ndjson"),
        ev="adjudicate",
        actor="ethan",
        body={
            "stage": "title-abstract",
            "record": "rec_0000000000000001",
            "decision": "include",
            "criteria": [],
            "criteria_version": 0,
            "rationale": "Adjudicated in favour of inclusion.",
        },
    )
    assert compute_stale_records(repo) == []

    mark_manual_stale(
        repo,
        stage="title-abstract",
        record_id="rec_0000000000000001",
        actor="ethan",
        rationale="Reviewer wants a second look at the adjudicated call.",
    )
    stale = compute_stale_records(repo)
    assert len(stale) == 1
    assert stale[0].reason == "manual"
    assert stale[0].prior_decision == "include"


def test_resolved_decision_with_no_version_stamped_adjudication_is_not_stale(
    tmp_path: Path,
) -> None:
    from strata.core.events import append_new_event

    repo = _init_single(tmp_path)
    _add_records(repo, ["rec_0000000000000001"])
    append_new_event(
        repo.path("events", "adjudication", "ethan.ndjson"),
        ev="adjudicate",
        actor="ethan",
        body={
            "stage": "title-abstract",
            "record": "rec_0000000000000001",
            "decision": "include",
            "criteria": [],
            "rationale": "Adjudicated before criteria_version was stamped.",
        },
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
    assert compute_stale_records(repo) == []


def test_regenerate_stale_tsv_empty_when_nothing_stale(tmp_path: Path) -> None:
    repo = _init_single(tmp_path)
    text = regenerate_stale_tsv(repo)
    assert (
        text == "record_id\tstage\tprior_decision\tprior_criteria\treason\tsince_version\ttitle\n"
    )
