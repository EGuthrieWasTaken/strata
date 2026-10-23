"""Extraction records, effect entry, warnings and completeness (openspec:data-extraction)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from strata.core.canon import dump_yaml_str
from strata.core.events import read_events
from strata.core.ids import singleton_study_id
from strata.extract import effects as effects_mod
from strata.extract import records as rec_mod
from strata.extract import schema as schema_mod
from strata.extract import units as units_mod
from strata.stats import escalc as es
from tests.unit._m3 import add_records, decide, init_review, rpt

FORM: dict[str, Any] = {
    "version": 1,
    "fields": [
        {"name": "n_total", "label": "N", "type": "integer", "required": True, "min": 1},
        {
            "name": "design",
            "type": "categorical",
            "required": True,
            "levels": ["rct", "quasi-experimental"],
        },
        {
            "name": "retention_interval",
            "type": "quantity",
            "required": True,
            "unit": "hours",
            "accepts_units": ["minutes", "hours", "days", "weeks"],
            "min": 0,
        },
        {"name": "mean_age", "type": "number", "min": 0, "max": 120},
        {"name": "blinded", "type": "boolean"},
        {"name": "countries", "type": "multi-categorical", "levels": ["us", "uk", "de"]},
        {"name": "start", "type": "date"},
        {"name": "notes", "type": "text"},
        {"name": "ref", "type": "citation"},
    ],
    "effects": {"outcomes": ["recall", "recognition"]},
}


def study(n: int) -> str:
    return singleton_study_id(rpt(n))


def _review(tmp_path: Path, *, mode: str = "single", studies: int = 3):  # type: ignore[no-untyped-def]
    repo = init_review(tmp_path)
    if mode != "single":
        manifest = repo.path("strata.toml")
        manifest.write_text(manifest.read_text() + f'\n[extraction]\nmode = "{mode}"\n')
        from strata.core.repo import open_repo

        repo = open_repo(repo.root)
    decide(repo, "full-text", add_records(repo, studies))
    repo.path("extraction").mkdir(exist_ok=True)
    repo.path("extraction", "schema.yaml").write_text(dump_yaml_str(FORM), encoding="utf-8")
    return repo


REGISTRY = units_mod.UnitRegistry()


def _spec(name: str) -> dict[str, Any]:
    return schema_mod.parse_schema(FORM).field(name) or {}


# --- coercing values -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "raw", "expected"),
    [
        ("n_total", "148", {"value": 148}),
        ("n_total", "1,048", {"value": 1048}),
        ("mean_age", "20.4", {"value": 20.4}),
        ("mean_age", "20", {"value": 20}),
        ("design", "RCT", {"value": "rct"}),
        ("blinded", "Yes", {"value": True}),
        ("blinded", "0", {"value": False}),
        ("countries", "UK, us", {"value": ["uk", "us"]}),
        ("start", "2026-03-28", {"value": "2026-03-28"}),
        ("start", "2026-03", {"value": "2026-03"}),
        ("notes", "  free text ", {"value": "free text"}),
        ("ref", "Cepeda 2008", {"value": "Cepeda 2008"}),
        ("n_total", "NR", {"value": None, "not_reported": True}),
        ("design", "not reported", {"value": None, "not_reported": True}),
    ],
)
def test_values_are_coerced_to_their_field_type(
    name: str, raw: str, expected: dict[str, Any]
) -> None:
    assert rec_mod.coerce_value(_spec(name), raw, REGISTRY) == expected


@pytest.mark.parametrize(
    ("name", "raw", "message"),
    [
        ("n_total", "", "required"),
        ("n_total", "abc", "not a number"),
        ("n_total", "14.5", "whole number"),
        ("n_total", "0", "below the minimum"),
        ("mean_age", "130", "above the maximum"),
        ("design", "cohort", "not one of"),
        ("blinded", "maybe", "yes or no"),
        ("countries", "fr", "not in"),
        ("countries", " , ", "not in"),
        ("start", "yesterday", "YYYY"),
        ("start", "2026-02-31", "day is out of range"),
        ("retention_interval", "2 fortnights", "E_UNIT"),
        ("retention_interval", "-5 hours", "below the minimum"),
    ],
)
def test_bad_values_are_refused_with_a_reason(name: str, raw: str, message: str) -> None:
    with pytest.raises((rec_mod.ExtractionError, ValueError), match=message):
        rec_mod.coerce_value(_spec(name), raw, REGISTRY)


def test_quantities_store_the_entered_and_the_normalised_value() -> None:
    """openspec scenario: '1 week' into an hours field -> 168 hours, entered '1 week'."""
    assert rec_mod.coerce_value(_spec("retention_interval"), "1 week", REGISTRY) == {
        "value": 168,
        "unit": "hours",
        "entered": "1 week",
    }


def test_a_bare_number_in_a_quantity_field_is_in_the_fields_own_unit() -> None:
    assert rec_mod.coerce_value(_spec("retention_interval"), "24", REGISTRY) == {
        "value": 24,
        "unit": "hours",
        "entered": "24",
    }
    assert rec_mod.coerce_value(_spec("retention_interval"), "1.5", REGISTRY)["value"] == 1.5


def test_a_source_locator_rides_along_with_the_value() -> None:
    assert rec_mod.split_source("148 @ p. 1097, para 2") == ("148", "p. 1097, para 2")
    assert rec_mod.split_source("148") == ("148", None)
    assert rec_mod.split_source("a@b.org") == ("a@b.org", None)  # an email is not a locator


# --- saving ----------------------------------------------------------------------------------


def test_setting_a_field_writes_the_consensus_file_and_logs_an_event(tmp_path: Path) -> None:
    repo = _review(tmp_path)
    entry = rec_mod.set_field(
        repo, study=study(1), handle="ethan", name="n_total", raw="148 @ p. 1097"
    )
    assert entry == {"value": 148, "source": "p. 1097"}
    path = rec_mod.consensus_path(repo, study(1))
    saved = rec_mod.read_record(path)
    assert saved is not None
    assert saved["study"] == study(1) and saved["reports"] == [rpt(1)]
    assert saved["extracted_by"] == ["ethan"] and saved["schema_version"] == 1
    assert saved["fields"]["n_total"] == {"value": 148, "source": "p. 1097"}
    [event] = read_events(repo.path("events", "extract", "ethan.ndjson"))
    assert event["body"]["study"] == study(1) and event["body"]["fields_changed"] == ["n_total"]
    assert event["body"]["digest"].startswith("sha256:")
    assert path.read_text(encoding="utf-8").startswith("study: ")


def test_a_second_extractor_is_added_and_a_value_can_be_replaced(tmp_path: Path) -> None:
    repo = _review(tmp_path)
    rec_mod.set_field(repo, study=study(1), handle="ethan", name="n_total", raw="148")
    rec_mod.set_field(
        repo, study=study(1), handle="sam", name="n_total", raw="150", source="Table 1"
    )
    saved = rec_mod.read_record(rec_mod.consensus_path(repo, study(1)))
    assert saved is not None
    assert saved["extracted_by"] == ["ethan", "sam"]
    assert saved["fields"]["n_total"] == {"value": 150, "source": "Table 1"}


def test_fields_are_written_in_the_forms_order(tmp_path: Path) -> None:
    repo = _review(tmp_path)
    for name, raw in (("notes", "x"), ("retention_interval", "1 week"), ("n_total", "9")):
        rec_mod.set_field(repo, study=study(1), handle="ethan", name=name, raw=raw)
    text = rec_mod.consensus_path(repo, study(1)).read_text(encoding="utf-8")
    assert text.index("n_total:") < text.index("retention_interval:") < text.index("notes:")
    assert "entered: 1 week" in text


def test_dual_mode_extractors_write_their_own_files(tmp_path: Path) -> None:
    repo = _review(tmp_path, mode="dual")
    rec_mod.set_field(repo, study=study(1), handle="ethan", name="n_total", raw="148")
    rec_mod.set_field(repo, study=study(1), handle="sam", name="n_total", raw="150")
    assert not rec_mod.consensus_path(repo, study(1)).exists()
    ethan = rec_mod.read_record(rec_mod.reviewer_path(repo, "ethan", study(1)))
    sam = rec_mod.read_record(rec_mod.reviewer_path(repo, "sam", study(1)))
    assert ethan is not None and sam is not None
    assert ethan["fields"]["n_total"]["value"] == 148 and sam["fields"]["n_total"]["value"] == 150
    assert ethan["extracted_by"] == ["ethan"]


def test_setting_a_field_refuses_unknown_fields_studies_and_values(tmp_path: Path) -> None:
    repo = _review(tmp_path)
    with pytest.raises(rec_mod.ExtractionError, match="no field"):
        rec_mod.set_field(repo, study=study(1), handle="ethan", name="shoe_size", raw="9")
    with pytest.raises(rec_mod.ExtractionError, match="no included study"):
        rec_mod.set_field(repo, study="std_" + "9" * 16, handle="ethan", name="n_total", raw="9")
    with pytest.raises(rec_mod.ExtractionError, match="below the minimum"):
        rec_mod.set_field(repo, study=study(1), handle="ethan", name="n_total", raw="0")
    assert not rec_mod.consensus_path(repo, study(1)).exists()  # nothing half-written


# --- effects ---------------------------------------------------------------------------------

MEANS = {"n1": 74, "m1": 0.62, "sd1": 0.18, "n2": 74, "m2": 0.48, "sd2": 0.21}


def test_an_effect_is_saved_with_an_id_and_shows_its_computed_size(tmp_path: Path) -> None:
    repo = _review(tmp_path)
    result = rec_mod.add_effect(
        repo,
        study=study(1),
        handle="ethan",
        outcome="recall",
        design="two-group-means",
        inputs=MEANS,
        timepoint="1 week",
        source="Table 2",
        moderators={"dose": 3},
    )
    assert result.computed is not None and result.computed.measure == "SMD"
    assert result.computed.yi == pytest.approx(es.smd(0.62, 0.18, 74, 0.48, 0.21, 74).yi)
    assert result.effect["id"] == f"eff_{study(1)[4:]}_0001"
    saved = rec_mod.read_record(rec_mod.consensus_path(repo, study(1)))
    assert saved is not None
    [effect] = saved["effects"]
    assert effect["moderators"] == {"dose": 3} and effect["source"] == "Table 2"
    [event] = read_events(repo.path("events", "extract", "ethan.ndjson"))
    assert event["body"]["fields_changed"] == ["effects:recall|1 week|"]


def test_the_same_outcome_and_timepoint_replaces_the_effect_and_keeps_its_id(
    tmp_path: Path,
) -> None:
    repo = _review(tmp_path)
    kwargs: dict[str, Any] = {"study": study(1), "handle": "ethan", "outcome": "recall"}
    first = rec_mod.add_effect(repo, design="two-group-means", inputs=MEANS, **kwargs)
    second = rec_mod.add_effect(
        repo, design="two-group-means", inputs={**MEANS, "m1": 0.7}, **kwargs
    )
    third = rec_mod.add_effect(
        repo, design="t-test", inputs={"t": 2.5, "n1": 30, "n2": 30}, timepoint="2 weeks", **kwargs
    )
    assert second.effect["id"] == first.effect["id"]
    assert third.effect["id"].endswith("_0002")
    saved = rec_mod.read_record(rec_mod.consensus_path(repo, study(1)))
    assert saved is not None and len(saved["effects"]) == 2
    assert saved["effects"][0]["m1"] == 0.7


def test_dual_mode_effects_get_their_ids_at_reconciliation_not_entry(tmp_path: Path) -> None:
    repo = _review(tmp_path, mode="dual")
    result = rec_mod.add_effect(
        repo,
        study=study(1),
        handle="ethan",
        outcome="recall",
        design="two-group-means",
        inputs=MEANS,
    )
    assert "id" not in result.effect


def test_sd_may_be_reported_as_se_or_a_confidence_interval(tmp_path: Path) -> None:
    repo = _review(tmp_path)
    with_sd = rec_mod.preview_effect(
        repo, study=None, design="two-group-means", inputs=MEANS
    ).computed
    as_se = {**MEANS, "se1": 0.18 / 74**0.5, "se2": 0.21 / 74**0.5}
    del as_se["sd1"], as_se["sd2"]
    from_se = rec_mod.preview_effect(
        repo, study=None, design="two-group-means", inputs=as_se
    ).computed
    assert with_sd is not None and from_se is not None
    assert from_se.yi == pytest.approx(with_sd.yi)
    ci = {k: v for k, v in MEANS.items() if k not in ("sd1", "sd2")}
    ci.update(ci_lo1=0.58, ci_hi1=0.66, ci_lo2=0.43, ci_hi2=0.53)
    assert rec_mod.preview_effect(repo, study=None, design="two-group-means", inputs=ci).computed


def test_preview_with_partial_inputs_is_not_an_error(tmp_path: Path) -> None:
    repo = _review(tmp_path)
    assert (
        rec_mod.preview_effect(
            repo, study=None, design="two-group-means", inputs={"n1": 74}
        ).computed
        is None
    )
    typed = rec_mod.preview_effect(
        repo, study=None, design="t-test", inputs={"t": "2.5", "n1": "30", "n2": "30"}
    )
    assert typed.computed is not None  # strings typed on a command line become numbers


def test_an_effect_lacking_declared_inputs_is_refused_with_e_effect_inputs(tmp_path: Path) -> None:
    repo = _review(tmp_path)
    partial = {k: v for k, v in MEANS.items() if k != "sd2"}
    with pytest.raises(effects_mod.EffectInputError, match="E_EFFECT_INPUTS"):
        rec_mod.add_effect(
            repo,
            study=study(1),
            handle="ethan",
            outcome="recall",
            design="two-group-means",
            inputs=partial,
        )
    with pytest.raises(rec_mod.ExtractionError, match="not declared"):
        rec_mod.add_effect(
            repo, study=study(1), handle="ethan", outcome="recall", design="telepathy", inputs={}
        )
    with pytest.raises(rec_mod.ExtractionError, match="outcome"):
        rec_mod.add_effect(
            repo, study=study(1), handle="ethan", outcome="mood", design="t-test", inputs={}
        )
    assert not rec_mod.consensus_path(repo, study(1)).exists()


def test_inputs_that_cannot_make_an_effect_are_refused_not_stored(tmp_path: Path) -> None:
    repo = _review(tmp_path)
    flat = {**MEANS, "sd1": 0, "sd2": 0}
    with pytest.raises(es.EffectSizeError, match="undefined"):
        rec_mod.add_effect(
            repo,
            study=study(1),
            handle="ethan",
            outcome="recall",
            design="two-group-means",
            inputs=flat,
        )
    assert not rec_mod.consensus_path(repo, study(1)).exists()


# --- data-quality warnings -------------------------------------------------------------------


def test_an_implausibly_large_effect_warns_but_can_still_be_saved(tmp_path: Path) -> None:
    """openspec scenario: g = 4.2 -> a warning is shown and the value can still be saved."""
    repo = _review(tmp_path)
    huge = {"n1": 20, "m1": 9.0, "sd1": 1.0, "n2": 20, "m2": 4.5, "sd2": 1.0}
    result = rec_mod.add_effect(
        repo,
        study=study(1),
        handle="ethan",
        outcome="recall",
        design="two-group-means",
        inputs=huge,
    )
    assert [w.code for w in result.warnings] == ["large-effect"]
    assert rec_mod.consensus_path(repo, study(1)).exists()


def test_the_other_guards_fire_on_the_effects_they_describe(tmp_path: Path) -> None:
    repo = _review(tmp_path)
    codes = lambda design, inputs, **kw: sorted(  # noqa: E731
        w.code
        for w in rec_mod.preview_effect(
            repo, study=None, design=design, inputs=inputs, **kw
        ).warnings
    )
    assert codes("p-value-only", {"p": 0.04, "n1": 30, "n2": 30, "direction": 1}) == ["p-derived"]
    assert codes("two-group-binary", {"events1": 0, "n1": 20, "events2": 5, "n2": 20}) == [
        "zero-cell"
    ]
    assert codes("t-test", {"t": 2.2, "n1": 16, "n2": 16, "reported_p": 0.05}) == [
        "stat-p-inconsistent"
    ]
    assert codes("t-test", {"t": 2.2, "n1": 16, "n2": 16, "df": 30, "reported_p": 0.036}) == []
    assert codes(
        "f-test",
        {"F": 4.0, "df1": 1, "df2": 30, "n1": 16, "n2": 16, "direction": 1, "reported_p": 0.5},
    ) == ["stat-p-inconsistent"]


def test_sample_size_mismatch_uses_the_studys_n_total(tmp_path: Path) -> None:
    repo = _review(tmp_path)
    rec_mod.set_field(repo, study=study(1), handle="ethan", name="n_total", raw="148")
    mismatch = {**MEANS, "n1": 74, "n2": 73}
    result = rec_mod.preview_effect(
        repo, study=study(1), design="two-group-means", inputs=mismatch, outcome="recall"
    )
    assert [w.code for w in result.warnings] == ["n-inconsistent"]


def test_an_outlying_sd_is_judged_against_the_same_outcome_in_other_studies(tmp_path: Path) -> None:
    repo = _review(tmp_path)
    for n, sd in ((2, 0.20), (3, 0.22)):
        rec_mod.add_effect(
            repo,
            study=study(n),
            handle="ethan",
            outcome="recall",
            design="two-group-means",
            inputs={**MEANS, "sd1": sd, "sd2": sd},
        )
    weird = {**MEANS, "sd1": 2.0}
    result = rec_mod.preview_effect(
        repo, study=study(1), design="two-group-means", inputs=weird, outcome="recall"
    )
    assert "sd-outlier" in [w.code for w in result.warnings]


def test_an_acknowledged_warning_does_not_recur_and_is_in_the_log(tmp_path: Path) -> None:
    """openspec scenario: acknowledged with a note -> does not reappear; the event log has it."""
    repo = _review(tmp_path)
    huge = {"n1": 20, "m1": 9.0, "sd1": 1.0, "n2": 20, "m2": 4.5, "sd2": 1.0}
    rec_mod.add_effect(
        repo,
        study=study(1),
        handle="ethan",
        outcome="recall",
        design="two-group-means",
        inputs=huge,
    )
    record = rec_mod.read_record(rec_mod.consensus_path(repo, study(1)))
    assert record is not None
    [(key, code, _message)] = rec_mod.open_warnings(repo, study(1), record)
    assert code == "large-effect"
    with pytest.raises(rec_mod.ExtractionError, match="note"):
        rec_mod.acknowledge_warning(
            repo, study=study(1), effect=key, code=code, note=" ", actor="ethan"
        )
    with pytest.raises(rec_mod.ExtractionError, match="unknown warning"):
        rec_mod.acknowledge_warning(
            repo, study=study(1), effect=key, code="vibes", note="x", actor="ethan"
        )
    event = rec_mod.acknowledge_warning(
        repo,
        study=study(1),
        effect=key,
        code=code,
        note="Matches the paper's Table 2",
        actor="ethan",
    )
    assert event["body"]["text"] == "Matches the paper's Table 2"
    assert rec_mod.open_warnings(repo, study(1), record) == []
    assert (study(1), key, code) in rec_mod.acknowledged(repo)


# --- completeness and validation -------------------------------------------------------------


def test_a_new_required_field_makes_extractions_incomplete_not_invalid(tmp_path: Path) -> None:
    """openspec scenario: completed extractions + a new required field -> queued, none invalid."""
    repo = _review(tmp_path, studies=3)
    for n in (1, 2, 3):
        for name, raw in (("n_total", "100"), ("design", "rct"), ("retention_interval", "1 week")):
            rec_mod.set_field(repo, study=study(n), handle="ethan", name=name, raw=raw)
    assert rec_mod.studies_missing(repo) == {}

    grown = {
        **FORM,
        "version": 2,
        "fields": [*FORM["fields"], {"name": "setting", "type": "text", "required": True}],
    }
    repo.path("extraction", "schema.yaml").write_text(dump_yaml_str(grown), encoding="utf-8")
    assert rec_mod.studies_missing(repo) == {study(n): ["setting"] for n in (1, 2, 3)}

    schema = schema_mod.load_schema(repo)
    for n in (1, 2, 3):
        record = rec_mod.read_record(rec_mod.consensus_path(repo, study(n)))
        assert record is not None
        assert rec_mod.validate_record(record, schema, REGISTRY, where="x") == []  # not invalid
    rec_mod.set_field(repo, study=study(2), handle="ethan", name="setting", raw="lab")
    assert set(rec_mod.studies_missing(repo)) == {study(1), study(3)}


def test_not_reported_counts_as_an_answer_for_a_required_field(tmp_path: Path) -> None:
    repo = _review(tmp_path, studies=1)
    for name, raw in (("n_total", "NR"), ("design", "rct"), ("retention_interval", "NR")):
        rec_mod.set_field(repo, study=study(1), handle="ethan", name=name, raw=raw)
    assert rec_mod.studies_missing(repo) == {}


def test_in_dual_mode_each_reviewers_queue_is_their_own_record(tmp_path: Path) -> None:
    repo = _review(tmp_path, mode="dual", studies=2)
    for name, raw in (("n_total", "9"), ("design", "rct"), ("retention_interval", "9")):
        rec_mod.set_field(repo, study=study(1), handle="ethan", name=name, raw=raw)
    assert set(rec_mod.studies_missing(repo, "ethan")) == {study(2)}
    assert set(rec_mod.studies_missing(repo, "sam")) == {study(1), study(2)}
    assert set(rec_mod.studies_missing(repo)) == {study(1), study(2)}  # nothing reconciled yet


def _valid_record() -> dict[str, Any]:
    return {
        "study": study(1),
        "reports": [rpt(1)],
        "schema_version": 1,
        "extracted_by": ["ethan"],
        "fields": {"n_total": {"value": 10}},
    }


def _issues(record: dict[str, Any]) -> list[tuple[str, str]]:
    schema = schema_mod.parse_schema(FORM)
    return [
        (i.code, i.message) for i in rec_mod.validate_record(record, schema, REGISTRY, where="f")
    ]


def test_validate_record_accepts_a_good_record_and_flags_each_kind_of_problem() -> None:
    assert _issues(_valid_record()) == []

    wrong_unit = _valid_record()
    wrong_unit["fields"]["retention_interval"] = {
        "value": 2, "unit": "hours", "entered": "2 fortnights",
    }  # fmt: skip
    assert [c for c, _ in _issues(wrong_unit)] == ["E_UNIT"]

    foreign_unit = _valid_record()
    foreign_unit["fields"]["retention_interval"] = {"value": 2, "unit": "grams"}
    assert [c for c, _ in _issues(foreign_unit)] == ["E_UNIT"]

    no_unit = _valid_record()
    no_unit["fields"]["retention_interval"] = {"value": 2}
    assert [c for c, _ in _issues(no_unit)] == ["E_UNIT"]

    unknown = _valid_record()
    unknown["fields"]["shoe_size"] = {"value": 9}
    assert _issues(unknown)[0][0] == "E_SCHEMA"

    bad_types = _valid_record()
    bad_types["fields"].update(
        n_total={"value": "ten"},
        mean_age={"value": 4.5, "source": "t"},
        design={"value": "cohort"},
        countries={"value": ["fr"]},
        blinded={"value": "yes"},
        retention_interval={"value": "soon", "unit": "hours"},
    )
    assert {c for c, _ in _issues(bad_types)} == {"E_SCHEMA"}
    assert len(_issues(bad_types)) == 5  # the valid mean_age is not among them

    fractional = _valid_record()
    fractional["fields"]["n_total"] = {"value": 10.5}
    assert [c for c, _ in _issues(fractional)] == ["E_SCHEMA"]

    reported_not = _valid_record()
    reported_not["fields"]["design"] = {"value": None, "not_reported": True}
    assert _issues(reported_not) == []

    malformed = _valid_record()
    del malformed["study"]
    assert _issues(malformed)[0][0] == "E_SCHEMA"


def test_validate_record_flags_effects_missing_their_designs_inputs() -> None:
    """openspec scenario: a two-group-means effect lacking sd2 -> E_EFFECT_INPUTS."""
    record = _valid_record()
    record["effects"] = [
        {
            "outcome": "recall",
            "design": "two-group-means",
            **{k: v for k, v in MEANS.items() if k != "sd2"},
        },
        {"outcome": "recognition", "design": "telepathy"},
        {
            "outcome": "recall",
            "timepoint": "2 weeks",
            "design": "t-test",
            "t": 2.5,
            "n1": 30,
            "n2": 30,
        },
    ]
    issues = _issues(record)
    assert [c for c, _ in issues] == ["E_EFFECT_INPUTS", "E_EFFECT_INPUTS"]
    assert "sd2" in issues[0][1] and "not declared" in issues[1][1]
