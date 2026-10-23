"""The effect rows an analysis pools: extracted effects joined to their study
(openspec:analysis-specification).

Each row is one extracted effect with its computed `yi`/`vi`, the study-level extraction fields,
the effect-level moderators and the risk-of-bias moderators, so a specification's `include.filter`
and its moderators can name any of them. Rows are built from the consensus extraction of the
included studies; an effect that cannot be computed, measures something else, or fails the filter
is *counted*, never silently dropped.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from strata.analysis.spec import AnalysisSpec
from strata.core import filters as filters_mod
from strata.core import records as records_mod
from strata.core.ids import normalise_year, record_id_for_report
from strata.core.repo import Repo
from strata.extract import effects as effects_mod
from strata.extract import records as extraction_records
from strata.extract import rob as rob_mod
from strata.protocol import studies as studies_mod
from strata.stats import escalc as es


class RowError(ValueError):
    """Rows cannot be built or filtered (a bad filter field, say)."""


@dataclass
class EffectRow:
    study_id: str
    effect_id: str
    label: str
    design: str
    measure: str
    yi: float
    vi: float
    n: int | None
    year: int | None
    outcome: str | None
    timepoint: str | None
    inputs: dict[str, Any]
    details: dict[str, Any]
    fields: dict[str, Any] = field(default_factory=dict)
    moderators: dict[str, Any] = field(default_factory=dict)
    rob: dict[str, Any] = field(default_factory=dict)

    @property
    def se(self) -> float:
        return math.sqrt(self.vi)

    def values(self) -> dict[str, Any]:
        """Everything a filter or a moderator may name.

        The identifying names (`study_id`, `effect_id`, `yi`, `vi`, `measure`, `n`, `year`, ...) are
        reserved; any other name is an extraction field or a moderator, which win over the
        convenience names (so `design` is the study's design if the form has one, and
        `effect_design` is always the way the effect was entered).
        """
        reserved = {
            "study_id": self.study_id,
            "effect_id": self.effect_id,
            "label": self.label,
            "measure": self.measure,
            "yi": self.yi,
            "vi": self.vi,
            "n": self.n,
            "year": self.year,
            "outcome": self.outcome,
            "timepoint": self.timepoint,
            "effect_design": self.design,
            "derived_from_pvalue": bool(self.details.get("derived_from_pvalue", False)),
            "derived_from": self.details.get("derived_from"),
            "assumed_correlation": self.details.get("assumed_correlation"),
        }
        return {"design": self.design, **self.fields, **self.moderators, **self.rob, **reserved}

    def resolver(self) -> filters_mod.FieldResolver:
        values = self.values()

        def resolve(name: str) -> Any:
            if name not in values:
                raise filters_mod.FilterEvaluationError(
                    f"unknown field {name!r} for effect {self.effect_id}; "
                    "name an extraction field, a moderator, or one of "
                    "study_id, outcome, timepoint, year, n, measure, rob_overall"
                )
            return values[name]

        return resolve


@dataclass
class Selection:
    rows: list[EffectRow]
    excluded: dict[str, list[str]] = field(default_factory=dict)  # reason -> effect ids
    candidates: int = 0

    def exclude(self, reason: str, effect_id: str) -> None:
        self.excluded.setdefault(reason, []).append(effect_id)


def _flat(entry: dict[str, Any] | None) -> Any:
    if entry is None or entry.get("not_reported"):
        return None
    return entry.get("value")


def _sample_size(inputs: dict[str, Any], study_n: Any) -> int | None:
    for pair in (("n1", "n2"),):
        if all(isinstance(inputs.get(k), (int, float)) for k in pair):
            return int(sum(inputs[k] for k in pair))
    if isinstance(inputs.get("n"), (int, float)):
        return int(inputs["n"])
    return int(study_n) if isinstance(study_n, (int, float)) else None


def _effect_inputs(effect: dict[str, Any]) -> dict[str, Any]:
    return {
        k: v
        for k, v in effect.items()
        if k not in ("id", "outcome", "design", "timepoint", "label", "source", "moderators")
    }


def compute_row(
    design: str, inputs: dict[str, Any], override_correlation: float | None = None
) -> es.EffectSize:
    """The effect for `design`; `override_correlation` replaces an assumed pre-post `r`."""
    if override_correlation is not None:
        inputs = {**inputs, "r": override_correlation}
    return effects_mod.compute(design, inputs)


def build_rows(repo: Repo, spec: AnalysisSpec, *, include_filter: bool = True) -> Selection:
    """Every effect of the included studies, selected for `spec`'s measure and filter."""
    members = studies_mod.study_map(repo).members
    consensus = {
        r["study"]: r
        for kind, _h, r, _p in extraction_records.all_records(repo)
        if kind == "consensus" and r.get("study") in members
    }
    robs = rob_mod.moderators(repo)
    records = records_mod.index_by_id(records_mod.read_records(repo))
    effect_cfg = spec.section("effect_size")
    flip = -1.0 if effect_cfg["direction"] == "lower-is-better" else 1.0
    selection = Selection(rows=[])
    expression = spec.section("include").get("filter") if include_filter else None

    for study in sorted(consensus):
        record = consensus[study]
        fields = {n: _flat(e) for n, e in (record.get("fields") or {}).items()}
        first = records.get(record_id_for_report(members[study][0]), {})
        citation = records_mod.short_citation(first)
        year = normalise_year(first.get("issued"))
        for effect in sorted(record.get("effects") or [], key=lambda e: str(e.get("id", ""))):
            effect_id = str(effect.get("id") or extraction_records.effect_key(effect))
            selection.candidates += 1
            inputs = _effect_inputs(effect)
            try:
                computed = compute_row(effect["design"], inputs)
            except (effects_mod.EffectInputError, es.EffectSizeError) as exc:
                selection.exclude(f"cannot be computed: {exc}", effect_id)
                continue
            if computed.measure != spec.measure:
                selection.exclude(f"measures {computed.measure}, not {spec.measure}", effect_id)
                continue
            if computed.details.get("double_zero") and spec.measure in ("logOR", "logRR"):
                selection.exclude("zero events in both arms (double-zero study)", effect_id)
                continue
            yi, vi = computed.yi, computed.vi
            details = dict(computed.details)
            if spec.measure == "SMD" and effect_cfg["correction"] == "none":
                d = float(details["d"])
                n1, n2 = float(details["n1"]), float(details["n2"])
                yi, vi = d, 1 / n1 + 1 / n2 + d**2 / (2 * (n1 + n2))
                details["correction"] = "none"
            row = EffectRow(
                study_id=study,
                effect_id=effect_id,
                label=_label(citation, effect),
                design=effect["design"],
                measure=computed.measure,
                yi=flip * yi,
                vi=vi,
                n=_sample_size(inputs, fields.get("n_total")),
                year=year,
                outcome=effect.get("outcome"),
                timepoint=effect.get("timepoint"),
                inputs=inputs,
                details=details,
                fields=fields,
                moderators=dict(effect.get("moderators") or {}),
                rob=dict(robs.get(study, {})),
            )
            if expression:
                try:
                    keep = filters_mod.matches_filter(expression, row.resolver())
                except filters_mod.FilterEvaluationError as exc:
                    raise RowError(f"include.filter: {exc}") from None
                if not keep:
                    selection.exclude("excluded by include.filter", effect_id)
                    continue
            selection.rows.append(row)
    return selection


def _label(citation: str, effect: dict[str, Any]) -> str:
    parts = [citation]
    detail = " ".join(str(effect[k]) for k in ("outcome", "timepoint", "label") if effect.get(k))
    if detail:
        parts.append(f"[{detail}]")
    return " ".join(parts)


def rows_by_filter(rows: list[EffectRow], expression: str) -> list[EffectRow]:
    """The rows matching a filter-language expression (a subset analysis)."""
    kept = []
    for row in rows:
        try:
            if filters_mod.matches_filter(expression, row.resolver()):
                kept.append(row)
        except filters_mod.FilterEvaluationError as exc:
            raise RowError(f"filter {expression!r}: {exc}") from None
    return kept
