"""Dual extraction: comparing two reviewers' records and reconciling them into the consensus.

Implements openspec:data-extraction#dual-extraction-and-reconciliation. With `extraction.mode =
"dual"` each reviewer extracts independently into `extraction/by-reviewer/<handle>/<study>.yaml`.
Reconciling walks every field and every effect input, presents agreements and disagreements with
each reviewer's value and source, and writes the agreed result into
`extraction/consensus/<study>.yaml`. *Every* resolved item appends a `reconcile` event with the
chosen value, its source and a rationale: for a disagreement the reconciler's reason, for an
agreement the plain statement that the reviewers agreed. Nothing is silently merged.

Effects are matched across reviewers by `(outcome, timepoint, label)`. An effect only one reviewer
extracted is itself an item to resolve (keep it, or drop it with a reason).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from strata.core.events import append_new_event, read_events
from strata.core.ids import effect_id
from strata.core.repo import Repo
from strata.core.validate import validate_event_body
from strata.extract import records as rec_mod
from strata.extract import schema as schema_mod
from strata.protocol import studies as studies_mod

_NON_INPUT = frozenset({"id", "source", "moderators", "outcome", "design", "timepoint", "label"})
AGREEMENT = "agreement"
OTHER = "other"
DROPPED = "dropped"


class ReconcileError(ValueError):
    pass


@dataclass
class Item:
    """One thing to reconcile: a field, one input of an effect, or an effect's very presence."""

    id: str
    kind: str  # field | effect-input | effect
    label: str
    candidates: dict[str, Any]  # reviewer handle -> displayed value (None where absent)
    sources: dict[str, str | None]
    agree: bool
    resolved: bool = False


@dataclass
class Comparison:
    study: str
    handles: list[str]
    items: list[Item] = field(default_factory=list)

    @property
    def disagreements(self) -> list[Item]:
        return [i for i in self.items if not i.agree]

    @property
    def unresolved(self) -> list[Item]:
        return [i for i in self.items if not i.resolved]


def reviewer_handles(repo: Repo, study: str) -> list[str]:
    directory = repo.path("extraction", "by-reviewer")
    if not directory.exists():
        return []
    return sorted(p.name for p in directory.iterdir() if (p / f"{study}.yaml").exists())


def _display(entry: dict[str, Any] | None) -> Any:
    if entry is None:
        return None
    if entry.get("not_reported"):
        return "NR"
    if "unit" in entry:
        return f"{entry['value']} {entry['unit']}"
    return entry.get("value")


def _comparable(entry: dict[str, Any] | None) -> Any:
    if entry is None:
        return ("absent",)
    if entry.get("not_reported"):
        return ("nr",)
    return ("value", entry.get("value"), entry.get("unit"))


def _inputs(effect: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in effect.items() if k not in _NON_INPUT}


def compare(repo: Repo, study: str) -> Comparison:
    """Every field and effect input two or more reviewers extracted, with where they agree."""
    handles = reviewer_handles(repo, study)
    if len(handles) < 2:
        raise ReconcileError(
            f"{study} needs extractions from at least two reviewers (found {len(handles)})"
        )
    schema = schema_mod.load_schema(repo)
    by_handle = {
        h: rec_mod.read_record(rec_mod.reviewer_path(repo, h, study)) or {} for h in handles
    }
    consensus = rec_mod.read_record(rec_mod.consensus_path(repo, study)) or {}
    comparison = Comparison(study=study, handles=handles)

    names = [f["name"] for f in schema.fields]
    seen = {n for rec in by_handle.values() for n in rec.get("fields", {})}
    for name in names + sorted(seen - set(names)):
        entries = {h: by_handle[h].get("fields", {}).get(name) for h in handles}
        if all(e is None for e in entries.values()):
            continue
        comparison.items.append(
            Item(
                id=f"field:{name}",
                kind="field",
                label=name,
                candidates={h: _display(e) for h, e in entries.items()},
                sources={h: (e or {}).get("source") for h, e in entries.items()},
                agree=len({_comparable(e) for e in entries.values()}) == 1,
                resolved=name in consensus.get("fields", {}),
            )
        )

    effects = {
        h: {rec_mod.effect_key(e): e for e in by_handle[h].get("effects", [])} for h in handles
    }
    consensus_effects = {rec_mod.effect_key(e): e for e in consensus.get("effects", [])}
    for key in sorted({k for per in effects.values() for k in per}):
        present = {h: effects[h].get(key) for h in handles}
        if any(e is None for e in present.values()):
            comparison.items.append(
                Item(
                    id=f"effect:{key}",
                    kind="effect",
                    label=f"effect {key}",
                    candidates={
                        h: ("extracted" if e else "not extracted") for h, e in present.items()
                    },
                    sources={h: (e or {}).get("source") for h, e in present.items()},
                    agree=False,
                    resolved=key in consensus_effects or _dropped(repo, study, key),
                )
            )
            continue
        names_seen = sorted({n for e in present.values() for n in _inputs(e or {})})
        for name in names_seen:
            values = {h: (e or {}).get(name) for h, e in present.items()}
            comparison.items.append(
                Item(
                    id=f"effect-input:{key}:{name}",
                    kind="effect-input",
                    label=f"{key} / {name}",
                    candidates=values,
                    sources={h: (e or {}).get("source") for h, e in present.items()},
                    agree=len({repr(v) for v in values.values()}) == 1,
                    resolved=name in consensus_effects.get(key, {}),
                )
            )
    return comparison


def _dropped(repo: Repo, study: str, key: str) -> bool:
    directory = repo.path("events", "reconcile")
    if not directory.exists():
        return False
    for path in sorted(directory.glob("*.ndjson")):
        for event in read_events(path):
            body = event.get("body", {})
            if (
                body.get("study") == study
                and body.get("field") == f"effects.{key}"
                and body.get("from") == DROPPED
            ):
                return True
    return False


def agreement_rate(comparisons: list[Comparison]) -> dict[str, float | int]:
    """Share of compared items on which the reviewers independently agreed."""
    items = [i for c in comparisons for i in c.items]
    agreed = sum(1 for i in items if i.agree)
    return {
        "compared": len(items),
        "agreed": agreed,
        "rate": (agreed / len(items)) if items else 1.0,
    }


def all_comparisons(repo: Repo) -> list[Comparison]:
    found = []
    for study in sorted(studies_mod.study_map(repo).members):
        if len(reviewer_handles(repo, study)) >= 2:
            found.append(compare(repo, study))
    return found


# --- resolving -------------------------------------------------------------------------------


def _consensus(
    repo: Repo, study: str, reconciler: str, schema: schema_mod.ExtractionSchema
) -> tuple[Any, dict[str, Any]]:
    path = rec_mod.consensus_path(repo, study)
    record = rec_mod.read_record(path)
    if record is None:
        handles = reviewer_handles(repo, study)
        record = rec_mod.new_record(
            study, studies_mod.study_map(repo).members[study], schema.version, handles[0]
        )
        record["extracted_by"] = handles
    record["schema_version"] = schema.version
    record["reconciled_by"] = reconciler
    return path, record


def _log(
    repo: Repo,
    *,
    reconciler: str,
    study: str,
    field_id: str,
    chosen: Any,
    origin: str,
    rationale: str,
    candidates: dict[str, Any],
    source: str | None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "study": study,
        "field": field_id,
        "chosen": chosen,
        "from": origin,
        "rationale": rationale,
        "candidates": candidates,
    }
    if source:
        body["source"] = source
    validate_event_body("reconcile", body)
    return append_new_event(
        repo.path("events", "reconcile", f"{reconciler}.ndjson"),
        ev="reconcile",
        actor=reconciler,
        body=body,
    )


def _joined_sources(item: Item, handles: list[str]) -> str | None:
    distinct = []
    for h in handles:
        source = item.sources.get(h)
        if source and source not in distinct:
            distinct.append(source)
    return " | ".join(distinct) or None


def resolve(
    repo: Repo,
    *,
    study: str,
    reconciler: str,
    item_id: str,
    choice: str,
    rationale: str,
    other_value: str | None = None,
    source: str | None = None,
) -> dict[str, Any]:
    """Resolve one item. `choice` is a reviewer's handle, `agreement`, `other` (with
    `other_value`), or `dropped` (an effect only one reviewer extracted)."""
    comparison = compare(repo, study)
    item = next((i for i in comparison.items if i.id == item_id), None)
    if item is None:
        raise ReconcileError(f"nothing to reconcile named {item_id!r} for {study}")
    if not rationale.strip():
        raise ReconcileError("every reconciliation needs a rationale")
    if choice == AGREEMENT and not item.agree:
        raise ReconcileError(f"{item_id} is a disagreement; choose a reviewer or give a value")
    if choice not in (AGREEMENT, OTHER, DROPPED) and choice not in comparison.handles:
        raise ReconcileError(
            f"choose one of {', '.join(comparison.handles)}, {OTHER}, or {AGREEMENT}"
        )

    if item.kind == "effect" and item.candidates.get(choice) == "not extracted":
        raise ReconcileError(
            f"{choice} did not extract this effect; choose the reviewer who did, or drop it"
        )

    schema = schema_mod.load_schema(repo)
    path, record = _consensus(repo, study, reconciler, schema)
    reviewer = comparison.handles[0] if choice in (AGREEMENT, OTHER, DROPPED) else choice
    reviewer_record = rec_mod.read_record(rec_mod.reviewer_path(repo, reviewer, study)) or {}
    chosen_source = source or (
        _joined_sources(item, comparison.handles)
        if choice == AGREEMENT
        else item.sources.get(choice)
    )

    if item.kind == "field":
        name = item_id.removeprefix("field:")
        if choice == OTHER:
            spec = schema.field(name)
            if spec is None or other_value is None:
                raise ReconcileError(
                    "choosing 'other' needs a value for a field in the coding form"
                )
            entry = rec_mod.coerce_value(spec, other_value, schema_mod.unit_registry(repo))
        else:
            entry = dict(reviewer_record.get("fields", {}).get(name) or {})
            if not entry:
                raise ReconcileError(f"{reviewer} did not extract {name}")
        entry.pop("source", None)
        if chosen_source:
            entry["source"] = chosen_source
        record["fields"][name] = entry
        field_id, chosen = name, entry.get("value")
    elif item.kind == "effect-input":
        _, key, name = item_id.split(":", 2)
        effect = _consensus_effect(record, key, reviewer_record, study, repo)
        if choice == OTHER:
            if other_value is None:
                raise ReconcileError("choosing 'other' needs a value")
            effect[name] = rec_mod._numeric({name: other_value})[name]
        else:
            effect[name] = _find_effect(reviewer_record, key).get(name)
        field_id, chosen = f"effects.{key}.{name}", effect[name]
    else:
        key = item_id.removeprefix("effect:")
        field_id = f"effects.{key}"
        if choice == DROPPED:
            chosen = None
        else:
            donor = (
                choice
                if choice in comparison.handles
                else next(h for h, v in item.candidates.items() if v == "extracted")
            )
            donor_record = rec_mod.read_record(rec_mod.reviewer_path(repo, donor, study)) or {}
            effect = _consensus_effect(record, key, donor_record, study, repo, copy_all=True)
            chosen = {k: v for k, v in effect.items() if k not in ("id",)}
            reviewer = donor

    digest = rec_mod.write_record(path, record, schema)
    del digest
    return _log(
        repo,
        reconciler=reconciler,
        study=study,
        field_id=field_id,
        chosen=chosen,
        origin=choice,
        rationale=rationale.strip(),
        candidates={h: v for h, v in item.candidates.items()},
        source=chosen_source,
    )


def _find_effect(record: dict[str, Any], key: str) -> dict[str, Any]:
    effect: dict[str, Any]
    for effect in record.get("effects", []):
        if rec_mod.effect_key(effect) == key:
            return effect
    return {}


def _consensus_effect(
    record: dict[str, Any],
    key: str,
    donor_record: dict[str, Any],
    study: str,
    repo: Repo,
    *,
    copy_all: bool = False,
) -> dict[str, Any]:
    """The consensus effect for `key`, created (with a fresh id) from the donor's if missing."""
    effects: list[dict[str, Any]] = record.setdefault("effects", [])
    existing: dict[str, Any] | None = next(
        (e for e in effects if rec_mod.effect_key(e) == key), None
    )
    if existing is not None:
        return existing
    donor = _find_effect(donor_record, key)
    base: dict[str, Any] = (
        {k: v for k, v in donor.items() if k != "id"}
        if copy_all
        else {k: donor[k] for k in ("outcome", "design", "timepoint", "label") if k in donor}
    )
    for passthrough in ("source", "moderators"):
        if passthrough in donor and not copy_all:
            base[passthrough] = donor[passthrough]
    base["id"] = effect_id(study, rec_mod._next_effect_sequence(effects))
    effects.append(base)
    return base


def accept_agreements(repo: Repo, *, study: str, reconciler: str) -> int:
    """Confirm every item the reviewers already agree on (one `reconcile` event each)."""
    confirmed = 0
    for item in compare(repo, study).items:
        if item.agree and not item.resolved:
            resolve(
                repo,
                study=study,
                reconciler=reconciler,
                item_id=item.id,
                choice=AGREEMENT,
                rationale="Both reviewers extracted the same value.",
            )
            confirmed += 1
    return confirmed
