from pathlib import Path

import pytest

from strata.core.events import read_events
from strata.core.init import init_repository
from strata.core.repo import open_repo
from strata.core.validate import SchemaValidationError
from strata.protocol.criteria import (
    CriteriaError,
    add_criterion,
    diff_versions,
    edit_criterion,
    get_criterion,
    list_criteria,
    next_criterion_id,
    per_criterion_digest,
    read_criteria_doc,
    reconstruct_at_version,
    retire_criterion,
    set_digest,
)


def _init(tmp_path: Path) -> Path:
    root = tmp_path / "review"
    init_repository(root, title="T", actor_handle="ethan", actor_name="Ethan")
    return root


def _events_path(repo, actor: str = "ethan"):  # type: ignore[no-untyped-def]
    return repo.path("events", "criteria", f"{actor}.ndjson")


def test_fresh_repo_starts_at_version_zero(tmp_path: Path) -> None:
    repo = open_repo(_init(tmp_path))
    doc = read_criteria_doc(repo)
    assert doc["version"] == 0
    assert doc["criteria"] == []


def test_read_criteria_doc_missing_file_returns_empty(tmp_path: Path) -> None:
    repo = open_repo(_init(tmp_path))
    repo.path("protocol", "criteria.yaml").unlink()
    assert read_criteria_doc(repo) == {"version": 0, "digest": set_digest([]), "criteria": []}


def test_read_criteria_doc_blank_file_returns_empty(tmp_path: Path) -> None:
    repo = open_repo(_init(tmp_path))
    repo.path("protocol", "criteria.yaml").write_text("", encoding="utf-8")
    assert read_criteria_doc(repo) == {"version": 0, "digest": set_digest([]), "criteria": []}


def test_get_criterion_returns_none_when_absent(tmp_path: Path) -> None:
    repo = open_repo(_init(tmp_path))
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
    assert get_criterion(repo, "EXC-01") is not None
    assert get_criterion(repo, "EXC-99") is None


def test_all_criteria_change_events_empty_before_any_directory(tmp_path: Path) -> None:
    from strata.protocol.criteria import all_criteria_change_events

    repo = open_repo(_init(tmp_path))
    assert all_criteria_change_events(repo) == []


def test_add_criterion_stores_examples(tmp_path: Path) -> None:
    repo = open_repo(_init(tmp_path))
    criterion = add_criterion(
        repo,
        kind="inclusion",
        label="RCT",
        definition="A randomised controlled trial.",
        applies_at=["title-abstract"],
        actor="ethan",
        rationale="Establishing the initial protocol criteria.",
        criterion_id="INC-01",
        examples={"include": ["An RCT of X"], "exclude": ["A cohort study of X"]},
    )
    assert criterion["examples"] == {"include": ["An RCT of X"], "exclude": ["A cohort study of X"]}
    reloaded = get_criterion(repo, "INC-01")
    assert reloaded is not None
    assert reloaded["examples"]["include"] == ["An RCT of X"]


def test_edit_criterion_rejects_label_over_80_chars(tmp_path: Path) -> None:
    repo = open_repo(_init(tmp_path))
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
    with pytest.raises(CriteriaError, match="80 characters"):
        edit_criterion(
            repo,
            "EXC-01",
            direction="editorial",
            actor="ethan",
            rationale="Testing an overlong label on edit.",
            label="x" * 81,
        )


def test_edit_criterion_rejects_empty_definition(tmp_path: Path) -> None:
    repo = open_repo(_init(tmp_path))
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
    with pytest.raises(CriteriaError, match="definition must not be empty"):
        edit_criterion(
            repo,
            "EXC-01",
            direction="tightened",
            actor="ethan",
            rationale="Testing an empty definition on edit.",
            definition="   ",
        )


def test_edit_criterion_updates_examples(tmp_path: Path) -> None:
    repo = open_repo(_init(tmp_path))
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
    updated = edit_criterion(
        repo,
        "EXC-01",
        direction="editorial",
        actor="ethan",
        rationale="Adding calibration examples for this criterion.",
        examples={"exclude": ["A rodent study"]},
    )
    assert updated["examples"] == {"exclude": ["A rodent study"]}


def test_add_criterion_bumps_version_to_one_and_sets_since_version(tmp_path: Path) -> None:
    repo = open_repo(_init(tmp_path))
    criterion = add_criterion(
        repo,
        kind="inclusion",
        label="Empirical study",
        definition="Reports original empirical data.",
        applies_at=["title-abstract", "full-text"],
        actor="ethan",
        rationale="Establishing the initial protocol criteria.",
    )
    assert criterion["id"] == "INC-01"
    assert criterion["since_version"] == 1
    assert criterion["status"] == "active"
    doc = read_criteria_doc(repo)
    assert doc["version"] == 1
    assert doc["digest"] == set_digest(doc["criteria"])


def test_add_criterion_ids_increment_per_kind_prefix(tmp_path: Path) -> None:
    repo = open_repo(_init(tmp_path))
    inc = add_criterion(
        repo,
        kind="inclusion",
        label="A",
        definition="def a",
        applies_at=["title-abstract"],
        actor="ethan",
        rationale="Setting up criteria for the first time.",
    )
    exc = add_criterion(
        repo,
        kind="exclusion",
        label="B",
        definition="def b",
        applies_at=["title-abstract"],
        actor="ethan",
        rationale="Setting up criteria for the first time.",
    )
    inc2 = add_criterion(
        repo,
        kind="inclusion",
        label="C",
        definition="def c",
        applies_at=["title-abstract"],
        actor="ethan",
        rationale="Setting up criteria for the first time.",
    )
    assert inc["id"] == "INC-01"
    assert exc["id"] == "EXC-01"
    assert inc2["id"] == "INC-02"
    assert next_criterion_id(repo, "inclusion") == "INC-03"


def test_add_criterion_rejects_duplicate_id(tmp_path: Path) -> None:
    repo = open_repo(_init(tmp_path))
    add_criterion(
        repo,
        kind="inclusion",
        label="A",
        definition="def a",
        applies_at=["title-abstract"],
        actor="ethan",
        rationale="Setting up criteria for the first time.",
        criterion_id="INC-01",
    )
    with pytest.raises(CriteriaError, match="already exists"):
        add_criterion(
            repo,
            kind="inclusion",
            label="A2",
            definition="def a2",
            applies_at=["title-abstract"],
            actor="ethan",
            rationale="Trying to reuse an existing criterion id.",
            criterion_id="INC-01",
        )


def test_add_criterion_rejects_bad_kind(tmp_path: Path) -> None:
    repo = open_repo(_init(tmp_path))
    with pytest.raises(CriteriaError, match="kind"):
        add_criterion(
            repo,
            kind="bogus",  # type: ignore[arg-type]
            label="A",
            definition="def a",
            applies_at=["title-abstract"],
            actor="ethan",
            rationale="Testing an invalid kind value here.",
        )


def test_add_criterion_rejects_empty_label_and_definition(tmp_path: Path) -> None:
    repo = open_repo(_init(tmp_path))
    with pytest.raises(CriteriaError, match="label"):
        add_criterion(
            repo,
            kind="inclusion",
            label="   ",
            definition="def a",
            applies_at=["title-abstract"],
            actor="ethan",
            rationale="Testing an empty label value here.",
        )
    with pytest.raises(CriteriaError, match="definition"):
        add_criterion(
            repo,
            kind="inclusion",
            label="A",
            definition="   ",
            applies_at=["title-abstract"],
            actor="ethan",
            rationale="Testing an empty definition value here.",
        )


def test_add_criterion_rejects_label_over_80_chars(tmp_path: Path) -> None:
    repo = open_repo(_init(tmp_path))
    with pytest.raises(CriteriaError, match="80 characters"):
        add_criterion(
            repo,
            kind="inclusion",
            label="x" * 81,
            definition="def a",
            applies_at=["title-abstract"],
            actor="ethan",
            rationale="Testing an overlong label value here.",
        )


def test_add_criterion_rejects_empty_applies_at(tmp_path: Path) -> None:
    repo = open_repo(_init(tmp_path))
    with pytest.raises(CriteriaError, match="applies_at must be non-empty"):
        add_criterion(
            repo,
            kind="inclusion",
            label="A",
            definition="def a",
            applies_at=[],
            actor="ethan",
            rationale="Testing an empty applies_at value here.",
        )


def test_add_criterion_rejects_unconfigured_stage(tmp_path: Path) -> None:
    repo = open_repo(_init(tmp_path))
    with pytest.raises(CriteriaError, match="unconfigured stage"):
        add_criterion(
            repo,
            kind="inclusion",
            label="A",
            definition="def a",
            applies_at=["not-a-real-stage"],
            actor="ethan",
            rationale="Testing an unconfigured stage value here.",
        )


def test_add_criterion_rejects_malformed_custom_id(tmp_path: Path) -> None:
    repo = open_repo(_init(tmp_path))
    with pytest.raises(CriteriaError, match="INC-01 or EXC-01"):
        add_criterion(
            repo,
            kind="inclusion",
            label="A",
            definition="def a",
            applies_at=["title-abstract"],
            actor="ethan",
            rationale="Testing a malformed custom criterion id.",
            criterion_id="NOTVALID",
        )


def test_add_criterion_emits_criteria_change_event_with_added_origin(tmp_path: Path) -> None:
    repo = open_repo(_init(tmp_path))
    add_criterion(
        repo,
        kind="exclusion",
        label="Animal model",
        definition="The sample is non-human.",
        applies_at=["title-abstract"],
        actor="ethan",
        rationale="Establishing the initial protocol criteria.",
    )
    events = read_events(_events_path(repo))
    assert len(events) == 1
    assert events[0]["ev"] == "criteria-change"
    body = events[0]["body"]
    assert body["from_version"] == 0
    assert body["to_version"] == 1
    assert body["rationale"] == "Establishing the initial protocol criteria."
    (delta,) = body["deltas"]
    assert delta["id"] == "EXC-01"
    assert delta["origin"] == "added"
    assert delta["direction"] == "tightened"


def test_edit_criterion_requires_direction_and_applies_it(tmp_path: Path) -> None:
    repo = open_repo(_init(tmp_path))
    add_criterion(
        repo,
        kind="exclusion",
        label="Not in English",
        definition="Publications not written in English.",
        applies_at=["title-abstract"],
        actor="ethan",
        rationale="Establishing the initial protocol criteria.",
        criterion_id="EXC-03",
    )
    updated = edit_criterion(
        repo,
        "EXC-03",
        direction="tightened",
        actor="ethan",
        rationale="Narrowing the language criterion after pilot screening.",
        definition=(
            "Publications not written in English, and publications in English "
            "translation where the original instrument was not validated."
        ),
    )
    assert updated["since_version"] == 1  # unchanged: since_version never moves
    doc = read_criteria_doc(repo)
    assert doc["version"] == 2
    events = read_events(_events_path(repo))
    assert events[-1]["body"]["deltas"][0]["origin"] == "edited"
    assert events[-1]["body"]["deltas"][0]["direction"] == "tightened"


def test_edit_criterion_rejects_unknown_id(tmp_path: Path) -> None:
    repo = open_repo(_init(tmp_path))
    with pytest.raises(CriteriaError, match="no criterion"):
        edit_criterion(
            repo,
            "EXC-99",
            direction="tightened",
            actor="ethan",
            rationale="Testing edit against an unknown criterion id.",
            definition="new definition",
        )


def test_edit_criterion_rejects_bad_direction(tmp_path: Path) -> None:
    repo = open_repo(_init(tmp_path))
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
    with pytest.raises(CriteriaError, match="direction"):
        edit_criterion(
            repo,
            "EXC-01",
            direction="sideways",  # type: ignore[arg-type]
            actor="ethan",
            rationale="Testing an invalid direction value here.",
            definition="def a2",
        )


def test_edit_criterion_rejects_retired_criterion(tmp_path: Path) -> None:
    repo = open_repo(_init(tmp_path))
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
    retire_criterion(repo, "EXC-01", actor="ethan", rationale="No longer relevant to the review.")
    with pytest.raises(CriteriaError, match="retired and cannot be edited"):
        edit_criterion(
            repo,
            "EXC-01",
            direction="tightened",
            actor="ethan",
            rationale="Testing edit against a retired criterion.",
            definition="def a2",
        )


def test_edit_criterion_rejects_no_op_change(tmp_path: Path) -> None:
    repo = open_repo(_init(tmp_path))
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
    with pytest.raises(CriteriaError, match="no change was made"):
        edit_criterion(
            repo,
            "EXC-01",
            direction="editorial",
            actor="ethan",
            rationale="Testing a no-op edit with nothing changed.",
        )


def test_edit_criterion_editorial_guard_allows_whitespace_only_change(tmp_path: Path) -> None:
    repo = open_repo(_init(tmp_path))
    add_criterion(
        repo,
        kind="exclusion",
        label="A",
        definition="def a   with   spacing",
        applies_at=["title-abstract"],
        actor="ethan",
        rationale="Establishing the initial protocol criteria.",
        criterion_id="EXC-01",
    )
    updated = edit_criterion(
        repo,
        "EXC-01",
        direction="editorial",
        actor="ethan",
        rationale="Cleaning up whitespace in the definition text.",
        definition="def a with spacing",
    )
    assert updated["definition"] == "def a with spacing"


def test_edit_criterion_editorial_guard_refuses_meaning_change(tmp_path: Path) -> None:
    repo = open_repo(_init(tmp_path))
    add_criterion(
        repo,
        kind="exclusion",
        label="Not in English",
        definition="Publications not written in English.",
        applies_at=["title-abstract"],
        actor="ethan",
        rationale="Establishing the initial protocol criteria.",
        criterion_id="EXC-03",
    )
    with pytest.raises(CriteriaError, match="editorial asserts no semantic change"):
        edit_criterion(
            repo,
            "EXC-03",
            direction="editorial",
            actor="ethan",
            rationale="Trying to sneak a meaning change past as editorial.",
            definition="Publications not written in English or French.",
        )


def test_edit_criterion_editorial_guard_refuses_applies_at_change(tmp_path: Path) -> None:
    repo = open_repo(_init(tmp_path))
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
    with pytest.raises(CriteriaError, match="editorial asserts no semantic change"):
        edit_criterion(
            repo,
            "EXC-01",
            direction="editorial",
            actor="ethan",
            rationale="Trying to widen applies_at under an editorial label.",
            applies_at=["title-abstract", "full-text"],
        )


def test_edit_criterion_label_only_change_permits_editorial(tmp_path: Path) -> None:
    repo = open_repo(_init(tmp_path))
    add_criterion(
        repo,
        kind="exclusion",
        label="Old label",
        definition="def a",
        applies_at=["title-abstract"],
        actor="ethan",
        rationale="Establishing the initial protocol criteria.",
        criterion_id="EXC-01",
    )
    updated = edit_criterion(
        repo,
        "EXC-01",
        direction="editorial",
        actor="ethan",
        rationale="Relabelling for clarity, no semantic change intended.",
        label="New label",
    )
    assert updated["label"] == "New label"
    assert updated["definition"] == "def a"


def test_retire_criterion_marks_retired_and_never_reused(tmp_path: Path) -> None:
    repo = open_repo(_init(tmp_path))
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
    retired = retire_criterion(repo, "EXC-01", actor="ethan", rationale="No longer relevant.")
    assert retired["status"] == "retired"
    doc = read_criteria_doc(repo)
    assert doc["version"] == 2
    # Retired entries stay in the file forever.
    assert get_criterion(repo, "EXC-01") is not None
    with pytest.raises(CriteriaError, match="already exists"):
        add_criterion(
            repo,
            kind="exclusion",
            label="B",
            definition="def b",
            applies_at=["title-abstract"],
            actor="ethan",
            rationale="Trying to reuse a retired criterion id.",
            criterion_id="EXC-01",
        )


def test_retire_criterion_rejects_unknown_and_already_retired(tmp_path: Path) -> None:
    repo = open_repo(_init(tmp_path))
    with pytest.raises(CriteriaError, match="no criterion"):
        retire_criterion(repo, "EXC-99", actor="ethan", rationale="Testing unknown retirement.")
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
    retire_criterion(repo, "EXC-01", actor="ethan", rationale="No longer relevant.")
    with pytest.raises(CriteriaError, match="already retired"):
        retire_criterion(repo, "EXC-01", actor="ethan", rationale="Testing double retirement.")


def test_list_criteria_filters_by_stage(tmp_path: Path) -> None:
    repo = open_repo(_init(tmp_path))
    add_criterion(
        repo,
        kind="exclusion",
        label="TA only",
        definition="def a",
        applies_at=["title-abstract"],
        actor="ethan",
        rationale="Establishing the initial protocol criteria.",
        criterion_id="EXC-01",
    )
    add_criterion(
        repo,
        kind="exclusion",
        label="FT only",
        definition="def b",
        applies_at=["full-text"],
        actor="ethan",
        rationale="Establishing the initial protocol criteria.",
        criterion_id="EXC-02",
    )
    assert [c["id"] for c in list_criteria(repo, at="title-abstract")] == ["EXC-01"]
    assert [c["id"] for c in list_criteria(repo, at="full-text")] == ["EXC-02"]
    assert {c["id"] for c in list_criteria(repo)} == {"EXC-01", "EXC-02"}


def test_reconstruct_at_version_replays_deltas(tmp_path: Path) -> None:
    repo = open_repo(_init(tmp_path))
    add_criterion(
        repo,
        kind="exclusion",
        label="Not in English",
        definition="Publications not written in English.",
        applies_at=["title-abstract"],
        actor="ethan",
        rationale="Establishing the initial protocol criteria.",
        criterion_id="EXC-03",
    )
    edit_criterion(
        repo,
        "EXC-03",
        direction="tightened",
        actor="ethan",
        rationale="Narrowing the language criterion after pilot screening.",
        definition="Publications not written in English, translations included.",
    )
    add_criterion(
        repo,
        kind="exclusion",
        label="Under 18",
        definition="Mean sample age under 18.",
        applies_at=["full-text"],
        actor="ethan",
        rationale="Adding an age criterion after pilot extraction.",
        criterion_id="EXC-07",
    )

    at_v1 = reconstruct_at_version(repo, 1)
    assert len(at_v1) == 1
    assert at_v1[0]["definition"] == "Publications not written in English."

    at_v2 = reconstruct_at_version(repo, 2)
    assert len(at_v2) == 1
    assert "translations included" in at_v2[0]["definition"]

    at_v3 = reconstruct_at_version(repo, 3)
    assert {c["id"] for c in at_v3} == {"EXC-03", "EXC-07"}

    assert list_criteria(repo, version=1) == at_v1


def test_diff_versions_returns_deltas_in_range(tmp_path: Path) -> None:
    repo = open_repo(_init(tmp_path))
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
    edit_criterion(
        repo,
        "EXC-01",
        direction="loosened",
        actor="ethan",
        rationale="Relaxing this criterion after a protocol review.",
        definition="def a, relaxed",
    )
    add_criterion(
        repo,
        kind="exclusion",
        label="B",
        definition="def b",
        applies_at=["title-abstract"],
        actor="ethan",
        rationale="Adding a second exclusion criterion.",
        criterion_id="EXC-02",
    )

    deltas_1_to_2 = diff_versions(repo, 1, 2)
    assert [d["id"] for d in deltas_1_to_2] == ["EXC-01"]
    assert deltas_1_to_2[0]["origin"] == "edited"

    deltas_0_to_3 = diff_versions(repo, 0, 3)
    assert [d["id"] for d in deltas_0_to_3] == ["EXC-01", "EXC-01", "EXC-02"]


def test_diff_versions_rejects_non_increasing_range(tmp_path: Path) -> None:
    repo = open_repo(_init(tmp_path))
    with pytest.raises(CriteriaError, match="must be greater"):
        diff_versions(repo, 2, 1)
    with pytest.raises(CriteriaError, match="must be greater"):
        diff_versions(repo, 1, 1)


def test_per_criterion_digest_ignores_label_and_examples() -> None:
    base = {
        "id": "EXC-01",
        "kind": "exclusion",
        "definition": "def",
        "applies_at": ["title-abstract"],
        "label": "Label one",
    }
    relabelled = {**base, "label": "A completely different label"}
    assert per_criterion_digest(base) == per_criterion_digest(relabelled)

    changed_definition = {**base, "definition": "a different definition"}
    assert per_criterion_digest(base) != per_criterion_digest(changed_definition)


def test_set_digest_empty_is_stable() -> None:
    assert set_digest([]) == set_digest([])
    assert set_digest([]).startswith("sha256:")


def test_add_criterion_writes_schema_valid_yaml(tmp_path: Path) -> None:
    repo = open_repo(_init(tmp_path))
    add_criterion(
        repo,
        kind="inclusion",
        label="Empirical",
        definition="Original empirical data.",
        applies_at=["title-abstract"],
        actor="ethan",
        rationale="Establishing the initial protocol criteria.",
    )
    # A second, unrelated write must still validate cleanly against the schema.
    doc = read_criteria_doc(repo)
    from strata.core.validate import validate

    validate("criteria", doc)


def test_add_criterion_rejects_corrupted_existing_entry(tmp_path: Path) -> None:
    repo = open_repo(_init(tmp_path))
    bad_doc = (
        "version: 1\n"
        f'digest: "sha256:{"0" * 64}"\n'
        "criteria:\n"
        "  - id: BAD-ID\n"
        "    kind: exclusion\n"
        "    label: Bad\n"
        "    definition: def\n"
        "    applies_at: [title-abstract]\n"
        "    since_version: 1\n"
        "    status: active\n"
    )
    repo.path("protocol", "criteria.yaml").write_text(bad_doc, encoding="utf-8")
    with pytest.raises(SchemaValidationError):
        add_criterion(
            repo,
            kind="inclusion",
            label="A",
            definition="def a",
            applies_at=["title-abstract"],
            actor="ethan",
            rationale="Testing schema validation on a corrupted manual write.",
        )
