import json
from pathlib import Path

import pytest

from strata.core import manifest as manifest_mod
from strata.core.init import init_repository
from strata.core.repo import open_repo
from strata.protocol import criteria as criteria_mod
from strata.protocol import screening as screening_mod
from strata.protocol.criteria import add_criterion, edit_criterion, retire_criterion
from strata.protocol.rescreen import (
    RescreenError,
    compute_stale_records,
    mark_manual_stale,
    preview_criterion_change_impact,
    regenerate_stale_tsv,
    rescreen_queue,
    stale_records_for_stage,
)
from strata.protocol.screening import record_screen_decision


def _init_single(tmp_path: Path, stages: tuple[str, ...] = ("title-abstract", "full-text")):  # type: ignore[no-untyped-def]
    """A repo where ethan alone resolves every stage (assignment of one) --
    the simplest way to get a *resolved* decision without needing a second
    reviewer to agree, matching effectively the spec's `single` mode."""
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


def test_effective_opinion_defends_against_empty_opinions() -> None:
    """`resolve_screening` never actually produces `status="include"` with no
    opinions and no adjudication, but `_effective_opinion`'s aggregate
    (`actor=None`) path still defends against it explicitly rather than
    raising on `min([])`."""
    from strata.core.fold import ScreeningState
    from strata.protocol.rescreen import _effective_opinion

    state = ScreeningState(status="include", opinions={}, first_opinions={}, adjudication=None)
    assert _effective_opinion(state, actor=None) is None


def test_effective_opinion_actor_mode_returns_none_when_actor_has_no_opinion() -> None:
    """The per-actor path (used by `rescreen_queue`): an actor who never
    screened this record has nothing to rescreen."""
    from strata.core.fold import ScreeningState
    from strata.protocol.rescreen import _effective_opinion

    state = ScreeningState(status="unscreened", opinions={}, first_opinions={}, adjudication=None)
    assert _effective_opinion(state, actor="ethan") is None


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


def test_rescreen_queue_excludes_a_stale_opinion_after_reassignment(tmp_path: Path) -> None:
    """An actor's own opinion can be stale, but if they were later reassigned
    off the record they no longer owe a fresh one (the `actor in assigned`
    filter in `rescreen_queue`, on top of `_compute_stale`'s per-opinion
    view)."""
    from strata.core.actor import add_actor
    from strata.protocol.screening import assign_reviewers

    repo = _init_single(tmp_path, stages=("title-abstract",))
    add_actor(repo, handle="sam", name="Sam", role="screener")
    repo = open_repo(repo.root)
    _add_records(repo, ["rec_0000000000000001"])
    record_screen_decision(
        repo,
        stage="title-abstract",
        record_id="rec_0000000000000001",
        decision="include",
        actor="ethan",
    )
    # Reassign the record to sam alone -- ethan's own prior opinion still
    # exists on disk, but ethan is no longer on the hook for it.
    assign_reviewers(
        repo,
        stage="title-abstract",
        actors=["sam"],
        record_ids=["rec_0000000000000001"],
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
    assert rescreen_queue(repo, "title-abstract", "ethan") == []


def test_rescreen_queue_survives_a_dual_reviewer_conflict(tmp_path: Path) -> None:
    """The bug docs/m2-plan.md sub-objective 9's E2E-01 test caught: once one
    dual reviewer re-screens and *disagrees* with the other's still-stale
    opinion, the record's aggregate status flips to `conflict`. The second
    reviewer's own opinion is exactly as stale as before and must still
    show up in *their* queue -- it must not silently vanish because the
    record is no longer in a resolved state."""
    root = tmp_path / "review"
    init_repository(root, title="T", actor_handle="ethan", actor_name="Ethan")
    repo = open_repo(root)
    from strata.core.actor import add_actor

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
    assert len(rescreen_queue(repo, "title-abstract", "ethan")) == 1
    assert len(rescreen_queue(repo, "title-abstract", "sam")) == 1

    # ethan re-screens, excluding under the new criterion -- disagreeing
    # with sam's still-stale "include", which flips the record to conflict.
    record_screen_decision(
        repo,
        stage="title-abstract",
        record_id="rec_0000000000000001",
        decision="exclude",
        actor="ethan",
        cited=["EXC-07"],
    )
    from strata.core.fold import CONFLICT

    state = screening_mod.resolve_record_state(repo, "title-abstract", "rec_0000000000000001")
    assert state.status == CONFLICT
    # The aggregate view has nothing to say about a conflict...
    assert compute_stale_records(repo) == []
    # ...but sam's own opinion is still exactly as stale as it was.
    sam_queue = rescreen_queue(repo, "title-abstract", "sam")
    assert len(sam_queue) == 1
    assert sam_queue[0].reason == "criterion-added"

    # sam agrees with ethan's new decision -- the conflict resolves cleanly.
    record_screen_decision(
        repo,
        stage="title-abstract",
        record_id="rec_0000000000000001",
        decision="exclude",
        actor="sam",
        cited=["EXC-07"],
    )
    assert compute_stale_records(repo) == []
    assert rescreen_queue(repo, "title-abstract", "ethan") == []
    assert rescreen_queue(repo, "title-abstract", "sam") == []


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


def test_preview_matches_what_the_real_edit_would_produce(tmp_path: Path) -> None:
    """The preview's whole point (openspec:web-ui#criteria-editor-impact-preview) is that it
    tells the truth about what saving would do -- so assert it against the
    real, post-edit `compute_stale_records` result, not just its own
    internals."""
    repo = _init_single(tmp_path)
    _add_records(repo, ["rec_0000000000000001", "rec_0000000000000002"])
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
    record_screen_decision(
        repo,
        stage="title-abstract",
        record_id="rec_0000000000000002",
        decision="include",
        actor="ethan",
    )

    preview = preview_criterion_change_impact(repo, criterion_id="EXC-03", direction="loosened")
    assert len(preview) == 1
    assert preview[0].record_id == "rec_0000000000000001"
    assert preview[0].reason == "criterion-loosened"

    # Nothing was written: criteria.yaml's version is unchanged, and a
    # second preview call gives the identical answer.
    assert int(criteria_mod.read_criteria_doc(repo)["version"]) == 1
    assert (
        preview_criterion_change_impact(repo, criterion_id="EXC-03", direction="loosened")
        == preview
    )

    # Now make the real edit and confirm the preview told the truth.
    edit_criterion(
        repo,
        "EXC-03",
        direction="loosened",
        actor="ethan",
        rationale="Relaxing the language criterion to include translations.",
        definition="Not in English, translations excepted.",
    )
    real = compute_stale_records(repo)
    assert [r.record_id for r in real] == [r.record_id for r in preview]
    assert [r.reason for r in real] == [r.reason for r in preview]


def test_preview_tightened_direction_stales_inclusions(tmp_path: Path) -> None:
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
    preview = preview_criterion_change_impact(repo, criterion_id="EXC-01", direction="tightened")
    assert len(preview) == 1
    assert preview[0].reason == "criterion-tightened"


def test_preview_retired_origin_ignores_direction_argument(tmp_path: Path) -> None:
    """Retiring always behaves as loosened regardless of what `direction`
    is passed (matching `CriterionChange.effective_direction`'s own
    origin-overrides-direction rule)."""
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
        decision="exclude",
        actor="ethan",
        cited=["EXC-01"],
    )
    preview = preview_criterion_change_impact(
        repo, criterion_id="EXC-01", direction="tightened", origin="retired"
    )
    assert len(preview) == 1
    assert preview[0].reason == "criterion-retired"


def test_preview_editorial_direction_has_no_impact(tmp_path: Path) -> None:
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
        decision="exclude",
        actor="ethan",
        cited=["EXC-01"],
    )
    assert preview_criterion_change_impact(repo, criterion_id="EXC-01", direction="editorial") == []


def test_preview_unknown_criterion_raises(tmp_path: Path) -> None:
    repo = _init_single(tmp_path)
    with pytest.raises(RescreenError, match="no criterion"):
        preview_criterion_change_impact(repo, criterion_id="EXC-99", direction="loosened")
