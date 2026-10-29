"""Operations that write to a review and commit, shared by every surface that offers them.

Implements openspec:architecture#mutating-operations-are-shared-services. The command line and the
web interface used to assemble these commits themselves; a copy per surface is how two surfaces come
to record the same action differently. An operation here takes the repository and its parameters,
writes, regenerates what the write moves, builds the structured commit and commits. A surface adds
only argument handling, rationale elicitation and presentation.

**Rationale.** A caller that already holds the rationale passes the text; the operation validates it
*before* it writes, so a rejected or missing one leaves the tree untouched
(openspec:git-integration#eliciting-the-rationale). The command line asks interactively, and only
after the work so that the prompt can say what was done, so it passes a callable instead; that is
invoked after the write and before the commit, and its result is validated like any other.

**Errors.** Domain errors (`SearchError`, `ImportPipelineError`, `SchemaValidationError`,
`RationaleRejectedError`) propagate to the caller, which reports them in its own terms.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeAlias

from strata import gitio
from strata.core.commit import (
    RationaleRejectedError,
    StructuredCommit,
    fit_subject,
    validate_rationale,
)
from strata.core.repo import Repo
from strata.ingest import pipeline as pipeline_mod
from strata.protocol import searches as searches_mod
from strata.report import counts as counts_mod

#: What a caller can hand an operation as its rationale: the text, nothing, or a function that
#: produces it once the work is written (the interactive prompt).
RationaleSource: TypeAlias = str | None | Callable[[], str | None]


def rationale_required(repo: Repo) -> bool:
    """Whether `git.require_rationale` is set, which it is unless a review turned it off."""
    return bool(repo.config.get("git", {}).get("require_rationale", True))


def rationale_problem(repo: Repo, text: str | None, *, always: bool = False) -> str | None:
    """Why `text` cannot be used as a rationale, or `None` if it can.

    For surfaces that hold the rationale before they act (a web form): refuse on this before
    writing anything. `always` is for operations that need a rationale whatever the review's
    setting says.
    """
    if text is None or not text.strip():
        if always or rationale_required(repo):
            return "a rationale is required for this operation"
        return None
    try:
        validate_rationale(text)
    except RationaleRejectedError as exc:
        return str(exc)
    return None


def _resolve_rationale(repo: Repo, source: RationaleSource) -> str | None:
    text = source() if callable(source) else source
    if text is None:
        if rationale_required(repo):
            raise RationaleRejectedError("a rationale is required for this operation")
        return None
    return validate_rationale(text)


def _check_up_front(
    repo: Repo, source: RationaleSource, *, commit: bool, needed: bool = True
) -> None:
    """Refuse, before anything is written, a text rationale that cannot be used.

    A callable is asked for later, after the work. A missing rationale only matters when something
    would be committed (`needed`), so a rerun that has nothing to record is not refused for want
    of one; a rationale that was supplied is validated either way.
    """
    if not commit or callable(source):
        return
    if source is None:
        if needed and rationale_required(repo):
            raise RationaleRejectedError("a rationale is required for this operation")
        return
    validate_rationale(source)


def _commit(
    repo: Repo,
    *,
    op: str,
    scope: str | None,
    summary: str,
    rationale: str | None,
    trailers: dict[str, str],
    paths: list[str],
) -> None:
    fitted_scope, fitted_summary = fit_subject(op, scope, summary)
    message = StructuredCommit(
        op=op, scope=fitted_scope, summary=fitted_summary, body=rationale, trailers=trailers
    ).message()
    gitio.add(repo.root, paths)
    gitio.commit(repo.root, message)


# ------------------------------------------------------------------------------------ searches


@dataclass(frozen=True)
class SearchRecorded:
    record: dict[str, Any]
    committed: bool

    @property
    def query_pending(self) -> bool:
        return bool(self.record["query"] == searches_mod.PENDING_QUERY)


def record_search(
    repo: Repo,
    *,
    database: str,
    platform: str,
    executed: str,
    executed_by: str,
    search_id: str | None = None,
    query: str | None = None,
    hits: int | None = None,
    export_files: Sequence[str] | None = None,
    peer_reviewed_by: str | None = None,
    notes: str | None = None,
    supersedes: str | None = None,
    commit: bool = True,
    rationale: RationaleSource = None,
    on_written: Callable[[SearchRecorded], None] | None = None,
) -> SearchRecorded:
    """Record an executed search (`strata search add`): write `protocol/searches/<id>.yaml`, commit.

    `on_written` is called with the result once the file exists and before the rationale is asked
    for, so a surface can say what it has done first.
    """
    _check_up_front(repo, rationale, commit=commit)
    record = searches_mod.add_search(
        repo,
        database=database,
        platform=platform,
        executed=executed,
        executed_by=executed_by,
        search_id=search_id,
        query=query,
        hits=hits,
        export_files=list(export_files) if export_files else [],
        peer_reviewed_by=peer_reviewed_by,
        notes=notes,
        supersedes=supersedes,
    )
    recorded = SearchRecorded(record=record, committed=False)
    if on_written is not None:
        on_written(recorded)
    if not commit:
        return recorded
    text = _resolve_rationale(repo, rationale)
    _commit(
        repo,
        op="search-add",
        scope=record["id"],
        summary=f"record search {record['id']}",
        rationale=text,
        trailers={"Op": "search-add", "Search": record["id"], "Actor": executed_by},
        paths=["protocol/searches"],
    )
    return SearchRecorded(record=record, committed=True)


# ------------------------------------------------------------------------------------ imports


@dataclass(frozen=True)
class ImportResult:
    outcome: pipeline_mod.ImportOutcome
    committed: bool


def would_import_anything(
    repo: Repo,
    files: Sequence[str | Path],
    *,
    imported_by: str,
    search_id: str | None = None,
    via: str | None = None,
    fmt: str | None = None,
    mapping: dict[str, str] | None = None,
    sheet: str | None = None,
) -> bool:
    """Whether any of `files` would add something (a dry run: nothing is written).

    A file that cannot be parsed contributes nothing here; the real run reports it as usual.
    """
    for file in files:
        try:
            outcome = pipeline_mod.import_file(
                repo,
                file,
                imported_by=imported_by,
                search_id=search_id,
                via=via,
                fmt=fmt,
                mapping=mapping,
                sheet=sheet,
                dry_run=True,
            )
        except pipeline_mod.ImportPipelineError:
            continue
        if not outcome.already_imported:
            return True
    return False


def import_file(
    repo: Repo,
    source_path: str | Path,
    *,
    imported_by: str,
    search_id: str | None = None,
    via: str | None = None,
    fmt: str | None = None,
    mapping: dict[str, str] | None = None,
    sheet: str | None = None,
    dry_run: bool = False,
    commit: bool = True,
    rationale: RationaleSource = None,
    on_written: Callable[[ImportResult], None] | None = None,
) -> ImportResult:
    """Import one export file (`strata import`): copy it raw, parse it, assign ids, commit.

    Each file is its own import and its own commit. A file already imported changes nothing and
    commits nothing; a dry run writes nothing at all. The PRISMA counts are regenerated for any
    real import, committed or not, because the identified and duplicate counts moved.
    """
    if not dry_run:
        _check_up_front(
            repo,
            rationale,
            commit=commit,
            needed=pipeline_mod.find_import_by_file(repo, source_path) is None,
        )
    outcome = pipeline_mod.import_file(
        repo,
        source_path,
        imported_by=imported_by,
        search_id=search_id,
        via=via,
        fmt=fmt,
        mapping=mapping,
        sheet=sheet,
        dry_run=dry_run,
    )
    result = ImportResult(outcome=outcome, committed=False)
    if on_written is not None:
        on_written(result)
    if outcome.already_imported or dry_run:
        return result
    counts_mod.regenerate_counts_json(repo)
    if not commit:
        return result
    text = _resolve_rationale(repo, rationale)
    _commit(
        repo,
        op="import",
        scope=outcome.import_id,
        summary=f"import {Path(source_path).name}",
        rationale=text,
        trailers={"Op": "import", "Import": outcome.import_id, "Actor": imported_by},
        paths=["imports", "records", "events", "derived"],
    )
    return ImportResult(outcome=outcome, committed=True)


@dataclass(frozen=True)
class ImportItem:
    """One file's fate in `import_files`: a result, or the reason it could not be imported."""

    file: str
    result: ImportResult | None
    error: str | None


def import_files(
    repo: Repo,
    files: Sequence[str | Path],
    *,
    imported_by: str,
    search_id: str | None = None,
    via: str | None = None,
    fmt: str | None = None,
    mapping: dict[str, str] | None = None,
    sheet: str | None = None,
    commit: bool = True,
    rationale: RationaleSource = None,
) -> list[ImportItem]:
    """Import each file in turn, one commit apiece, carrying on past a file that fails.

    A failure partway leaves every earlier file's import already committed rather than the tree
    half-written.
    """
    items: list[ImportItem] = []
    for file in files:
        try:
            result = import_file(
                repo,
                file,
                imported_by=imported_by,
                search_id=search_id,
                via=via,
                fmt=fmt,
                mapping=mapping,
                sheet=sheet,
                commit=commit,
                rationale=rationale,
            )
        except pipeline_mod.ImportPipelineError as exc:
            items.append(ImportItem(file=str(file), result=None, error=str(exc)))
            continue
        items.append(ImportItem(file=str(file), result=result, error=None))
    return items
