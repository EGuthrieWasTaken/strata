"""Analysis specifications: `analysis/<id>.yaml` (openspec:analysis-specification).

A specification is declarative and versioned with the review. Loading validates it against its
JSON Schema, fills in the documented defaults (random effects, REML, Knapp-Hartung, 95%), and checks
the combinations the native engine cannot compute. A model that cannot be computed correctly is
refused with a pointer to `strata export effects` and the `metafor` engine, never approximated
(openspec:analysis-specification#validated-or-absent).
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any

from strata.core import filters as filters_mod
from strata.core.canon import load_yaml_str
from strata.core.repo import Repo
from strata.core.validate import SchemaValidationError, validate
from strata.extract.schema import plain

_EXPORT_HINT = (
    "use `strata export effects` to analyse it in R, or the optional `metafor` engine "
    '([analysis] engine = "metafor")'
)
DEFAULT_HETEROGENEITY = ("Q", "I2", "tau2", "H2", "prediction_interval")
RHO_SWEEP = (0.2, 0.5, 0.8)
R_SWEEP = (0.3, 0.5, 0.7)


class AnalysisSpecError(ValueError):
    """A specification is invalid or asks for something the native engine does not compute."""


@dataclass(frozen=True)
class AnalysisSpec:
    """A validated specification with defaults applied. `doc` is the normalised document."""

    doc: dict[str, Any]

    @property
    def id(self) -> str:
        return str(self.doc["id"])

    @property
    def title(self) -> str:
        return str(self.doc["title"])

    @property
    def preregistered(self) -> bool:
        return bool(self.doc["preregistered"])

    @property
    def measure(self) -> str:
        return str(self.doc["effect_size"]["measure"])

    @property
    def label(self) -> str:
        return "preregistered" if self.preregistered else "exploratory"

    def section(self, name: str) -> Any:
        return self.doc[name]


def analysis_dir(repo: Repo) -> Any:
    return repo.path("analysis")


def results_dir(repo: Repo, analysis_id: str) -> Any:
    return repo.path("analysis", "results", analysis_id)


def spec_path(repo: Repo, analysis_id: str) -> Any:
    return repo.path("analysis", f"{analysis_id}.yaml")


def list_analyses(repo: Repo) -> list[str]:
    directory = analysis_dir(repo)
    if not directory.exists():
        return []
    return sorted(p.stem for p in directory.glob("*.yaml"))


def parse_spec(raw: Any, *, where: str = "analysis specification") -> AnalysisSpec:
    """Validate and normalise a parsed document."""
    doc = plain(raw)
    if not isinstance(doc, dict):
        raise AnalysisSpecError(f"{where}: must be a mapping")
    try:
        validate("analysis", doc)
    except SchemaValidationError as exc:
        raise AnalysisSpecError(f"{where}: {'; '.join(exc.errors)}") from None
    out = copy.deepcopy(doc)
    out.setdefault("preregistered", False)
    effect = out["effect_size"]
    effect.setdefault("correction", "hedges")
    effect.setdefault("direction", "higher-is-better")
    out.setdefault("include", {})
    out["include"].setdefault("stage", "included")
    model = out.setdefault("model", {})
    model.setdefault("type", "random-effects")
    if model["type"] == "fixed-effect":
        model["type"] = "common-effect"  # the documented alias
    model.setdefault("tau2_estimator", "REML")
    model.setdefault("ci_method", "knapp-hartung")
    model.setdefault("level", 0.95)
    dependency = out.setdefault("dependency", {})
    dependency.setdefault("cluster", "study_id")
    dependency.setdefault("small_sample_correction", "CR2")
    for moderator in out.setdefault("moderators", []):
        if moderator["type"] == "continuous":
            moderator.setdefault("centering", "none")
    out.setdefault("heterogeneity", list(DEFAULT_HETEROGENEITY))
    out.setdefault("publication_bias", [])
    out.setdefault("sensitivity", [])
    out.setdefault("plots", [])
    out.setdefault("seed", 0)
    _check(out, where)
    return AnalysisSpec(out)


def _check(doc: dict[str, Any], where: str) -> None:
    effect, model, dependency = doc["effect_size"], doc["model"], doc["dependency"]
    if effect["correction"] == "none" and effect["measure"] != "SMD":
        raise AnalysisSpecError(f"{where}: correction 'none' applies to the SMD measure only")
    if model["type"] == "common-effect" and model["ci_method"] == "knapp-hartung":
        model["ci_method"] = "wald"  # Knapp-Hartung is not meant for common-effect models
    if model["type"] == "common-effect" and dependency.get("handling") in (
        "cluster-robust",
        "multilevel",
    ):
        raise AnalysisSpecError(
            f"{where}: a {dependency['handling']} dependency model estimates between-study "
            f"variance, so it cannot be combined with a common-effect model; {_EXPORT_HINT}"
        )
    handling = dependency.get("handling")
    if handling in ("aggregate", "cluster-robust", "multilevel") and "rho" not in dependency:
        raise AnalysisSpecError(
            f"{where}: dependency.rho (the assumed within-study correlation) must be given "
            f"explicitly for handling {handling!r}; it is recorded and swept over 0.2, 0.5, 0.8"
        )
    if handling in ("cluster-robust", "multilevel") and dependency["cluster"] != "study_id":
        raise AnalysisSpecError(
            f"{where}: only clustering on study_id is computed natively; {_EXPORT_HINT}"
        )
    if "prediction_interval" in doc["heterogeneity"] and model["type"] == "common-effect":
        doc["heterogeneity"] = [h for h in doc["heterogeneity"] if h != "prediction_interval"]
    ids = [s["id"] for s in doc["sensitivity"]]
    if len(ids) != len(set(ids)):
        raise AnalysisSpecError(f"{where}: sensitivity ids must be unique")
    for sens in doc["sensitivity"]:
        if sens["type"] == "subset" and not sens.get("filter"):
            raise AnalysisSpecError(f"{where}: sensitivity {sens['id']!r} (subset) needs a filter")
    names = [m["name"] for m in doc["moderators"]]
    if len(names) != len(set(names)):
        raise AnalysisSpecError(f"{where}: moderator names must be unique")
    for expression in [
        doc["include"].get("filter"),
        *(s.get("filter") for s in doc["sensitivity"]),
    ]:
        if expression:
            try:
                filters_mod.parse(expression)
            except filters_mod.FilterSyntaxError as exc:
                raise AnalysisSpecError(f"{where}: invalid filter {expression!r}: {exc}") from None
    if (
        effect["measure"] in ("PLO", "PFT", "SMCR")
        and doc["moderators"]
        and (model["type"] == "common-effect")
    ):
        raise AnalysisSpecError(
            f"{where}: moderators on a common-effect {effect['measure']} model are not computed; "
            f"{_EXPORT_HINT}"
        )


def load_spec(repo: Repo, analysis_id: str) -> AnalysisSpec:
    path = spec_path(repo, analysis_id)
    if not path.exists():
        raise AnalysisSpecError(f"there is no analysis {analysis_id!r} (looked for {path.name})")
    spec = parse_spec(load_yaml_str(path.read_text(encoding="utf-8")), where=path.name)
    if spec.id != analysis_id:
        raise AnalysisSpecError(f"{path.name}: its id {spec.id!r} must match the file name")
    return spec
