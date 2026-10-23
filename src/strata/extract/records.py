"""Extraction records: per-reviewer and consensus files, and the events that log them.

Implements openspec:data-extraction. Records are human-readable YAML a person may open and edit
(openspec:repository-format#authoritative-versus-derived-files); every save through `strata` also
appends an `extract` event carrying the file's digest, so the log shows who changed what and when.

Where a value lands depends on `extraction.mode`: with `single` it goes straight into
`extraction/consensus/<study>.yaml`; with `dual` each reviewer writes
`extraction/by-reviewer/<handle>/<study>.yaml` independently and the two are reconciled into the
consensus (see `strata.extract.reconcile`).
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from strata.core.canon import dump_yaml_str, load_yaml_str
from strata.core.events import append_new_event, read_events
from strata.core.ids import effect_id
from strata.core.repo import Repo
from strata.core.validate import SchemaValidationError, validate, validate_event_body
from strata.extract import effects as effects_mod
from strata.extract import quality
from strata.extract import schema as schema_mod
from strata.extract import units as units_mod
from strata.protocol import studies as studies_mod
from strata.stats import effect_sizes as es

_ACK_SUBJECT = "quality-ack"
_RECORD_KEY_ORDER = (
    "study",
    "reports",
    "schema_version",
    "extracted_by",
    "reconciled_by",
    "fields",
    "effects",
)
_ENTRY_KEY_ORDER = ("value", "unit", "entered", "not_reported", "source")
_EFFECT_HEAD = ("id", "outcome", "design", "timepoint", "label")
_EFFECT_TAIL = ("source", "moderators")
_NOT_REPORTED = {"nr", "not reported", "not-reported"}
_SOURCE_SPLIT = re.compile(r"\s@\s*(.+)$")


class ExtractionError(ValueError):
    pass


@dataclass(frozen=True)
class Issue:
    """One problem found in an extraction file. `warning` issues do not fail verification."""

    code: str
    where: str
    message: str
    warning: bool = False


# --- locations -------------------------------------------------------------------------------


def extraction_mode(repo: Repo) -> str:
    return str(repo.config.get("extraction", {}).get("mode", "single"))


def consensus_path(repo: Repo, study: str) -> Path:
    return repo.path("extraction", "consensus", f"{study}.yaml")


def reviewer_path(repo: Repo, handle: str, study: str) -> Path:
    return repo.path("extraction", "by-reviewer", handle, f"{study}.yaml")


def working_path(repo: Repo, handle: str, study: str) -> Path:
    """The file `handle` writes to under the current mode."""
    if extraction_mode(repo) == "dual":
        return reviewer_path(repo, handle, study)
    return consensus_path(repo, study)


def read_record(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    data = schema_mod.plain(load_yaml_str(path.read_text(encoding="utf-8")))
    return data if isinstance(data, dict) else None


def _ordered_effect(effect: dict[str, Any]) -> dict[str, Any]:
    head = {k: effect[k] for k in _EFFECT_HEAD if k in effect}
    middle = {k: effect[k] for k in sorted(effect) if k not in _EFFECT_HEAD + _EFFECT_TAIL}
    tail = {k: effect[k] for k in _EFFECT_TAIL if k in effect}
    return {**head, **middle, **tail}


def serialise(record: dict[str, Any], schema: schema_mod.ExtractionSchema | None) -> str:
    """Canonical YAML: fixed key order, fields in the coding form's order."""
    names = [f["name"] for f in schema.fields] if schema else []
    fields = record.get("fields", {})
    ordered_names = [n for n in names if n in fields] + sorted(n for n in fields if n not in names)
    ordered: dict[str, Any] = {}
    for key in _RECORD_KEY_ORDER:
        if key == "fields":
            ordered["fields"] = {
                n: {k: fields[n][k] for k in _ENTRY_KEY_ORDER if k in fields[n]}
                for n in ordered_names
            }
        elif key == "effects":
            if record.get("effects"):
                ordered["effects"] = [_ordered_effect(e) for e in record["effects"]]
        elif key in record:
            ordered[key] = record[key]
    return dump_yaml_str(ordered)


def write_record(
    path: Path, record: dict[str, Any], schema: schema_mod.ExtractionSchema | None
) -> str:
    """Write a record; returns the digest of the bytes written."""
    text = serialise(record, schema)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def new_record(
    study: str, reports: tuple[str, ...], schema_version: int, handle: str
) -> dict[str, Any]:
    return {
        "study": study,
        "reports": list(reports),
        "schema_version": schema_version,
        "extracted_by": [handle],
        "fields": {},
    }


# --- coercing typed values -------------------------------------------------------------------


def split_source(text: str) -> tuple[str, str | None]:
    """`148 @ p. 1097` -> (`148`, `p. 1097`): a value and its source locator in one entry."""
    match = _SOURCE_SPLIT.search(text)
    if not match:
        return text.strip(), None
    return text[: match.start()].strip(), match.group(1).strip()


def _number(text: str, *, integer: bool) -> int | float:
    cleaned = text.strip().replace(",", "")
    try:
        number = float(cleaned)
    except ValueError:
        raise ExtractionError(f"{text!r} is not a number") from None
    if integer:
        if number != int(number):
            raise ExtractionError(f"{text!r} is not a whole number")
        return int(number)
    return int(number) if number == int(number) and "." not in cleaned else number


def _within(spec: dict[str, Any], value: float) -> None:
    if "min" in spec and value < spec["min"]:
        raise ExtractionError(f"{spec['name']}: {value:g} is below the minimum {spec['min']:g}")
    if "max" in spec and value > spec["max"]:
        raise ExtractionError(f"{spec['name']}: {value:g} is above the maximum {spec['max']:g}")


def coerce_value(
    spec: dict[str, Any], raw: str, registry: units_mod.UnitRegistry
) -> dict[str, Any]:
    """Turn what a person typed into the stored entry for field `spec`.

    `NR` (not reported) is a recorded answer, not a gap: the value is null and the entry says so.
    """
    text = raw.strip()
    if not text:
        raise ExtractionError(f"{spec['name']}: a value is required")
    if text.lower() in _NOT_REPORTED:
        return {"value": None, "not_reported": True}
    kind = spec["type"]
    if kind in ("integer", "number"):
        value = _number(text, integer=kind == "integer")
        _within(spec, value)
        return {"value": value}
    if kind == "quantity":
        accepts = spec.get("accepts_units")
        try:
            bare = float(text.replace(",", ""))
        except ValueError:
            try:
                record = registry.to_quantity_record(
                    text, target_unit=spec["unit"], accepts_units=accepts
                )
            except units_mod.UnitError as exc:
                raise ExtractionError(f"{spec['name']}: {exc} (E_UNIT)") from None
            _within(spec, float(record["value"]))
            return record
        # A bare number is taken to be in the field's own unit.
        unit = registry.normalise_unit_name(spec["unit"])
        _within(spec, bare)
        return {"value": int(bare) if bare == int(bare) else bare, "unit": unit, "entered": text}
    if kind == "categorical":
        by_lower = {level.lower(): level for level in spec["levels"]}
        if text.lower() not in by_lower:
            raise ExtractionError(
                f"{spec['name']}: {text!r} is not one of {', '.join(spec['levels'])}"
            )
        return {"value": by_lower[text.lower()]}
    if kind == "multi-categorical":
        by_lower = {level.lower(): level for level in spec["levels"]}
        picked = [p.strip() for p in text.split(",") if p.strip()]
        unknown = [p for p in picked if p.lower() not in by_lower]
        if unknown or not picked:
            raise ExtractionError(
                f"{spec['name']}: {', '.join(unknown) or text!r} not in {', '.join(spec['levels'])}"
            )
        return {"value": sorted({by_lower[p.lower()] for p in picked})}
    if kind == "boolean":
        lowered = text.lower()
        if lowered in ("y", "yes", "true", "1"):
            return {"value": True}
        if lowered in ("n", "no", "false", "0"):
            return {"value": False}
        raise ExtractionError(f"{spec['name']}: {text!r} is not yes or no")
    if kind == "date":
        if not re.fullmatch(r"\d{4}(-\d{2}(-\d{2})?)?", text):
            raise ExtractionError(f"{spec['name']}: {text!r} is not YYYY, YYYY-MM or YYYY-MM-DD")
        if len(text) == 10:
            date.fromisoformat(text)
        return {"value": text}
    return {"value": text}  # text, citation


# --- saving ----------------------------------------------------------------------------------


def _current_study(repo: Repo, study: str) -> tuple[str, ...]:
    members = studies_mod.study_map(repo).members
    if study not in members:
        raise ExtractionError(f"no included study {study!r}")
    return members[study]


def _record_for_update(
    repo: Repo, handle: str, study: str, schema: schema_mod.ExtractionSchema
) -> tuple[Path, dict[str, Any]]:
    reports = _current_study(repo, study)
    path = working_path(repo, handle, study)
    record = read_record(path) or new_record(study, reports, schema.version, handle)
    record["reports"] = list(reports)
    record["schema_version"] = schema.version
    if handle not in record["extracted_by"]:
        record["extracted_by"] = sorted({*record["extracted_by"], handle})
    return path, record


def _log_extraction(
    repo: Repo,
    *,
    handle: str,
    study: str,
    changed: list[str],
    digest: str,
    schema: schema_mod.ExtractionSchema,
) -> dict[str, Any]:
    body = {
        "study": study,
        "fields_changed": changed,
        "digest": digest,
        "schema_version": schema.version,
    }
    validate_event_body("extract", body)
    return append_new_event(
        repo.path("events", "extract", f"{handle}.ndjson"), ev="extract", actor=handle, body=body
    )


def set_field(
    repo: Repo, *, study: str, handle: str, name: str, raw: str, source: str | None = None
) -> dict[str, Any]:
    """Record one field's value (and its source locator) for `study` as `handle`."""
    schema = schema_mod.load_schema(repo)
    spec = schema.field(name)
    if spec is None:
        raise ExtractionError(f"the coding form has no field {name!r}")
    value_text, inline_source = split_source(raw)
    entry = coerce_value(spec, value_text, schema_mod.unit_registry(repo))
    if source or inline_source:
        entry["source"] = source or inline_source
    path, record = _record_for_update(repo, handle, study, schema)
    record["fields"][name] = entry
    digest = write_record(path, record, schema)
    _log_extraction(repo, handle=handle, study=study, changed=[name], digest=digest, schema=schema)
    return entry


def effect_key(effect: dict[str, Any]) -> str:
    """What identifies an effect within a study across reviewers: outcome, timepoint, label."""
    return "|".join(str(effect.get(k) or "") for k in ("outcome", "timepoint", "label"))


def _numeric(inputs: dict[str, Any]) -> dict[str, Any]:
    """Inputs typed on a command line arrive as strings; numbers become numbers."""
    converted: dict[str, Any] = {}
    for name, value in inputs.items():
        if isinstance(value, str):
            try:
                converted[name] = (
                    float(value) if "." in value or "e" in value.lower() else int(value)
                )
                continue
            except ValueError:
                pass
        converted[name] = value
    return converted


@dataclass
class EffectResult:
    effect: dict[str, Any]
    computed: es.EffectSize | None
    warnings: list[quality.QualityWarning] = field(default_factory=list)


def preview_effect(
    repo: Repo,
    *,
    study: str | None,
    design: str,
    inputs: dict[str, Any],
    outcome: str | None = None,
    skip_key: str | None = None,
) -> EffectResult:
    """Compute an effect from whatever has been entered so far, without saving anything.

    This is what shows the effect size as it is typed: missing inputs give `computed=None` (not
    an error), and the data-quality guards that already apply are returned alongside.
    """
    typed = _numeric(inputs)
    try:
        computed: es.EffectSize | None = effects_mod.compute(design, typed)
    except effects_mod.EffectInputError:
        computed = None
    except es.EffectSizeError:
        computed = None
    n_total = _study_n_total(repo, study) if study else None
    peers = _peer_sds(repo, outcome, exclude_study=study, exclude_key=skip_key) if outcome else []
    try:
        warnings = effects_mod.guard_warnings(
            design, typed, computed, n_total=n_total, peer_sds=peers
        )
    except (effects_mod.EffectInputError, ValueError):
        warnings = []
    return EffectResult(effect={"design": design, **typed}, computed=computed, warnings=warnings)


def add_effect(
    repo: Repo,
    *,
    study: str,
    handle: str,
    outcome: str,
    design: str,
    inputs: dict[str, Any],
    timepoint: str | None = None,
    label: str | None = None,
    source: str | None = None,
    moderators: dict[str, Any] | None = None,
) -> EffectResult:
    """Add (or replace, by outcome/timepoint/label) one effect for a study."""
    schema = schema_mod.load_schema(repo)
    declared = schema.designs
    if design not in declared:
        raise ExtractionError(f"design {design!r} is not declared; declared: {', '.join(declared)}")
    if schema.outcomes and outcome not in schema.outcomes:
        raise ExtractionError(f"outcome {outcome!r} is not one of {', '.join(schema.outcomes)}")
    typed = _numeric(inputs)
    missing = effects_mod.missing_inputs(declared[design], typed)
    if missing:
        raise effects_mod.EffectInputError(
            f"a {design} effect still needs: {', '.join(missing)} (E_EFFECT_INPUTS)"
        )
    effect: dict[str, Any] = {"outcome": outcome, "design": design, **typed}
    if timepoint:
        effect["timepoint"] = timepoint
    if label:
        effect["label"] = label
    if source:
        effect["source"] = source
    if moderators:
        effect["moderators"] = moderators
    key = effect_key(effect)

    path, record = _record_for_update(repo, handle, study, schema)
    effects = record.setdefault("effects", [])
    existing = next((e for e in effects if effect_key(e) == key), None)
    result = preview_effect(
        repo, study=study, design=design, inputs=typed, outcome=outcome, skip_key=key
    )
    if design in effects_mod.DESIGNS and result.computed is None:
        # Present but impossible inputs (e.g. both SDs zero) surface their specific message.
        effects_mod.compute(design, typed)
    if existing is not None:
        if "id" in existing:
            effect["id"] = existing["id"]
        effects[effects.index(existing)] = effect
    else:
        if extraction_mode(repo) == "single":
            effect["id"] = effect_id(study, _next_effect_sequence(effects))
        effects.append(effect)
    result.effect = effect
    digest = write_record(path, record, schema)
    _log_extraction(
        repo, handle=handle, study=study, changed=[f"effects:{key}"], digest=digest, schema=schema
    )
    return result


def _next_effect_sequence(effects: list[dict[str, Any]]) -> int:
    used = [int(e["id"][-4:]) for e in effects if "id" in e]
    return max(used, default=0) + 1


# --- reading everything ----------------------------------------------------------------------


def record_paths(repo: Repo) -> list[tuple[str, str | None, Path]]:
    """Every extraction file as `(kind, handle, path)`; kind is `consensus` or `reviewer`."""
    found: list[tuple[str, str | None, Path]] = []
    consensus_dir = repo.path("extraction", "consensus")
    if consensus_dir.exists():
        found.extend(("consensus", None, p) for p in sorted(consensus_dir.glob("*.yaml")))
    reviewer_dir = repo.path("extraction", "by-reviewer")
    if reviewer_dir.exists():
        found.extend(("reviewer", p.parent.name, p) for p in sorted(reviewer_dir.glob("*/*.yaml")))
    return found


def all_records(repo: Repo) -> list[tuple[str, str | None, dict[str, Any], Path]]:
    """Every readable extraction file as `(kind, handle, record, path)`."""
    found: list[tuple[str, str | None, dict[str, Any], Path]] = []
    for kind, handle, path in record_paths(repo):
        record = read_record(path)
        if record is not None:
            found.append((kind, handle, record, path))
    return found


def _study_n_total(repo: Repo, study: str) -> float | None:
    for _kind, _handle, record, _path in all_records(repo):
        if record.get("study") == study:
            entry = record.get("fields", {}).get("n_total")
            if entry and isinstance(entry.get("value"), (int, float)):
                return float(entry["value"])
    return None


def _peer_sds(
    repo: Repo, outcome: str, *, exclude_study: str | None, exclude_key: str | None
) -> list[float]:
    sds: list[float] = []
    for kind, _handle, record, _path in all_records(repo):
        if kind != "consensus":
            continue
        for effect in record.get("effects", []):
            if effect.get("outcome") != outcome or effect.get("design") != "two-group-means":
                continue
            if record.get("study") == exclude_study and effect_key(effect) == exclude_key:
                continue
            for arm in ("1", "2"):
                try:
                    sds.append(effects_mod._arm_sd(effect, arm))
                except (effects_mod.EffectInputError, es.EffectSizeError):
                    continue
    return sds


# --- completeness ----------------------------------------------------------------------------


def missing_fields(schema: schema_mod.ExtractionSchema, record: dict[str, Any] | None) -> list[str]:
    """Required fields with no entry. `NR` counts as an answer; an absent entry does not."""
    fields = (record or {}).get("fields", {})
    return [n for n in schema.required_names if n not in fields]


def studies_missing(repo: Repo, handle: str | None = None) -> dict[str, list[str]]:
    """Included studies still missing required values: `{study: [field, ...]}`.

    With `single` mode (or no `handle`) this is the consensus record's completeness; with `dual`
    mode and a `handle` it is that reviewer's own record, which is what their queue is.
    """
    schema = schema_mod.load_schema(repo)
    dual_queue = extraction_mode(repo) == "dual" and handle is not None
    incomplete: dict[str, list[str]] = {}
    for study in sorted(studies_mod.study_map(repo).members):
        path = (
            reviewer_path(repo, handle, study)
            if dual_queue and handle
            else consensus_path(repo, study)
        )
        missing = missing_fields(schema, read_record(path))
        if missing:
            incomplete[study] = missing
    return incomplete


# --- data-quality acknowledgements -----------------------------------------------------------


def acknowledge_warning(
    repo: Repo, *, study: str, effect: str, code: str, note: str, actor: str
) -> dict[str, Any]:
    """Record that a data-quality warning was seen and accepted, with a note, so it does not
    recur and the decision is auditable (openspec:data-extraction#data-quality-guards)."""
    if code not in quality.CODES:
        raise ExtractionError(f"unknown warning code {code!r}; one of {', '.join(quality.CODES)}")
    if not note.strip():
        raise ExtractionError("acknowledging a warning needs a note saying why it is acceptable")
    body = {
        "subject": _ACK_SUBJECT,
        "study": study,
        "effect": effect,
        "code": code,
        "text": note.strip(),
    }
    return append_new_event(
        repo.path("events", "note", f"{actor}.ndjson"), ev="note", actor=actor, body=body
    )


def acknowledged(repo: Repo) -> set[tuple[str, str, str]]:
    directory = repo.path("events", "note")
    found: set[tuple[str, str, str]] = set()
    if directory.exists():
        for path in sorted(directory.glob("*.ndjson")):
            for event in read_events(path):
                body = event.get("body", {})
                if event.get("ev") == "note" and body.get("subject") == _ACK_SUBJECT:
                    found.add((body["study"], body["effect"], body["code"]))
    return found


def open_warnings(repo: Repo, study: str, record: dict[str, Any]) -> list[tuple[str, str, str]]:
    """Unacknowledged data-quality warnings on a study's effects: `(effect key, code, message)`."""
    accepted = acknowledged(repo)
    found = []
    for effect in record.get("effects", []):
        key = effect_key(effect)
        result = preview_effect(
            repo,
            study=study,
            design=effect["design"],
            inputs={k: v for k, v in effect.items() if k not in ("design", "outcome")},
            outcome=effect.get("outcome"),
            skip_key=key,
        )
        for warning in result.warnings:
            if (study, key, warning.code) not in accepted:
                found.append((key, warning.code, warning.message))
    return found


# --- validation (strata verify) --------------------------------------------------------------


def _check_stored(
    spec: dict[str, Any], entry: dict[str, Any], registry: units_mod.UnitRegistry
) -> Iterator[tuple[str, str]]:
    if entry.get("not_reported"):
        return
    kind = spec["type"]
    value = entry.get("value")
    if kind == "quantity":
        unit = entry.get("unit")
        accepts = spec.get("accepts_units")
        try:
            if unit is None:
                raise units_mod.UnitError("a quantity needs its unit")
            normal = registry.normalise_unit_name(unit)
            if normal != registry.normalise_unit_name(spec["unit"]):
                raise units_mod.UnitError(
                    f"stored unit {unit!r} is not the field's unit {spec['unit']!r}"
                )
            if entered := entry.get("entered"):
                registry.to_quantity_record(
                    str(entered), target_unit=spec["unit"], accepts_units=accepts
                )
        except units_mod.UnitError as exc:
            yield "E_UNIT", str(exc)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            yield "E_SCHEMA", f"{spec['name']}: a quantity's value must be a number"
    elif kind in ("integer", "number"):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            yield "E_SCHEMA", f"{spec['name']}: {value!r} is not a number"
        elif kind == "integer" and value != int(value):
            yield "E_SCHEMA", f"{spec['name']}: {value!r} is not a whole number"
    elif kind == "categorical" and value not in spec["levels"]:
        yield "E_SCHEMA", f"{spec['name']}: {value!r} is not one of {', '.join(spec['levels'])}"
    elif kind == "multi-categorical":
        if not isinstance(value, list) or any(v not in spec["levels"] for v in value):
            yield "E_SCHEMA", f"{spec['name']}: {value!r} is not a subset of the levels"
    elif kind == "boolean" and not isinstance(value, bool):
        yield "E_SCHEMA", f"{spec['name']}: {value!r} is not yes or no"


def validate_record(
    record: dict[str, Any],
    schema: schema_mod.ExtractionSchema,
    registry: units_mod.UnitRegistry,
    *,
    where: str,
) -> list[Issue]:
    """Every problem with one record: schema shape, unit errors, incomplete effects."""
    try:
        validate("extraction-record", record)
    except SchemaValidationError as exc:
        return [Issue("E_SCHEMA", where, error) for error in exc.errors]
    issues: list[Issue] = []
    for name, entry in record["fields"].items():
        spec = schema.field(name)
        if spec is None:
            issues.append(Issue("E_SCHEMA", where, f"field {name!r} is not in the coding form"))
            continue
        issues.extend(Issue(code, where, msg) for code, msg in _check_stored(spec, entry, registry))
    declared = schema.designs
    for effect in record.get("effects", []):
        design = effect["design"]
        if design not in declared:
            issues.append(Issue("E_EFFECT_INPUTS", where, f"design {design!r} is not declared"))
            continue
        missing = effects_mod.missing_inputs(declared[design], effect)
        if missing:
            issues.append(
                Issue(
                    "E_EFFECT_INPUTS",
                    where,
                    f"{effect_key(effect)!r} ({design}) lacks: {', '.join(missing)}",
                )
            )
    return issues
