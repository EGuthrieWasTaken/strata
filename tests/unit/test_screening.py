from pathlib import Path

import pytest

from strata.core.actor import add_actor
from strata.core.events import read_events
from strata.core.init import init_repository
from strata.core.repo import open_repo
from strata.protocol.criteria import add_criterion
from strata.protocol.screening import (
    ScreeningError,
    all_assign_events,
    assign_reviewers,
    assigned_actors,
    configured_stages,
    import_decisions_tsv,
    record_screen_decision,
    resolve_record_state,
    stage_queue,
)


def _init(tmp_path: Path):  # type: ignore[no-untyped-def]
    root = tmp_path / "review"
    init_repository(root, title="T", actor_handle="ethan", actor_name="Ethan")
    repo = open_repo(root)
    add_actor(repo, handle="sam", name="Sam", role="screener")
    return open_repo(root)  # reload so `repo.config["actors"]` sees sam


def _add_records(repo, ids: list[str]) -> None:  # type: ignore[no-untyped-def]
    import json

    records_path = repo.path("records", "records.ndjson")
    records_path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for rid in ids:
        lines.append(
            json.dumps(
                {
                    "id": rid,
                    "type": "article-journal",
                    "title": f"Title for {rid}",
                    "strata": {"canonical_key": f"sig:{rid}", "canonical": True, "sources": []},
                }
            )
        )
    records_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _add_exclusion_criterion(repo, criterion_id: str = "EXC-01", **overrides):  # type: ignore[no-untyped-def]
    kwargs = {
        "kind": "exclusion",
        "label": "Not empirical",
        "definition": "Not an empirical study.",
        "applies_at": ["title-abstract", "full-text"],
        "actor": "ethan",
        "rationale": "Establishing the initial protocol criteria.",
        "criterion_id": criterion_id,
    }
    kwargs.update(overrides)
    return add_criterion(repo, **kwargs)


def test_configured_stages_falls_back_when_unset(tmp_path: Path) -> None:
    from strata.core.repo import Repo

    repo = Repo(root=tmp_path, config={})
    assert configured_stages(repo) == ["title-abstract", "full-text"]


def test_assigned_actors_defaults_to_screener_and_lead_roles(tmp_path: Path) -> None:
    repo = _init(tmp_path)
    _add_records(repo, ["rec_0000000000000001"])
    assert assigned_actors(repo, "title-abstract", "rec_0000000000000001") == frozenset(
        {"ethan", "sam"}
    )


def test_assigned_actors_uses_config_assignment(tmp_path: Path) -> None:
    from strata.core import manifest as manifest_mod

    root = tmp_path / "review"
    init_repository(root, title="T", actor_handle="ethan", actor_name="Ethan")
    repo = open_repo(root)
    add_actor(repo, handle="sam", name="Sam", role="screener")
    doc = manifest_mod.load_manifest_doc(root)
    manifest_mod.set_value(doc, "screening.assignment", {"title-abstract": ["ethan"]})
    manifest_mod.write_manifest(root, doc)
    repo = open_repo(root)
    _add_records(repo, ["rec_0000000000000001"])
    assert assigned_actors(repo, "title-abstract", "rec_0000000000000001") == frozenset({"ethan"})


def test_assign_reviewers_overrides_default_for_named_records(tmp_path: Path) -> None:
    repo = _init(tmp_path)
    _add_records(repo, ["rec_0000000000000001", "rec_0000000000000002"])
    assign_reviewers(
        repo,
        stage="title-abstract",
        actors=["ethan"],
        record_ids=["rec_0000000000000001"],
        actor="ethan",
    )
    assert assigned_actors(repo, "title-abstract", "rec_0000000000000001") == frozenset({"ethan"})
    # The other record is untouched by the override.
    assert assigned_actors(repo, "title-abstract", "rec_0000000000000002") == frozenset(
        {"ethan", "sam"}
    )
    events = all_assign_events(repo)
    assert len(events) == 1
    assert events[0]["body"]["records"] == ["rec_0000000000000001"]
    assert "filter" not in events[0]["body"]


def test_assign_reviewers_records_the_filter_expression(tmp_path: Path) -> None:
    repo = _init(tmp_path)
    _add_records(repo, ["rec_0000000000000001"])
    assign_reviewers(
        repo,
        stage="title-abstract",
        actors=["ethan"],
        record_ids=["rec_0000000000000001"],
        actor="ethan",
        filter_expr="year >= 2000",
    )
    events = all_assign_events(repo)
    assert events[0]["body"]["filter"] == "year >= 2000"


def test_assign_reviewers_rejects_empty_actors_and_records(tmp_path: Path) -> None:
    repo = _init(tmp_path)
    _add_records(repo, ["rec_0000000000000001"])
    with pytest.raises(ScreeningError, match="actors must be non-empty"):
        assign_reviewers(
            repo,
            stage="title-abstract",
            actors=[],
            record_ids=["rec_0000000000000001"],
            actor="ethan",
        )
    with pytest.raises(ScreeningError, match="no records matched"):
        assign_reviewers(
            repo, stage="title-abstract", actors=["ethan"], record_ids=[], actor="ethan"
        )


def test_assign_reviewers_rejects_unknown_stage(tmp_path: Path) -> None:
    repo = _init(tmp_path)
    _add_records(repo, ["rec_0000000000000001"])
    with pytest.raises(ScreeningError, match="unknown stage"):
        assign_reviewers(
            repo,
            stage="bogus-stage",
            actors=["ethan"],
            record_ids=["rec_0000000000000001"],
            actor="ethan",
        )


def test_record_screen_decision_rejects_unknown_stage(tmp_path: Path) -> None:
    repo = _init(tmp_path)
    _add_records(repo, ["rec_0000000000000001"])
    with pytest.raises(ScreeningError, match="unknown stage"):
        record_screen_decision(
            repo, stage="bogus", record_id="rec_0000000000000001", decision="include", actor="ethan"
        )


def test_record_screen_decision_rejects_unknown_decision(tmp_path: Path) -> None:
    repo = _init(tmp_path)
    _add_records(repo, ["rec_0000000000000001"])
    with pytest.raises(ScreeningError, match="decision must be one of"):
        record_screen_decision(
            repo,
            stage="title-abstract",
            record_id="rec_0000000000000001",
            decision="yes",  # type: ignore[arg-type]
            actor="ethan",
        )


def test_record_screen_decision_rejects_unknown_record(tmp_path: Path) -> None:
    repo = _init(tmp_path)
    with pytest.raises(ScreeningError, match="no record"):
        record_screen_decision(
            repo,
            stage="title-abstract",
            record_id="rec_doesnotexist0000",
            decision="include",
            actor="ethan",
        )


def test_record_screen_decision_rejects_inactive_criterion(tmp_path: Path) -> None:
    repo = _init(tmp_path)
    _add_records(repo, ["rec_0000000000000001"])
    with pytest.raises(ScreeningError, match="not an active criterion"):
        record_screen_decision(
            repo,
            stage="title-abstract",
            record_id="rec_0000000000000001",
            decision="exclude",
            actor="ethan",
            cited=["EXC-99"],
        )


def test_record_screen_decision_rejects_criterion_wrong_stage(tmp_path: Path) -> None:
    repo = _init(tmp_path)
    _add_records(repo, ["rec_0000000000000001"])
    _add_exclusion_criterion(repo, applies_at=["full-text"])
    with pytest.raises(ScreeningError, match="not an active criterion that applies at stage"):
        record_screen_decision(
            repo,
            stage="title-abstract",
            record_id="rec_0000000000000001",
            decision="exclude",
            actor="ethan",
            cited=["EXC-01"],
        )


def test_record_screen_decision_requires_criterion_at_full_text_always(tmp_path: Path) -> None:
    root = tmp_path / "review"
    init_repository(root, title="T", actor_handle="ethan", actor_name="Ethan")
    repo = open_repo(root)
    add_actor(repo, handle="sam", name="Sam", role="screener")
    from strata.core import manifest as manifest_mod

    doc = manifest_mod.load_manifest_doc(root)
    manifest_mod.set_value(doc, "screening.require_exclusion_reason", False)
    manifest_mod.write_manifest(root, doc)
    repo = open_repo(root)
    _add_records(repo, ["rec_0000000000000001"])
    with pytest.raises(ScreeningError, match="full-text always requires"):
        record_screen_decision(
            repo,
            stage="full-text",
            record_id="rec_0000000000000001",
            decision="exclude",
            actor="ethan",
        )


def test_record_screen_decision_requires_criterion_when_configured(tmp_path: Path) -> None:
    repo = _init(tmp_path)
    _add_records(repo, ["rec_0000000000000001"])
    with pytest.raises(ScreeningError, match="require_exclusion_reason"):
        record_screen_decision(
            repo,
            stage="title-abstract",
            record_id="rec_0000000000000001",
            decision="exclude",
            actor="ethan",
        )


def test_record_screen_decision_writes_valid_event(tmp_path: Path) -> None:
    repo = _init(tmp_path)
    _add_records(repo, ["rec_0000000000000001"])
    criterion = _add_exclusion_criterion(repo)
    envelope = record_screen_decision(
        repo,
        stage="title-abstract",
        record_id="rec_0000000000000001",
        decision="exclude",
        actor="ethan",
        cited=[criterion["id"]],
        note="rodent model",
    )
    assert envelope["ev"] == "screen"
    assert envelope["body"]["decision"] == "exclude"
    assert envelope["body"]["criteria"] == ["EXC-01"]
    assert envelope["body"]["note"] == "rodent model"
    assert envelope["body"]["criteria_version"] == 1

    events = read_events(repo.path("events", "screen", "title-abstract.ethan.ndjson"))
    assert len(events) == 1


def test_record_screen_decision_include_needs_no_criteria(tmp_path: Path) -> None:
    repo = _init(tmp_path)
    _add_records(repo, ["rec_0000000000000001"])
    envelope = record_screen_decision(
        repo,
        stage="title-abstract",
        record_id="rec_0000000000000001",
        decision="include",
        actor="ethan",
    )
    assert envelope["body"]["criteria"] == []


def test_record_screen_decision_stores_confidence(tmp_path: Path) -> None:
    repo = _init(tmp_path)
    _add_records(repo, ["rec_0000000000000001"])
    envelope = record_screen_decision(
        repo,
        stage="title-abstract",
        record_id="rec_0000000000000001",
        decision="include",
        actor="ethan",
        confidence="high",
    )
    assert envelope["body"]["confidence"] == "high"


def test_record_screen_decision_allows_uncited_exclude_when_reason_not_required(
    tmp_path: Path,
) -> None:
    from strata.core import manifest as manifest_mod

    root = tmp_path / "review"
    init_repository(root, title="T", actor_handle="ethan", actor_name="Ethan")
    repo = open_repo(root)
    add_actor(repo, handle="sam", name="Sam", role="screener")
    doc = manifest_mod.load_manifest_doc(root)
    manifest_mod.set_value(doc, "screening.require_exclusion_reason", False)
    manifest_mod.write_manifest(root, doc)
    repo = open_repo(root)
    _add_records(repo, ["rec_0000000000000001"])

    envelope = record_screen_decision(
        repo,
        stage="title-abstract",
        record_id="rec_0000000000000001",
        decision="exclude",
        actor="ethan",
    )
    assert envelope["body"]["criteria"] == []


def test_all_screen_events_missing_directory_returns_empty(tmp_path: Path) -> None:
    import tomllib

    from strata.core.repo import Repo
    from strata.protocol.screening import all_screen_events

    (tmp_path / "strata.toml").write_text(
        'schema_version = 1\ncreated_with = "strata/0.1.0"\n\n[project]\n'
        'id = "prj_x"\ntitle = "T"\nslug = "t"\ncreated = "2026-01-01"\n\n'
        '[[actors]]\nhandle = "ethan"\nname = "Ethan"\nrole = "lead"\n',
        encoding="utf-8",
    )
    config = tomllib.loads((tmp_path / "strata.toml").read_text())
    repo = Repo(root=tmp_path, config=config)
    assert all_screen_events(repo, "title-abstract") == []


def test_all_adjudicate_events_missing_directory_returns_empty(tmp_path: Path) -> None:
    import shutil

    from strata.protocol.screening import all_adjudicate_events

    repo = _init(tmp_path)
    shutil.rmtree(repo.path("events", "adjudication"))
    assert all_adjudicate_events(repo) == []


def test_all_adjudicate_events_and_stage_filter(tmp_path: Path) -> None:
    from strata.core.events import append_new_event
    from strata.protocol.screening import all_adjudicate_events

    repo = _init(tmp_path)
    assert all_adjudicate_events(repo) == []
    assert all_adjudicate_events(repo, "title-abstract") == []

    path = repo.path("events", "adjudication", "ethan.ndjson")
    append_new_event(
        path,
        ev="adjudicate",
        actor="ethan",
        body={
            "stage": "title-abstract",
            "record": "rec_0000000000000001",
            "decision": "include",
            "criteria": [],
            "rationale": "Looks like an eligible RCT on balance.",
        },
    )
    append_new_event(
        path,
        ev="adjudicate",
        actor="ethan",
        body={
            "stage": "full-text",
            "record": "rec_0000000000000002",
            "decision": "exclude",
            "criteria": [],
            "rationale": "Wrong population on full-text review.",
        },
    )
    assert len(all_adjudicate_events(repo)) == 2
    assert len(all_adjudicate_events(repo, "title-abstract")) == 1
    assert len(all_adjudicate_events(repo, "full-text")) == 1


def test_resolve_record_state_uses_adjudication_over_conflicting_opinions(tmp_path: Path) -> None:
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
        decision="maybe",
        actor="sam",
    )
    from strata.core.events import append_new_event

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
    state = resolve_record_state(repo, "title-abstract", "rec_0000000000000001")
    assert state.status == "include"
    assert state.adjudication is not None


def test_resolve_record_state_tracks_fold_transitions(tmp_path: Path) -> None:
    repo = _init(tmp_path)
    _add_records(repo, ["rec_0000000000000001"])
    state = resolve_record_state(repo, "title-abstract", "rec_0000000000000001")
    assert state.status == "unscreened"

    record_screen_decision(
        repo,
        stage="title-abstract",
        record_id="rec_0000000000000001",
        decision="include",
        actor="ethan",
    )
    state = resolve_record_state(repo, "title-abstract", "rec_0000000000000001")
    assert state.status == "partial"


def test_resolve_record_state_conflict_and_agreement(tmp_path: Path) -> None:
    repo = _init(tmp_path)
    _add_records(repo, ["rec_0000000000000001", "rec_0000000000000002"])
    _add_exclusion_criterion(repo)

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
        decision="exclude",
        actor="sam",
        cited=["EXC-01"],
    )
    conflict_state = resolve_record_state(repo, "title-abstract", "rec_0000000000000001")
    assert conflict_state.status == "conflict"

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
    agree_state = resolve_record_state(repo, "title-abstract", "rec_0000000000000002")
    assert agree_state.status == "include"


def test_stage_queue_excludes_records_already_opined_and_unassigned(tmp_path: Path) -> None:
    repo = _init(tmp_path)
    _add_records(repo, ["rec_0000000000000001", "rec_0000000000000002"])
    assign_reviewers(
        repo,
        stage="title-abstract",
        actors=["ethan"],
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
    queue = stage_queue(repo, "title-abstract", "ethan")
    assert queue == ["rec_0000000000000002"]

    queue_sam = stage_queue(repo, "title-abstract", "sam")
    # sam is still assigned to record 1 by the config default (record 2 was
    # overridden to ethan-only), and has not opined on it yet.
    assert queue_sam == ["rec_0000000000000001"]


def test_stage_queue_only_ids_filter(tmp_path: Path) -> None:
    repo = _init(tmp_path)
    _add_records(repo, ["rec_0000000000000001", "rec_0000000000000002"])
    queue = stage_queue(repo, "title-abstract", "ethan", only_ids={"rec_0000000000000002"})
    assert queue == ["rec_0000000000000002"]


def test_stage_queue_rejects_unknown_stage(tmp_path: Path) -> None:
    repo = _init(tmp_path)
    with pytest.raises(ScreeningError, match="unknown stage"):
        stage_queue(repo, "bogus", "ethan")


def test_import_decisions_tsv_happy_path(tmp_path: Path) -> None:
    repo = _init(tmp_path)
    _add_records(repo, ["rec_0000000000000001", "rec_0000000000000002"])
    _add_exclusion_criterion(repo)
    text = (
        "record_id\tdecision\tcriteria\tnote\n"
        "rec_0000000000000001\tinclude\t\t\n"
        "rec_0000000000000002\texclude\tEXC-01\trodent model\n"
    )
    envelopes = import_decisions_tsv(repo, stage="title-abstract", text=text, actor="ethan")
    assert len(envelopes) == 2
    assert all(e["body"]["imported"] is True for e in envelopes)
    assert envelopes[1]["body"]["criteria"] == ["EXC-01"]
    assert envelopes[1]["body"]["note"] == "rodent model"


def test_import_decisions_tsv_empty_text_returns_no_events(tmp_path: Path) -> None:
    repo = _init(tmp_path)
    assert import_decisions_tsv(repo, stage="title-abstract", text="", actor="ethan") == []


def test_import_decisions_tsv_rejects_bad_header(tmp_path: Path) -> None:
    repo = _init(tmp_path)
    with pytest.raises(ScreeningError, match="header"):
        import_decisions_tsv(repo, stage="title-abstract", text="wrong\theader\n", actor="ethan")


def test_import_decisions_tsv_rejects_wrong_column_count(tmp_path: Path) -> None:
    repo = _init(tmp_path)
    text = "record_id\tdecision\tcriteria\tnote\nrec_0001\tinclude\n"
    with pytest.raises(ScreeningError, match="expected 4 columns"):
        import_decisions_tsv(repo, stage="title-abstract", text=text, actor="ethan")


def test_import_decisions_tsv_propagates_row_validation_errors(tmp_path: Path) -> None:
    repo = _init(tmp_path)
    _add_records(repo, ["rec_0000000000000001"])
    text = "record_id\tdecision\tcriteria\tnote\nrec_0000000000000001\texclude\t\t\n"
    with pytest.raises(ScreeningError, match="require_exclusion_reason"):
        import_decisions_tsv(repo, stage="title-abstract", text=text, actor="ethan")
