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

from strata.core import events as events_mod
from strata.core.canon import load_yaml_str
from strata.core.repo import Repo
from strata.core.validate import SchemaValidationError, validate
from strata.protocol import criteria as criteria_mod


@dataclass
class VerifyIssue:
    code: str
    message: str
    path: str | None = None


@dataclass
class VerifyReport:
    issues: list[VerifyIssue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.issues

    def add(self, code: str, message: str, path: str | None = None) -> None:
        self.issues.append(VerifyIssue(code=code, message=message, path=path))


def _verify_manifest(repo: Repo, report: VerifyReport) -> None:
    try:
        validate("manifest", repo.config)
    except SchemaValidationError as exc:
        for error in exc.errors:
            report.add("E_SCHEMA", error, path="strata.toml")


def _verify_events(repo: Repo, report: VerifyReport, *, fast: bool) -> set[str]:
    """Validate every event file's schema and hash chain. Returns all record ids referenced."""
    referenced_records: set[str] = set()
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

        if not fast:
            for violation in events_mod.verify_chain(path):
                report.add(
                    "E_CHAIN",
                    f"line {violation.line} (event {violation.event_id}): {violation.reason}",
                    path=rel,
                )
    return referenced_records


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


def verify_repository(repo: Repo, *, fast: bool = False) -> VerifyReport:
    report = VerifyReport()
    _verify_manifest(repo, report)
    referenced_records = _verify_events(repo, report, fast=fast)
    _verify_searches(repo, report)
    _verify_records(repo, report)
    _verify_criteria(repo, report)
    if not fast:
        _verify_screen_events(repo, report)
        _verify_aliases(repo, report)
        _verify_dangling_refs(repo, report, referenced_records)
    return report
