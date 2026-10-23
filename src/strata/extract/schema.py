"""The extraction coding form, `extraction/schema.yaml`
(openspec:data-extraction#extraction-schema).

The form is declarative configuration a human edits
(openspec:repository-format#authoritative-versus-derived-files); `strata extract init` drafts it
from the protocol's declared moderators and outcomes. Changing the form bumps its `version`;
adding a required field makes existing extractions *incomplete* for that field, never invalid
(openspec:data-extraction#schema-changes-make-extractions-incomplete-not-stale).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from strata.core.canon import dump_yaml_str, load_yaml_str
from strata.core.repo import Repo
from strata.core.validate import SchemaValidationError, validate
from strata.extract import effects as effects_mod
from strata.extract import units as units_mod

SCHEMA_PATH = ("extraction", "schema.yaml")
UNITS_PATH = ("extraction", "units.yaml")
FIELD_TYPES = (
    "integer",
    "number",
    "quantity",
    "categorical",
    "multi-categorical",
    "boolean",
    "text",
    "date",
    "citation",
)
_FIELD_KEY_ORDER = (
    "name",
    "label",
    "type",
    "required",
    "min",
    "max",
    "levels",
    "unit",
    "accepts_units",
    "help",
)
_DEFAULT_DESIGNS = (
    "two-group-means",
    "two-group-binary",
    "correlation",
    "precomputed",
    "pre-post",
    "t-test",
    "f-test",
    "chi-square",
    "p-value-only",
    "hazard-ratio",
)


class ExtractionSchemaError(ValueError):
    pass


def plain(value: Any) -> Any:
    """A ruamel round-trip structure as plain dicts/lists/scalars (dates become strings)."""
    return json.loads(json.dumps(value, default=str))


@dataclass(frozen=True)
class ExtractionSchema:
    doc: dict[str, Any]

    @property
    def version(self) -> int:
        return int(self.doc["version"])

    @property
    def fields(self) -> list[dict[str, Any]]:
        return list(self.doc["fields"])

    def field(self, name: str) -> dict[str, Any] | None:
        return next((f for f in self.doc["fields"] if f["name"] == name), None)

    @property
    def required_names(self) -> list[str]:
        return [f["name"] for f in self.doc["fields"] if f.get("required", False)]

    @property
    def outcome_field(self) -> str:
        return str(self.doc.get("effects", {}).get("outcome_field", "outcome"))

    @property
    def outcomes(self) -> list[str]:
        return list(self.doc.get("effects", {}).get("outcomes", []))

    @property
    def designs(self) -> dict[str, tuple[str, ...]]:
        """Declared designs -> required inputs. With none declared, every built-in design."""
        declared = self.doc.get("effects", {}).get("designs")
        if declared:
            return {d["id"]: tuple(d["requires"]) for d in declared}
        return {i: effects_mod.DESIGNS[i].requires for i in _DEFAULT_DESIGNS}


def schema_path(repo: Repo) -> Any:
    return repo.path(*SCHEMA_PATH)


def schema_exists(repo: Repo) -> bool:
    return bool(schema_path(repo).exists())


def unit_registry(repo: Repo) -> units_mod.UnitRegistry:
    """Built-in unit tables plus the project's `extraction/units.yaml` extensions, if any."""
    path = repo.path(*UNITS_PATH)
    if not path.exists():
        return units_mod.UnitRegistry()
    data = plain(load_yaml_str(path.read_text(encoding="utf-8"))) or {}
    try:
        return units_mod.UnitRegistry(data.get("units") or {})
    except (units_mod.UnitError, AttributeError, TypeError) as exc:
        raise ExtractionSchemaError(f"extraction/units.yaml: {exc}") from None


def parse_schema(doc: Any, registry: units_mod.UnitRegistry | None = None) -> ExtractionSchema:
    """Validate a coding form against its JSON Schema and the rules a schema cannot express."""
    plain_doc = plain(doc)
    try:
        validate("extraction-schema", plain_doc)
    except SchemaValidationError as exc:
        raise ExtractionSchemaError("; ".join(exc.errors)) from None
    registry = registry or units_mod.UnitRegistry()

    names = [f["name"] for f in plain_doc["fields"]]
    duplicates = sorted({n for n in names if names.count(n) > 1})
    if duplicates:
        raise ExtractionSchemaError(f"duplicate field name(s): {', '.join(duplicates)}")
    for f in plain_doc["fields"]:
        if "min" in f and "max" in f and f["min"] > f["max"]:
            raise ExtractionSchemaError(f"field {f['name']!r}: min is greater than max")
        if f["type"] == "quantity":
            try:
                dimension = registry.dimension_of(f["unit"])
                for accepted in f.get("accepts_units", []):
                    if registry.dimension_of(accepted) != dimension:
                        raise units_mod.UnitError(
                            f"{accepted!r} is not a unit of {dimension} like {f['unit']!r}"
                        )
            except units_mod.UnitError as exc:
                raise ExtractionSchemaError(f"field {f['name']!r}: {exc}") from None
    designs = plain_doc.get("effects", {}).get("designs", [])
    design_ids = [d["id"] for d in designs]
    if len(design_ids) != len(set(design_ids)):
        raise ExtractionSchemaError("duplicate effect design id")
    return ExtractionSchema(plain_doc)


def load_schema(repo: Repo) -> ExtractionSchema:
    path = schema_path(repo)
    if not path.exists():
        raise ExtractionSchemaError(
            "this review has no extraction/schema.yaml yet; run `strata extract init`"
        )
    return parse_schema(load_yaml_str(path.read_text(encoding="utf-8")), unit_registry(repo))


# --- drafting a form from the protocol -------------------------------------------------------


def _snake(text: str) -> str:
    name = re.sub(r"[^a-z0-9]+", "_", str(text).lower()).strip("_")
    return name if name and name[0].isalpha() else f"f_{name}"


def _ordered(field_def: dict[str, Any]) -> dict[str, Any]:
    return {k: field_def[k] for k in _FIELD_KEY_ORDER if k in field_def}


def _moderator_field(moderator: dict[str, Any], registry: units_mod.UnitRegistry) -> dict[str, Any]:
    kind = moderator.get("type", "continuous")
    out: dict[str, Any] = {
        "name": _snake(moderator["name"]),
        "label": moderator.get("label") or str(moderator["name"]),
        "required": bool(moderator.get("planned", True)),
    }
    value_range = moderator.get("range")
    if kind == "continuous":
        unit = moderator.get("unit")
        try:
            dimension = registry.dimension_of(unit) if unit else None
        except units_mod.UnitError:
            dimension = None
        if unit and dimension:
            out["type"] = "quantity"
            out["unit"] = registry.normalise_unit_name(unit)
            out["accepts_units"] = registry.units_in(dimension)
        else:
            out["type"] = "number"
            if unit:
                out["help"] = f"In {unit}."
    elif kind in ("categorical", "ordinal") and moderator.get("levels"):
        out["type"] = "categorical"
        out["levels"] = [str(level) for level in moderator["levels"]]
    elif kind == "boolean":
        out["type"] = "boolean"
    elif kind == "count":
        out["type"] = "integer"
        out["min"] = 0
    else:
        out["type"] = "text"
    if value_range and out["type"] in ("number", "quantity", "integer"):
        out["min"], out["max"] = value_range[0], value_range[1]
    return _ordered(out)


def draft_schema(
    moderators: list[dict[str, Any]],
    outcomes: list[Any],
    registry: units_mod.UnitRegistry | None = None,
) -> dict[str, Any]:
    """A first coding form: the sample size, one field per declared moderator, the outcomes
    from the protocol, and every built-in effect design. A starting point to edit by hand."""
    registry = registry or units_mod.UnitRegistry()
    fields = [
        _ordered(
            {
                "name": "n_total",
                "label": "Total analysed N",
                "type": "integer",
                "required": True,
                "min": 1,
                "help": "Number of participants in the analysed sample, not the enrolled sample.",
            }
        )
    ]
    for moderator in moderators:
        drafted = _moderator_field(moderator, registry)
        if all(drafted["name"] != f["name"] for f in fields):
            fields.append(drafted)
    names = [
        str(o.get("name") or o.get("id") or o.get("label")) if isinstance(o, dict) else str(o)
        for o in outcomes
    ]
    return {
        "version": 1,
        "fields": fields,
        "effects": {
            "outcome_field": "outcome",
            "outcomes": [n for n in names if n and n != "None"],
            "designs": [
                {"id": i, "requires": list(effects_mod.DESIGNS[i].requires)}
                for i in _DEFAULT_DESIGNS
            ],
        },
    }


def init_schema(repo: Repo, *, overwrite: bool = False) -> ExtractionSchema:
    """Write a draft `extraction/schema.yaml` from the protocol's moderators and outcomes."""
    path = schema_path(repo)
    if path.exists() and not overwrite:
        raise ExtractionSchemaError(
            "extraction/schema.yaml already exists; edit it directly (and raise its version)"
        )

    def listed(filename: str, key: str) -> list[Any]:
        source = repo.path("protocol", filename)
        if not source.exists():
            return []
        data = plain(load_yaml_str(source.read_text(encoding="utf-8"))) or {}
        return list(data.get(key) or [])

    doc = draft_schema(
        listed("moderators.yaml", "moderators"),
        listed("outcomes.yaml", "outcomes"),
        unit_registry(repo),
    )
    schema = parse_schema(doc, unit_registry(repo))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump_yaml_str(doc), encoding="utf-8")
    return schema
