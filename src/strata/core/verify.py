"""`strata verify`: whole-repository validation.

Implements the checks catalogued in openspec:repository-verification#cross-schema-validation-rules
that are in
scope at M0 (schema validation, hash-chain integrity, dangling references,
alias-graph acyclicity). Checks that depend on derived-view regeneration or
domain events not yet implemented (dedup, screening, extraction, analysis)
are added as those land.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ruamel.yaml.error import YAMLError

from strata.core import events as events_mod
from strata.core import fulltext as fulltext_mod
from strata.core.canon import load_yaml_str
from strata.core.ids import record_id_for_report, report_id, singleton_study_id
from strata.core.repo import Repo
from strata.core.validate import SchemaValidationError, validate
from strata.extract import records as extraction_records_mod
from strata.extract import rob as rob_mod
from strata.extract import schema as extraction_schema_mod
from strata.protocol import criteria as criteria_mod
from strata.protocol import studies as studies_mod


@dataclass
class VerifyIssue:
    code: str
    message: str
    path: str | None = None
    severity: str = "error"  # "warning" issues are reported but do not fail verification


@dataclass
class VerifyReport:
    issues: list[VerifyIssue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(i.severity == "warning" for i in self.issues)

    def add(
        self, code: str, message: str, path: str | None = None, *, severity: str = "error"
    ) -> None:
        self.issues.append(VerifyIssue(code=code, message=message, path=path, severity=severity))


def _verify_manifest(repo: Repo, report: VerifyReport) -> None:
    try:
        validate("manifest", repo.config)
    except SchemaValidationError as exc:
        for error in exc.errors:
            report.add("E_SCHEMA", error, path="strata.toml")


def _verify_events(repo: Repo, report: VerifyReport, *, fast: bool) -> tuple[set[str], set[str]]:
    """Validate every event file's schema and hash chain.

    Returns the record ids and the study ids that events refer to.
    """
    referenced_records: set[str] = set()
    referenced_studies: set[str] = set()
    for path in events_mod.iter_event_files(repo.root):
        rel = path.relative_to(repo.root).as_posix()
        raw_events = events_mod.read_events(path)
        for i, envelope in enumerate(raw_events):
            try:
                validate("event", envelope)
            except SchemaValidationError as exc:
                for error in exc.errors:
                    report.add("E_SCHEMA", f"line {i + 1}: {error}", path=rel)
            body = envelope.get("body", {})
            record = body.get("record") or body.get("canonical")
            if isinstance(record, str):
                referenced_records.add(record)
            for absorbed in body.get("absorbed") or []:
                referenced_records.add(absorbed)
            for report_ref in [body.get("report"), *(body.get("reports") or [])]:
                referenced_records |= _records_for_reports([report_ref])
            if envelope.get("ev") in ("extract", "reconcile", "rob") and isinstance(
                body.get("study"), str
            ):
                referenced_studies.add(body["study"])

        if not fast:
            for violation in events_mod.verify_chain(path):
                report.add(
                    "E_CHAIN",
                    f"line {violation.line} (event {violation.event_id}): {violation.reason}",
                    path=rel,
                )
    return referenced_records, referenced_studies


def _load_ndjson_field(path: Path, field: str) -> set[str]:
    if not path.exists():
        return set()
    values: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        obj = json.loads(line)
        if field in obj:
            values.add(obj[field])
    return values


def _records_for_reports(reports: list[Any]) -> set[str]:
    """Record ids behind report ids (`rpt_x` -> `rec_x`); a malformed id is E_SCHEMA's to report."""
    found: set[str] = set()
    for report_ref in reports:
        if not isinstance(report_ref, str):
            continue
        try:
            found.add(record_id_for_report(report_ref))
        except ValueError:
            continue
    return found


def _verify_fulltext_manifest(repo: Repo, report: VerifyReport) -> set[str]:
    """Schema-check `fulltext/manifest.ndjson` and return the record ids its entries cite.

    Deliberately compares nothing about `sha256`: two reviewers' copies of the same paper
    differ in bytes the moment one annotates it, which is not a discrepancy
    (openspec:full-text-retrieval#documents-are-never-identified-by-content-hash).
    """
    path = fulltext_mod.manifest_path(repo)
    if not path.exists():
        return set()
    rel = path.relative_to(repo.root).as_posix()
    cited: list[Any] = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
            validate("fulltext-entry", entry)
        except json.JSONDecodeError as exc:
            report.add("E_SCHEMA", f"line {i + 1}: not valid JSON ({exc.msg})", path=rel)
            continue
        except SchemaValidationError as exc:
            for error in exc.errors:
                report.add("E_SCHEMA", f"line {i + 1}: {error}", path=rel)
            continue
        cited.append(entry["report"])
    return _records_for_reports(cited)


def _verify_searches(repo: Repo, report: VerifyReport) -> None:
    searches_dir = repo.path("protocol", "searches")
    if not searches_dir.exists():
        return
    for path in sorted(searches_dir.glob("*.yaml")):
        rel = path.relative_to(repo.root).as_posix()
        data = load_yaml_str(path.read_text(encoding="utf-8"))
        if not data:
            continue
        try:
            validate("search", dict(data))
        except SchemaValidationError as exc:
            for error in exc.errors:
                report.add("E_SCHEMA", error, path=rel)


def _verify_records(repo: Repo, report: VerifyReport) -> None:
    path = repo.path("records", "records.ndjson")
    if not path.exists():
        return
    rel = path.relative_to(repo.root).as_posix()
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
        if not line.strip():
            continue
        try:
            validate("record", json.loads(line))
        except SchemaValidationError as exc:
            for error in exc.errors:
                report.add("E_SCHEMA", f"line {i + 1}: {error}", path=rel)


def _verify_criteria_reuse(repo: Repo, report: VerifyReport) -> None:
    """`E_CRITERION_REUSE`: a criterion id must never be used by two `added` deltas.

    Our own `protocol.criteria.add_criterion` already refuses to reuse an id
    still present in `criteria.yaml` (retired entries are never deleted), so
    this only fires against a hand-edited or corrupted repository where a
    criterion entry was removed and then its id reissued.
    """
    criteria_dir = repo.path("events", "criteria")
    if not criteria_dir.exists():
        return
    seen: set[str] = set()
    for path in sorted(criteria_dir.glob("*.ndjson")):
        for envelope in events_mod.read_events(path):
            if envelope.get("ev") != "criteria-change":
                continue
            for delta in envelope.get("body", {}).get("deltas", []):
                if delta.get("origin") != "added":
                    continue
                criterion_id = delta["id"]
                if criterion_id in seen:
                    report.add(
                        "E_CRITERION_REUSE",
                        f"criterion id {criterion_id!r} was added more than once",
                    )
                else:
                    seen.add(criterion_id)


def _verify_criteria(repo: Repo, report: VerifyReport) -> None:
    path = repo.path("protocol", "criteria.yaml")
    if path.exists():
        data = load_yaml_str(path.read_text(encoding="utf-8"))
        if data:
            try:
                validate("criteria", dict(data))
            except SchemaValidationError as exc:
                for error in exc.errors:
                    report.add("E_SCHEMA", error, path="protocol/criteria.yaml")
    # Driven by the event log, not the file, so it must run even when
    # criteria.yaml is missing or blank (a corrupted repository is exactly
    # the case this check exists to catch).
    _verify_criteria_reuse(repo, report)


def _verify_screen_events(repo: Repo, report: VerifyReport) -> None:
    """`E_EXCLUSION_NO_CRITERION` and `E_CRITERION_STAGE` (
    openspec:repository-verification#cross-schema-validation-rules) over persisted `screen` events
    -- a defensive check against a
    hand-edited or corrupted event file, since `protocol.screening.
    record_screen_decision` already refuses to write either violation.

    Citations are checked against the criteria set *as it stood at the
    event's own `criteria_version`* (via `reconstruct_at_version`), not the
    current set -- a criterion changing stage applicability after a
    decision was made is exactly what staleness (not a schema/integrity
    violation) is for.

    Full-mode only (like `_verify_aliases`/`_verify_dangling_refs`): this
    reconstructs criteria state from the event log, which is exactly the
    kind of cross-referencing check `fast=True` (the pre-commit hook) skips
    for speed and because every write through this module's own commands
    already validates before appending.
    """
    screen_dir = repo.path("events", "screen")
    if not screen_dir.exists():
        return
    require_reason = bool(repo.config.get("screening", {}).get("require_exclusion_reason", True))
    reconstructed_cache: dict[int, dict[str, dict[str, Any]]] = {}

    for path in sorted(screen_dir.glob("*.ndjson")):
        rel = path.relative_to(repo.root).as_posix()
        for envelope in events_mod.read_events(path):
            if envelope.get("ev") != "screen":
                continue
            body = envelope.get("body", {})
            stage = body.get("stage")
            decision = body.get("decision")
            cited = body.get("criteria") or []

            if decision == "exclude" and not cited and (stage == "full-text" or require_reason):
                report.add(
                    "E_EXCLUSION_NO_CRITERION",
                    f"exclude decision for {body.get('record')!r} at stage {stage!r} "
                    "cites no criterion",
                    path=rel,
                )

            version = body.get("criteria_version")
            if not cited or version is None:
                continue
            if version not in reconstructed_cache:
                reconstructed_cache[version] = {
                    c["id"]: c for c in criteria_mod.reconstruct_at_version(repo, int(version))
                }
            criteria_at_version = reconstructed_cache[version]
            for criterion_id in cited:
                criterion = criteria_at_version.get(criterion_id)
                if criterion is None or criterion["status"] != "active":
                    report.add(
                        "E_CRITERION_STAGE",
                        f"{criterion_id!r} was not an active criterion at criteria v{version}",
                        path=rel,
                    )
                elif stage not in criterion["applies_at"]:
                    report.add(
                        "E_CRITERION_STAGE",
                        f"{criterion_id!r} does not apply at stage {stage!r} (criteria v{version})",
                        path=rel,
                    )


def _verify_aliases(repo: Repo, report: VerifyReport) -> None:
    aliases_path = repo.path("records", "aliases.ndjson")
    if not aliases_path.exists():
        return
    edges: dict[str, str] = {}
    for line in aliases_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        obj = json.loads(line)
        edges[obj["alias"]] = obj["canonical"]

    for start in edges:
        seen: set[str] = set()
        node = start
        while node in edges:
            if node in seen:
                report.add("E_ALIAS_CYCLE", f"alias cycle starting at {start!r}")
                break
            seen.add(node)
            node = edges[node]


def _all_record_ids(repo: Repo) -> set[str]:
    return _load_ndjson_field(repo.path("records", "records.ndjson"), "id") | _load_ndjson_field(
        repo.path("records", "aliases.ndjson"), "alias"
    )


def _verify_dangling_refs(repo: Repo, report: VerifyReport, referenced_records: set[str]) -> None:
    # aliases.ndjson entries key the absorbed record's id as "alias", not
    # "id" (openspec:repository-format#authoritative-versus-derived-files) -- a non-canonical
    # record id therefore never appears in records.ndjson at all.
    record_ids = _load_ndjson_field(repo.path("records", "records.ndjson"), "id")
    alias_ids = _load_ndjson_field(repo.path("records", "aliases.ndjson"), "alias")
    known = record_ids | alias_ids
    for ref in sorted(referenced_records):
        if ref not in known:
            report.add("E_DANGLING_REF", f"event references unknown record {ref!r}")


def _known_studies(repo: Repo, record_ids: set[str]) -> set[str]:
    """Every study id that exists or ever existed: a singleton per record, plus every id a
    `study-group` / `study-split` event created."""
    known: set[str] = set()
    for record_id in record_ids:
        try:
            known.add(singleton_study_id(report_id(record_id)))
        except ValueError:
            continue
    for event in studies_mod.all_study_events(repo):
        body = event["body"]
        known.update([body["study"]] if "study" in body else body.get("studies", []))
    return known


def _verify_studies(
    repo: Repo, report: VerifyReport, record_ids: set[str], referenced_studies: set[str]
) -> None:
    known = _known_studies(repo, record_ids)
    for study in sorted(referenced_studies - known):
        report.add("E_DANGLING_REF", f"event references unknown study {study!r}")


def _verify_extraction(repo: Repo, report: VerifyReport) -> None:
    """`E_ORPHAN_EXTRACTION`, `E_MISSING_EXTRACTION`, `E_UNIT`, `E_EFFECT_INPUTS` and the schema
    of every extraction file (openspec:data-extraction). Nothing to check before extraction starts.
    """
    if not extraction_schema_mod.schema_exists(repo):
        return
    try:
        schema = extraction_schema_mod.load_schema(repo)
        registry = extraction_schema_mod.unit_registry(repo)
    except extraction_schema_mod.ExtractionSchemaError as exc:
        report.add("E_SCHEMA", str(exc), path="extraction/schema.yaml")
        return

    members = studies_mod.study_map(repo).members
    consensus: set[str] = set()
    for kind, _handle, path in extraction_records_mod.record_paths(repo):
        rel = path.relative_to(repo.root).as_posix()
        try:
            record = extraction_records_mod.read_record(path)
        except YAMLError as exc:
            report.add("E_SCHEMA", f"not valid YAML: {exc}", path=rel)
            continue
        if record is None:
            report.add("E_SCHEMA", "not a mapping", path=rel)
            continue
        for issue in extraction_records_mod.validate_record(record, schema, registry, where=rel):
            report.add(issue.code, issue.message, path=rel)
        study = record.get("study")
        if kind == "consensus" and isinstance(study, str):
            consensus.add(study)
        if isinstance(study, str) and study not in members:
            report.add(
                "E_ORPHAN_EXTRACTION",
                f"{study} has an extraction but is not an included study "
                "(the extraction is retained)",
                path=rel,
            )
    for study in sorted(set(members) - consensus):
        report.add(
            "E_MISSING_EXTRACTION",
            f"included study {study} has no consensus extraction",
            severity="warning",
        )


def _verify_rob(repo: Repo, report: VerifyReport) -> None:
    """The instrument and every risk-of-bias assessment (openspec:risk-of-bias). An assessment of
    a study that is no longer included is flagged and retained, as an extraction is."""
    if not rob_mod.instrument_path(repo).exists():
        return
    try:
        instrument = rob_mod.load_instrument(repo)
    except rob_mod.RobError as exc:
        report.add("E_SCHEMA", str(exc), path="rob/instrument.yaml")
        return
    members = studies_mod.study_map(repo).members
    for _kind, _handle, path in rob_mod.assessment_paths(repo):
        rel = path.relative_to(repo.root).as_posix()
        try:
            assessment = rob_mod.read_assessment(path)
        except YAMLError as exc:
            report.add("E_SCHEMA", f"not valid YAML: {exc}", path=rel)
            continue
        if assessment is None:
            report.add("E_SCHEMA", "not a mapping", path=rel)
            continue
        for problem in rob_mod.validate_assessment(instrument, assessment):
            report.add("E_SCHEMA", problem, path=rel)
        study = assessment.get("study")
        if isinstance(study, str) and study not in members:
            report.add(
                "E_ORPHAN_EXTRACTION",
                f"{study} has a risk-of-bias assessment but is not an included study "
                "(the assessment is retained)",
                path=rel,
            )


def _verify_counts(repo: Repo, report: VerifyReport) -> None:
    """The PRISMA counts close (openspec:prisma-reporting#counts-and-reconciliation-identities)."""
    from strata.report import counts as counts_mod

    for identity in counts_mod.compute(repo).failures:
        report.add(
            "E_COUNT_RECONCILE", f"the counts do not close: {identity}", path="derived/counts.json"
        )


def _verify_diagram(repo: Repo, report: VerifyReport) -> None:
    """A committed `reports/prisma.svg` is what `strata prisma` would draw now, byte for byte
    (openspec:prisma-reporting#flow-diagram). A warning: the diagram is out of date after any
    later decision until it is drawn again."""
    path = repo.path("reports", "prisma.svg")
    if not path.is_file():
        return
    from strata.report import counts as counts_mod
    from strata.report import flow as flow_mod

    counts = counts_mod.compute(repo)
    if not counts.reconciled:
        return
    committed = path.read_bytes()
    if committed not in (
        flow_mod.render(counts, fmt="svg", columns=columns) for columns in flow_mod.COLUMNS
    ):
        report.add(
            "W_DIAGRAM_STALE",
            "reports/prisma.svg differs from the diagram the current events produce; "
            "run strata prisma to draw it again",
            path="reports/prisma.svg",
            severity="warning",
        )


def _verify_analyses(repo: Repo, report: VerifyReport) -> None:
    """Every analysis specification parses, and committed results are not silently out of date:
    stale because the data changed, or because the tool did (openspec:analysis-specification)."""
    from strata.analysis import rows as analysis_rows
    from strata.analysis import run as analysis_run
    from strata.analysis import spec as analysis_spec

    for analysis_id in analysis_spec.list_analyses(repo):
        path = f"analysis/{analysis_id}.yaml"
        try:
            analysis_spec.load_spec(repo, analysis_id)
        except (analysis_spec.AnalysisSpecError, YAMLError) as exc:
            report.add("E_SCHEMA", str(exc), path=path)
            continue
        try:
            state = analysis_run.results_state(repo, analysis_id)
        except (analysis_rows.RowError, ValueError) as exc:
            report.add(
                "W_ANALYSIS_UNCHECKED",
                f"cannot check {analysis_id}: {exc}",
                path=path,
                severity="warning",
            )
            continue
        reason = {
            "stale-data": "stale because its data changed (strata analyze to refresh)",
            "stale-tool": "stale because the tool changed (strata analyze to refresh)",
        }.get(state)
        if reason:
            report.add(
                "W_ANALYSIS_STALE",
                f"analysis {analysis_id} is {reason}",
                path=f"analysis/results/{analysis_id}/run.json",
                severity="warning",
            )


def verify_repository(repo: Repo, *, fast: bool = False) -> VerifyReport:
    report = VerifyReport()
    _verify_manifest(repo, report)
    referenced_records, referenced_studies = _verify_events(repo, report, fast=fast)
    referenced_records |= _verify_fulltext_manifest(repo, report)
    _verify_searches(repo, report)
    _verify_records(repo, report)
    _verify_criteria(repo, report)
    if not fast:
        _verify_screen_events(repo, report)
        _verify_aliases(repo, report)
        _verify_dangling_refs(repo, report, referenced_records)
        _verify_studies(
            repo, report, referenced_records | _all_record_ids(repo), referenced_studies
        )
        _verify_extraction(repo, report)
        _verify_rob(repo, report)
        _verify_counts(repo, report)
        _verify_diagram(repo, report)
        _verify_analyses(repo, report)
    return report
