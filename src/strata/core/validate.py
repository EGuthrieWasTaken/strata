"""JSON Schema loading and validation for the schemas shipped under `strata/schemas/`.

Implements openspec:data-schemas#project-manifest: every persisted object type MUST be
validated on write and on load against its shipped JSON Schema.
"""

from __future__ import annotations

import functools
import importlib.resources
import json
from typing import Any

import jsonschema


class SchemaValidationError(ValueError):
    def __init__(self, schema_name: str, errors: list[str]) -> None:
        self.schema_name = schema_name
        self.errors = errors
        super().__init__(f"{schema_name}: " + "; ".join(errors))


@functools.cache
def _load_schema(name: str) -> dict[str, Any]:
    ref = importlib.resources.files("strata.schemas").joinpath(f"{name}.schema.json")
    schema: dict[str, Any] = json.loads(ref.read_text(encoding="utf-8"))
    return schema


@functools.cache
def _validator_for(name: str) -> jsonschema.protocols.Validator:
    schema = _load_schema(name)
    validator_cls = jsonschema.validators.validator_for(schema)
    validator_cls.check_schema(schema)
    return validator_cls(schema)


def validate(name: str, instance: Any) -> None:
    """Validate `instance` against the schema `name` (e.g. `"event"`, `"manifest"`).

    Raises `SchemaValidationError` naming every violation, not just the first.
    """
    validator = _validator_for(name)
    errors = [
        f"{'/'.join(str(p) for p in error.absolute_path) or '<root>'}: {error.message}"
        for error in validator.iter_errors(instance)
    ]
    if errors:
        raise SchemaValidationError(name, errors)


def validate_event_body(ev: str, body: dict[str, Any]) -> None:
    """Validate an event body against its per-type schema *before* anything is written.

    The event schema constrains a body by its `ev` type, so this wraps the body in a placeholder
    envelope and validates that. A body that would later fail `strata verify` is therefore
    refused at the moment it would have been appended.
    """
    validate(
        "event",
        {
            "ev": ev,
            "id": "ev_" + "0" * 26,
            "ts": "2026-01-01T00:00:00Z",
            "actor": "placeholder",
            "seq": 1,
            "body": body,
            "tool": "strata/validation",
            "digest": "sha256:" + "0" * 64,
        },
    )
