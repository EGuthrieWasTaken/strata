"""The extraction coding form (openspec:data-extraction#extraction-schema)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from strata.core.canon import dump_yaml_str, load_yaml_str
from strata.extract import schema as schema_mod
from strata.extract import units as units_mod
from tests.unit._m3 import init_review


def _minimal(**overrides: Any) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "version": 1,
        "fields": [{"name": "n_total", "type": "integer", "required": True}],
    }
    doc.update(overrides)
    return doc


def test_draft_form_has_a_field_for_each_declared_moderator(tmp_path: Path) -> None:
    """openspec scenario: moderators mean_age and design -> fields for both."""
    repo = init_review(tmp_path)
    repo.path("protocol", "moderators.yaml").write_text(
        dump_yaml_str(
            {
                "moderators": [
                    {
                        "name": "mean_age",
                        "label": "Mean age",
                        "type": "continuous",
                        "unit": "years",
                    },
                    {
                        "name": "design",
                        "label": "Study design",
                        "type": "categorical",
                        "levels": ["rct", "quasi-experimental"],
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    schema = schema_mod.init_schema(repo)
    assert [f["name"] for f in schema.fields] == ["n_total", "mean_age", "design"]
    assert schema.field("design")["levels"] == ["rct", "quasi-experimental"]  # type: ignore[index]
    assert schema_mod.schema_exists(repo)
    assert schema_mod.load_schema(repo).doc == schema.doc


def test_draft_maps_every_moderator_type() -> None:
    drafted = schema_mod.draft_schema(
        [
            {"name": "Dose (mg)", "type": "continuous", "unit": "milligrams", "range": [0, 500]},
            {"name": "interval", "type": "continuous", "unit": "hours"},
            {"name": "iq", "type": "continuous", "unit": "points", "range": [40, 160]},
            {"name": "rank", "type": "ordinal", "levels": ["low", "high"]},
            {"name": "blinded", "type": "boolean", "planned": False},
            {"name": "sessions", "type": "count"},
            {"name": "free", "type": "categorical"},
            {"name": "n_total", "type": "count"},  # duplicates the built-in field: ignored
        ],
        ["recall", {"name": "recognition"}, {"id": "transfer"}],
    )
    by_name = {f["name"]: f for f in drafted["fields"]}
    assert by_name["dose_mg"]["type"] == "quantity" and by_name["dose_mg"]["unit"] == "milligrams"
    assert (by_name["dose_mg"]["min"], by_name["dose_mg"]["max"]) == (0, 500)
    assert "hours" in by_name["interval"]["accepts_units"]
    assert by_name["iq"]["type"] == "number" and by_name["iq"]["help"] == "In points."
    assert by_name["rank"]["type"] == "categorical" and by_name["blinded"]["required"] is False
    assert by_name["sessions"] == {
        "name": "sessions",
        "label": "sessions",
        "type": "integer",
        "required": True,
        "min": 0,
    }
    assert by_name["free"]["type"] == "text"  # a categorical with no levels cannot be a choice
    assert drafted["effects"]["outcomes"] == ["recall", "recognition", "transfer"]
    assert {d["id"] for d in drafted["effects"]["designs"]} >= {"two-group-means", "p-value-only"}
    schema_mod.parse_schema(drafted)  # a draft is always a valid form


def test_init_refuses_to_overwrite_an_existing_form(tmp_path: Path) -> None:
    repo = init_review(tmp_path)
    schema_mod.init_schema(repo)
    with pytest.raises(schema_mod.ExtractionSchemaError, match="already exists"):
        schema_mod.init_schema(repo)
    assert schema_mod.init_schema(repo, overwrite=True).version == 1


def test_loading_a_missing_form_points_at_init(tmp_path: Path) -> None:
    repo = init_review(tmp_path)
    assert not schema_mod.schema_exists(repo)
    with pytest.raises(schema_mod.ExtractionSchemaError, match="extract init"):
        schema_mod.load_schema(repo)


def test_a_form_with_no_declared_designs_offers_every_built_in_design() -> None:
    schema = schema_mod.parse_schema(_minimal())
    assert "two-group-means" in schema.designs and "hazard-ratio" in schema.designs
    assert schema.designs["two-group-binary"] == ("events1", "n1", "events2", "n2")
    assert schema.outcome_field == "outcome" and schema.outcomes == []
    assert schema.required_names == ["n_total"] and schema.version == 1


def test_declared_designs_replace_the_defaults() -> None:
    doc = _minimal(effects={"designs": [{"id": "correlation", "requires": ["r", "n"]}]})
    assert schema_mod.parse_schema(doc).designs == {"correlation": ("r", "n")}


@pytest.mark.parametrize(
    ("doc", "message"),
    [
        (
            _minimal(fields=[{"name": "a", "type": "text"}, {"name": "a", "type": "text"}]),
            "duplicate",
        ),
        (_minimal(fields=[{"name": "a", "type": "integer", "min": 5, "max": 1}]), "min is greater"),
        (_minimal(fields=[{"name": "A b", "type": "text"}]), "does not match"),
        (_minimal(fields=[{"name": "a", "type": "categorical"}]), "levels"),
        (_minimal(fields=[{"name": "a", "type": "quantity"}]), "unit"),
        (_minimal(fields=[{"name": "a", "type": "quantity", "unit": "parsecs"}]), "parsecs"),
        (
            _minimal(
                fields=[
                    {"name": "a", "type": "quantity", "unit": "hours", "accepts_units": ["grams"]}
                ]
            ),
            "not a unit of time",
        ),
        (_minimal(effects={"designs": [{"id": "x", "requires": ["a"]}] * 2}), "duplicate effect"),
        ({"fields": []}, "version"),
        (_minimal(surprise=1), "surprise"),
    ],
)
def test_invalid_forms_are_rejected_with_a_specific_message(
    doc: dict[str, Any], message: str
) -> None:
    with pytest.raises(schema_mod.ExtractionSchemaError, match=message):
        schema_mod.parse_schema(doc)


def test_project_unit_extensions_are_part_of_the_form_vocabulary(tmp_path: Path) -> None:
    repo = init_review(tmp_path)
    repo.path("extraction").mkdir(exist_ok=True)
    repo.path("extraction", "units.yaml").write_text(
        dump_yaml_str({"units": {"time": {"fortnights": 1209600}}}), encoding="utf-8"
    )
    registry = schema_mod.unit_registry(repo)
    assert registry.convert(1, "fortnights", "days") == pytest.approx(14)
    doc = _minimal(
        fields=[{"name": "t", "type": "quantity", "unit": "days", "accepts_units": ["fortnights"]}]
    )
    schema_mod.parse_schema(doc, registry)
    with pytest.raises(schema_mod.ExtractionSchemaError, match="fortnights"):
        schema_mod.parse_schema(doc)  # without the extension the unit is unknown


def test_a_broken_units_file_is_a_clear_error(tmp_path: Path) -> None:
    repo = init_review(tmp_path)
    repo.path("extraction").mkdir(exist_ok=True)
    repo.path("extraction", "units.yaml").write_text(
        "units: {luminosity: {candela: 1}}\n", encoding="utf-8"
    )
    with pytest.raises(schema_mod.ExtractionSchemaError, match="units.yaml"):
        schema_mod.unit_registry(repo)
    assert isinstance(load_yaml_str("a: 1"), dict)
    assert isinstance(units_mod.UnitRegistry(), units_mod.UnitRegistry)
