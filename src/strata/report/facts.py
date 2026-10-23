"""What the repository knows about how the review was done, gathered once for the reports.

The checklist and the generated Methods and Results sections both describe the same facts (the
searches, the criteria, who screened and how, the extraction and risk-of-bias process, the
analyses and what they found). Reading them in one place keeps those documents consistent with
each other and with the repository: nothing here is typed by hand, and nothing is invented.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from strata import __version__, gitio
from strata.analysis import spec as analysis_spec
from strata.core.repo import Repo
from strata.extract import reconcile as reconcile_mod
from strata.extract import records as extraction_records
from strata.extract import rob as rob_mod
from strata.extract import schema as extraction_schema
from strata.ingest import pipeline as import_pipeline
from strata.protocol import criteria as criteria_mod
from strata.protocol import irr as irr_mod
from strata.protocol import screening as screening_mod
from strata.protocol import searches as searches_mod
from strata.report import counts as counts_mod


@dataclass
class AnalysisFacts:
    id: str
    spec: analysis_spec.AnalysisSpec
    estimates: dict[str, Any] | None
    run: dict[str, Any] | None


@dataclass
class Facts:
    repo: Repo
    project: dict[str, Any]
    commit: str | None
    remote: str | None
    criteria: list[dict[str, Any]]
    criteria_version: int
    searches: list[dict[str, Any]]
    other_imports: list[dict[str, Any]]
    actors: list[dict[str, Any]]
    screening: dict[str, Any]
    stages: list[str]
    irr: dict[str, list[irr_mod.PairIrr]]
    extraction_mode: str
    extraction_schema: extraction_schema.ExtractionSchema | None
    agreement: dict[str, float | int] | None
    instrument: rob_mod.Instrument | None
    analyses: list[AnalysisFacts]
    counts: counts_mod.Counts
    dedup: dict[str, Any] = field(default_factory=dict)

    @property
    def version(self) -> str:
        return __version__

    def reviewers(self, *roles: str) -> list[str]:
        """Handles of active actors with one of `roles` (any active actor if none are given)."""
        return [
            str(a["handle"])
            for a in self.actors
            if a.get("role") != "inactive" and (not roles or a.get("role") in roles)
        ]


def _read_json(path: Any) -> dict[str, Any] | None:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return loaded if isinstance(loaded, dict) else None


def _analyses(repo: Repo) -> list[AnalysisFacts]:
    found = []
    for analysis_id in analysis_spec.list_analyses(repo):
        try:
            spec = analysis_spec.load_spec(repo, analysis_id)
        except ValueError:
            continue
        directory = analysis_spec.results_dir(repo, analysis_id)
        found.append(
            AnalysisFacts(
                analysis_id,
                spec,
                _read_json(directory / "estimates.json"),
                _read_json(directory / "run.json"),
            )
        )
    return found


def collect(repo: Repo) -> Facts:
    try:
        commit: str | None = gitio.current_commit(repo.root)
    except gitio.GitError:
        commit = None
    stages = screening_mod.configured_stages(repo)
    schema = extraction_schema.load_schema(repo) if extraction_schema.schema_exists(repo) else None
    mode = extraction_records.extraction_mode(repo)
    try:
        instrument: rob_mod.Instrument | None = rob_mod.load_instrument(repo)
    except rob_mod.RobError:
        instrument = None
    agreement = None
    if mode == "dual":
        agreement = reconcile_mod.agreement_rate(reconcile_mod.all_comparisons(repo))
    return Facts(
        repo=repo,
        project=dict(repo.config.get("project", {})),
        commit=commit,
        remote=gitio.get_config(repo.root, "remote.origin.url"),
        criteria=criteria_mod.list_criteria(repo),
        criteria_version=int(criteria_mod.read_criteria_doc(repo).get("version", 0)),
        searches=searches_mod.list_searches(repo),
        other_imports=[m for m in import_pipeline.list_import_manifests(repo) if m.get("via")],
        actors=list(repo.config.get("actors", [])),
        screening=dict(repo.config.get("screening", {})),
        stages=stages,
        irr={stage: irr_mod.compute_stage_irr(repo, stage) for stage in stages},
        extraction_mode=mode,
        extraction_schema=schema,
        agreement=agreement,
        instrument=instrument,
        analyses=_analyses(repo),
        counts=counts_mod.compute(repo),
        dedup=dict(repo.config.get("dedup", {})),
    )
