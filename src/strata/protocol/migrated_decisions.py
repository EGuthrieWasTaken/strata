"""Screening decisions carried in another tool's export, recorded as imported decisions
(openspec:literature-import#migration-imports-from-incumbent-tools).

`strata screen <stage> --by <actor> --decisions <export> --from rayyan|covidence|eppi-json`. The
records must already be in the review (`strata import --format <tool>` the same file). Each
decision is attributed to `--by` and marked `imported: true`, exactly as a decisions TSV is
(`screening.import_decisions_tsv`), because their independence cannot be verified.

A row is matched to its record by the identity `strata import` gives it (the canonical key,
through hand-corrected identities and duplicate merges). Nothing is guessed: a row that matches
no record, a reviewer's decision when another reviewer was asked for, a decision the stage cannot
take, and an exclusion whose reason names no criterion (when the review requires one) are each
skipped and reported, never recorded in a weaker form.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from strata.core import aliases as aliases_mod
from strata.core import records as records_mod
from strata.core.events import append_new_events
from strata.core.ids import assign_record_id, normalise_identifier_fields
from strata.core.repo import Repo
from strata.ingest.parsers import decode_bytes, normalise_newlines
from strata.ingest.parsers import migration as migration_parser
from strata.protocol import screening as screening_mod
from strata.protocol.screening import ScreeningError


@dataclass(frozen=True)
class Skipped:
    """A decision in the export that was not recorded, and why."""

    title: str
    why: str


@dataclass
class MigratedDecisions:
    recorded: list[dict[str, Any]] = field(default_factory=list)
    skipped: list[Skipped] = field(default_factory=list)
    #: Reviewers the export names, for `--reviewer`.
    reviewers: tuple[str, ...] = ()


def _record_index(repo: Repo) -> tuple[set[str], dict[str, str]]:
    records = records_mod.read_records(repo)
    known = {str(r["id"]) for r in records if r.get("strata", {}).get("canonical", True)}
    follow: dict[str, str] = {e["alias"]: e["canonical"] for e in aliases_mod.read_aliases(repo)}
    for record in records:
        for absorbed in record.get("strata", {}).get("absorbed", []):
            follow[str(absorbed)] = str(record["id"])
    return known, follow


def _resolve(record_id: str, known: set[str], follow: Mapping[str, str]) -> str | None:
    seen: set[str] = set()
    while record_id not in known and record_id in follow and record_id not in seen:
        seen.add(record_id)
        record_id = follow[record_id]
    return record_id if record_id in known else None


def import_tool_decisions(
    repo: Repo,
    *,
    stage: str,
    tool: str,
    raw: bytes,
    actor: str,
    reviewer: str | None = None,
    covidence_list: str | None = None,
    reasons: Mapping[str, str] | None = None,
) -> MigratedDecisions:
    """Record the decisions in `raw` (an export from `tool`) for `stage`, as `actor`.

    `reviewer` picks one reviewer's decisions where the export names several (Rayyan), and is
    required when it does; `covidence_list` says which Covidence list the file is; `reasons` maps
    an exclusion reason as the tool wrote it to the criterion it stands for.
    """
    if tool not in migration_parser.PARSERS:
        raise ScreeningError(f"--from must be one of {', '.join(migration_parser.TOOLS)}")
    if stage not in screening_mod.configured_stages(repo):
        stages = screening_mod.configured_stages(repo)
        raise ScreeningError(f"unknown stage {stage!r}; configured stages are {stages!r}")
    if tool == "covidence" and covidence_list not in migration_parser.COVIDENCE_LISTS:
        raise ScreeningError(
            "a Covidence export is one list: pass --list "
            + " | ".join(migration_parser.COVIDENCE_LISTS)
        )
    text, _encoding = decode_bytes(raw)
    try:
        parsed = migration_parser.PARSERS[tool](normalise_newlines(text))
    except migration_parser.MigrationFormatError as exc:
        raise ScreeningError(str(exc)) from None

    named = sorted({d.reviewer for ds in parsed.decisions for d in ds if d.reviewer})
    if named and reviewer is None:
        raise ScreeningError(
            "this export holds the decisions of several reviewers; pass --reviewer with one of: "
            + ", ".join(named)
        )
    if reviewer is not None and named and reviewer not in named:
        raise ScreeningError(
            f"no reviewer {reviewer!r} in this export; the reviewers are: {', '.join(named)}"
        )

    known, follow = _record_index(repo)
    lowered = {k.strip().lower(): v for k, v in (reasons or {}).items()}
    result = MigratedDecisions(reviewers=tuple(named))
    entries: list[tuple[str, str, dict[str, Any]]] = []
    for record, decisions in zip(parsed.records.records, parsed.decisions, strict=True):
        title = str(record.get("title", ""))
        candidate = dict(record)
        normalise_identifier_fields(candidate)
        rid, _key, _det = assign_record_id(candidate)
        target = _resolve(rid, known, follow)
        chosen = [d for d in decisions if reviewer is None or d.reviewer == reviewer]
        if not chosen:
            continue  # this reviewer made no decision on it: nothing to record
        if target is None:
            result.skipped.append(
                Skipped(title, "no record in the review matches it; import the file first")
            )
            continue
        for found in chosen:
            decision = found.decision
            if tool == "covidence":
                decision = migration_parser.covidence_decision(str(covidence_list), stage) or ""
                if not decision:
                    continue  # the list says nothing about this stage
            cited = sorted({lowered[r.lower()] for r in found.reasons if r.lower() in lowered})
            unmapped = [r for r in found.reasons if r.lower() not in lowered]
            note = (
                f"Imported from {tool}"
                + (f" ({found.reviewer})" if found.reviewer else "")
                + (f"; reason given: {', '.join(found.reasons)}" if found.reasons else "")
            )
            try:
                body = screening_mod.build_imported_body(
                    repo,
                    stage=stage,
                    record_id=target,
                    decision=decision,
                    cited=cited if decision == "exclude" else [],
                    note=note,
                )
            except ScreeningError as exc:
                why = str(exc)
                if decision == "exclude" and unmapped:
                    why = (
                        f"its reason ({', '.join(unmapped)}) names no criterion; map it with "
                        f"--reason '{unmapped[0]}=<criterion id>'"
                    )
                result.skipped.append(Skipped(title, why))
                continue
            entries.append(("screen", actor, body))
    if entries:
        result.recorded = append_new_events(
            screening_mod.screen_events_path(repo, stage, actor), entries
        )
    return result
