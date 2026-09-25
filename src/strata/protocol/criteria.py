"""Criteria management: `protocol/criteria.yaml` and the `criteria-change` event.

Implements docs/spec/06-workflow-screening.md §3 (direction classification)
and docs/spec/03-schemas.md §3 (the file shape and digest rules).

`criteria.yaml` is declarative configuration like `strata.toml` -- rewritten
in full on every change -- not an event-sourced view. The `criteria-change`
event in `events/criteria/<actor>.ndjson` is what makes the history
auditable and is what docs/spec/06-workflow-screening.md §4's staleness
rules are computed against; the YAML file only ever holds the *current*
state.

**Version numbering decision.** docs/spec/06-workflow-screening.md §3.1 (the
normative section) says "*any* change to the active criteria set increments
`criteria.version` by one." Taken literally, adding six criteria during
initial protocol setup produces version 6, not version 1 -- which
contradicts the terse "# 6 criteria, version 1" comment in §9's worked
example. Since §9 is explicitly informative and §3.1 is explicitly
normative, this module follows §3.1 literally: every `add`/`edit`/`retire`
bumps the version by one, full stop. `strata init` seeds `criteria.yaml` at
version 0 (not 1) precisely so that whichever criteria are added before the
protocol's first post-launch amendment land at `since_version: 1`, matching
the schema example (`INC-01`, `since_version: 1`) for the common case where
setup happens in one sitting before any screening starts -- the version
number only diverges from the narrative "1" when setup itself is spread
across multiple `strata criteria add` invocations, which is harmless because
no screening decisions exist yet to be affected by it.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any, Literal, get_args

from ruamel.yaml.scalarstring import FoldedScalarString

from strata.core.canon import canonical_json, dump_yaml_str, load_yaml_str
from strata.core.events import append_new_event, read_events
from strata.core.fold import sort_events
from strata.core.repo import Repo
from strata.core.validate import validate

CRITERIA_PATH = ("protocol", "criteria.yaml")

Kind = Literal["inclusion", "exclusion"]
Direction = Literal["tightened", "loosened", "both", "editorial"]
Origin = Literal["added", "edited", "retired"]

_KINDS: tuple[Kind, ...] = get_args(Kind)
_DIRECTIONS: tuple[Direction, ...] = get_args(Direction)

_ID_RE = re.compile(r"^(INC|EXC)-(\d+)$")
_WHITESPACE_RE = re.compile(r"\s+")

# Schema-declared key order (docs/spec/02-repository-format.md §5.3).
_FIELD_ORDER = (
    "id",
    "kind",
    "label",
    "definition",
    "applies_at",
    "since_version",
    "status",
    "examples",
)


class CriteriaError(ValueError):
    pass


def criteria_path(repo: Repo) -> Path:
    return repo.path(*CRITERIA_PATH)


def _empty_digest() -> str:
    return "sha256:" + hashlib.sha256(b"").hexdigest()


def per_criterion_digest(criterion: dict[str, Any]) -> str:
    """docs/spec/03-schemas.md §3: sha256 over `{id, kind, definition, applies_at}`.

    `label` and `examples` are deliberately excluded: relabelling is
    presentationally significant but never semantically significant, so it
    MUST NOT be able to make work stale.
    """
    payload = {
        "id": criterion["id"],
        "kind": criterion["kind"],
        "definition": criterion["definition"],
        "applies_at": sorted(criterion["applies_at"]),
    }
    return "sha256:" + hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def set_digest(criteria: list[dict[str, Any]]) -> str:
    """sha256 over the concatenation of per-criterion digests of *active* criteria, sorted by id."""
    active = sorted((c for c in criteria if c["status"] == "active"), key=lambda c: str(c["id"]))
    if not active:
        return _empty_digest()
    digests = [per_criterion_digest(c) for c in active]
    return "sha256:" + hashlib.sha256("\n".join(digests).encode("utf-8")).hexdigest()


def read_criteria_doc(repo: Repo) -> dict[str, Any]:
    path = criteria_path(repo)
    if not path.exists():
        return {"version": 0, "digest": _empty_digest(), "criteria": []}
    data = load_yaml_str(path.read_text(encoding="utf-8"))
    if not data:
        return {"version": 0, "digest": _empty_digest(), "criteria": []}
    return dict(data)


def _write(repo: Repo, doc: dict[str, Any]) -> None:
    validate("criteria", doc)
    yaml_criteria = []
    for criterion in doc["criteria"]:
        entry: dict[str, Any] = {k: criterion[k] for k in _FIELD_ORDER if k in criterion}
        entry["definition"] = FoldedScalarString(entry["definition"])
        yaml_criteria.append(entry)
    yaml_data = {"version": doc["version"], "digest": doc["digest"], "criteria": yaml_criteria}
    path = criteria_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump_yaml_str(yaml_data), encoding="utf-8")


def next_criterion_id(repo: Repo, kind: Kind) -> str:
    """Suggest the next unused `INC-nn`/`EXC-nn`, zero-padded, never reusing a retired number."""
    prefix = "INC" if kind == "inclusion" else "EXC"
    doc = read_criteria_doc(repo)
    existing_numbers = []
    for criterion in doc.get("criteria", []):
        match = _ID_RE.match(str(criterion["id"]))
        if match and match.group(1) == prefix:
            existing_numbers.append(int(match.group(2)))
    n = max(existing_numbers, default=0) + 1
    return f"{prefix}-{n:02d}"


def list_criteria(
    repo: Repo, *, at: str | None = None, version: int | None = None
) -> list[dict[str, Any]]:
    """All criteria, optionally filtered by stage (`at`) or reconstructed as of a past `version`."""
    if version is not None:
        criteria = reconstruct_at_version(repo, version)
    else:
        criteria = list(read_criteria_doc(repo).get("criteria", []))
    if at is not None:
        criteria = [c for c in criteria if at in c.get("applies_at", [])]
    return criteria


def get_criterion(repo: Repo, criterion_id: str) -> dict[str, Any] | None:
    for criterion in read_criteria_doc(repo).get("criteria", []):
        if criterion["id"] == criterion_id:
            return dict(criterion)
    return None


def _normalise_whitespace(text: str) -> str:
    return _WHITESPACE_RE.sub(" ", text).strip()


def _delta_from_criterion(
    criterion: dict[str, Any], *, origin: Origin, direction: Direction
) -> dict[str, Any]:
    return {
        "id": criterion["id"],
        "origin": origin,
        "direction": direction,
        "kind": criterion["kind"],
        "label": criterion["label"],
        "definition": criterion["definition"],
        "applies_at": list(criterion["applies_at"]),
        "since_version": criterion["since_version"],
        "status": criterion["status"],
    }


def _emit_change_event(
    repo: Repo,
    *,
    actor: str,
    from_version: int,
    to_version: int,
    deltas: list[dict[str, Any]],
    rationale: str,
) -> dict[str, Any]:
    events_path = repo.path("events", "criteria", f"{actor}.ndjson")
    body = {
        "from_version": from_version,
        "to_version": to_version,
        "deltas": deltas,
        "rationale": rationale,
    }
    return append_new_event(events_path, ev="criteria-change", actor=actor, body=body)


def _configured_stages(repo: Repo) -> list[str]:
    stages = repo.config.get("screening", {}).get("stages")
    return list(stages) if stages else []


def _validate_applies_at(repo: Repo, applies_at: list[str]) -> None:
    if not applies_at:
        raise CriteriaError("applies_at must be non-empty")
    configured = _configured_stages(repo)
    unknown = [s for s in applies_at if configured and s not in configured]
    if unknown:
        raise CriteriaError(
            f"applies_at names unconfigured stage(s) {unknown!r}; "
            f"screening.stages is {configured!r}"
        )


def add_criterion(
    repo: Repo,
    *,
    kind: Kind,
    label: str,
    definition: str,
    applies_at: list[str],
    actor: str,
    rationale: str,
    criterion_id: str | None = None,
    examples: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    """Add a criterion. A criterion **added** behaves as `tightened` (§3.2)."""
    if kind not in _KINDS:
        raise CriteriaError(f"kind must be one of {_KINDS}, got {kind!r}")
    if not label.strip():
        raise CriteriaError("label must not be empty")
    if len(label) > 80:
        raise CriteriaError("label must be at most 80 characters")
    if not definition.strip():
        raise CriteriaError("definition must not be empty")
    self_applies_at = list(applies_at)
    _validate_applies_at(repo, self_applies_at)

    doc = read_criteria_doc(repo)
    criteria = list(doc.get("criteria", []))
    resolved_id = criterion_id or next_criterion_id(repo, kind)
    if not _ID_RE.match(resolved_id):
        raise CriteriaError(f"criterion id {resolved_id!r} must look like INC-01 or EXC-01")
    if any(c["id"] == resolved_id for c in criteria):
        raise CriteriaError(f"a criterion {resolved_id!r} already exists")

    new_version = int(doc.get("version", 0)) + 1
    criterion: dict[str, Any] = {
        "id": resolved_id,
        "kind": kind,
        "label": label,
        "definition": definition,
        "applies_at": self_applies_at,
        "since_version": new_version,
        "status": "active",
    }
    if examples:
        criterion["examples"] = examples
    criteria.append(criterion)

    new_doc = {"version": new_version, "digest": set_digest(criteria), "criteria": criteria}
    _write(repo, new_doc)
    _emit_change_event(
        repo,
        actor=actor,
        from_version=new_version - 1,
        to_version=new_version,
        deltas=[_delta_from_criterion(criterion, origin="added", direction="tightened")],
        rationale=rationale,
    )
    return criterion


def edit_criterion(
    repo: Repo,
    criterion_id: str,
    *,
    direction: Direction,
    actor: str,
    rationale: str,
    label: str | None = None,
    definition: str | None = None,
    applies_at: list[str] | None = None,
    examples: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    """Edit a criterion's definition/label/applies_at/examples.

    `direction` MUST be supplied by the caller (docs/spec 06 §3.2 -- the tool
    asks the user to classify every definition change because it cannot
    reliably infer the classification from text). The `editorial` guard is
    enforced here: `editorial` is refused unless comparing old and new
    `definition` (after whitespace normalisation) and old and new
    `applies_at` (order-independent) shows no change at all.
    """
    if direction not in _DIRECTIONS:
        raise CriteriaError(f"direction must be one of {_DIRECTIONS}, got {direction!r}")

    doc = read_criteria_doc(repo)
    criteria = list(doc.get("criteria", []))
    index = next((i for i, c in enumerate(criteria) if c["id"] == criterion_id), None)
    if index is None:
        raise CriteriaError(f"no criterion {criterion_id!r}")
    existing = criteria[index]
    if existing["status"] != "active":
        raise CriteriaError(f"{criterion_id} is retired and cannot be edited")

    new_label = label if label is not None else existing["label"]
    if len(new_label) > 80:
        raise CriteriaError("label must be at most 80 characters")
    new_definition = definition if definition is not None else existing["definition"]
    if not new_definition.strip():
        raise CriteriaError("definition must not be empty")
    new_applies_at = list(applies_at) if applies_at is not None else list(existing["applies_at"])
    if applies_at is not None:
        _validate_applies_at(repo, new_applies_at)

    raw_definition_changed = new_definition != existing["definition"]
    meaning_changed = _normalise_whitespace(new_definition) != _normalise_whitespace(
        existing["definition"]
    ) or sorted(new_applies_at) != sorted(existing["applies_at"])
    applies_at_changed = sorted(new_applies_at) != sorted(existing["applies_at"])
    label_changed = new_label != existing["label"]
    examples_changed = examples is not None and examples != existing.get("examples")

    if not (raw_definition_changed or applies_at_changed or label_changed or examples_changed):
        raise CriteriaError("no change was made")

    if direction == "editorial" and meaning_changed:
        raise CriteriaError(
            "editorial asserts no semantic change, but the definition or applies_at changed "
            "in a way that is not just label/examples/whitespace -- choose tightened, "
            "loosened, or both instead (both is always safe if you are unsure)"
        )

    updated: dict[str, Any] = {
        **existing,
        "label": new_label,
        "definition": new_definition,
        "applies_at": new_applies_at,
    }
    if examples is not None:
        updated["examples"] = examples

    criteria[index] = updated
    new_version = int(doc.get("version", 0)) + 1
    new_doc = {"version": new_version, "digest": set_digest(criteria), "criteria": criteria}
    _write(repo, new_doc)
    _emit_change_event(
        repo,
        actor=actor,
        from_version=new_version - 1,
        to_version=new_version,
        deltas=[_delta_from_criterion(updated, origin="edited", direction=direction)],
        rationale=rationale,
    )
    return updated


def retire_criterion(
    repo: Repo, criterion_id: str, *, actor: str, rationale: str
) -> dict[str, Any]:
    """Retire a criterion. A criterion **retired** behaves as `loosened` (§3.2).

    The id is never reused (docs/spec/01-domain-model.md §3.4); the entry
    stays in the file forever with `status: retired`.
    """
    doc = read_criteria_doc(repo)
    criteria = list(doc.get("criteria", []))
    index = next((i for i, c in enumerate(criteria) if c["id"] == criterion_id), None)
    if index is None:
        raise CriteriaError(f"no criterion {criterion_id!r}")
    if criteria[index]["status"] == "retired":
        raise CriteriaError(f"{criterion_id} is already retired")

    updated = {**criteria[index], "status": "retired"}
    criteria[index] = updated
    new_version = int(doc.get("version", 0)) + 1
    new_doc = {"version": new_version, "digest": set_digest(criteria), "criteria": criteria}
    _write(repo, new_doc)
    _emit_change_event(
        repo,
        actor=actor,
        from_version=new_version - 1,
        to_version=new_version,
        deltas=[_delta_from_criterion(updated, origin="retired", direction="loosened")],
        rationale=rationale,
    )
    return updated


def all_criteria_change_events(repo: Repo) -> list[dict[str, Any]]:
    """Every `criteria-change` event across all actors, in deterministic `(ts, id)` order."""
    criteria_dir = repo.path("events", "criteria")
    if not criteria_dir.exists():
        return []
    events: list[dict[str, Any]] = []
    for path in sorted(criteria_dir.glob("*.ndjson")):
        events.extend(e for e in read_events(path) if e.get("ev") == "criteria-change")
    return sort_events(events)


def reconstruct_at_version(repo: Repo, version: int) -> list[dict[str, Any]]:
    """Rebuild the criteria set as it stood at `version`, by folding `criteria-change` deltas.

    Last-write-wins per criterion id, restricted to changes whose
    `to_version` does not exceed `version` -- the same fold shape as
    everything else in this codebase (docs/spec/02-repository-format.md
    §4.3), applied here to a declarative config file's own history rather
    than to `records.ndjson`.
    """
    state: dict[str, dict[str, Any]] = {}
    for event in all_criteria_change_events(repo):
        body = event["body"]
        if int(body["to_version"]) > version:
            continue
        for delta in body["deltas"]:
            state[delta["id"]] = {
                "id": delta["id"],
                "kind": delta["kind"],
                "label": delta["label"],
                "definition": delta["definition"],
                "applies_at": list(delta["applies_at"]),
                "since_version": delta["since_version"],
                "status": delta["status"],
            }
    return sorted(state.values(), key=lambda c: str(c["id"]))


def diff_versions(repo: Repo, v1: int, v2: int) -> list[dict[str, Any]]:
    """Every delta whose `to_version` lands in `(v1, v2]`, in event order.

    Does not (yet) compute what a change invalidated -- that needs
    screening state (docs/m2-plan.md sub-objective 4's
    `compute_stale_records`), which this module deliberately has no
    dependency on.
    """
    if v2 <= v1:
        raise CriteriaError(f"v2 ({v2}) must be greater than v1 ({v1})")
    deltas: list[dict[str, Any]] = []
    for event in all_criteria_change_events(repo):
        body = event["body"]
        if v1 < int(body["to_version"]) <= v2:
            deltas.extend(body["deltas"])
    return deltas
