"""`strata verify`: whole-repository validation.

Implements the checks catalogued in docs/spec/03-schemas.md §10 that are in
scope at M0 (schema validation, hash-chain integrity, dangling references,
alias-graph acyclicity). Checks that depend on derived-view regeneration or
domain events not yet implemented (dedup, screening, extraction, analysis)
are added as those land.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from strata.core import events as events_mod
from strata.core.canon import load_yaml_str
from strata.core.repo import Repo
from strata.core.validate import SchemaValidationError, validate


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
        rel = str(path.relative_to(repo.root))
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
        rel = str(path.relative_to(repo.root))
        data = load_yaml_str(path.read_text(encoding="utf-8"))
        if not data:
            continue
        try:
            validate("search", dict(data))
        except SchemaValidationError as exc:
            for error in exc.errors:
                report.add("E_SCHEMA", error, path=rel)


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
    # "id" (docs/spec/02-repository-format.md §3.3) -- a non-canonical
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
    if not fast:
        _verify_aliases(repo, report)
        _verify_dangling_refs(repo, report, referenced_records)
    return report
