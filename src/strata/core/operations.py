"""Operations that write to a review and commit, shared by every surface that offers them.

Implements openspec:architecture#mutating-operations-are-shared-services. The command line and the
web interface used to assemble these commits themselves; a copy per surface is how two surfaces come
to record the same action differently. An operation here takes the repository and its parameters,
writes, regenerates what the write moves, builds the structured commit and commits. A surface adds
only argument handling, rationale elicitation and presentation.

**Rationale.** A caller that already holds the rationale passes the text; the operation validates
it *before* it writes, so a rejected or missing one leaves the tree untouched
(openspec:git-integration#eliciting-the-rationale). The command line asks interactively, and only
after the work so that the prompt can say what was done, so it passes a callable instead; that is
invoked after the write and before the commit, and its result is validated like any other.

**Locking.** Each operation holds the repository lock
(openspec:architecture#concurrency-and-locking) from just before it writes until its commit is
made, so a command line and a web server working on one repository cannot interleave their writes
or sweep each other's staged files into a commit. The lock is held while a callable rationale is
being answered, because the commit waits for it. A waiter gives up with `LockTimeoutError` naming
the holder, and a result says when the lock had been left by a process that died
(`lock_reclaimed_from`). Reads and dry runs never take it.

**Errors.** Domain errors (`SearchError`, `ImportPipelineError`, `FixFieldError`, `CriteriaError`,
`ScreeningError`, `RetrievalError`, `StudyError`, `FilterError`, `SchemaValidationError`,
`RationaleRejectedError`, `LockTimeoutError`) propagate to the caller, which reports them in its
own terms.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeAlias

from strata import gitio
from strata.core import filters as filters_mod
from strata.core import records as records_mod
from strata.core.commit import (
    RationaleRejectedError,
    StructuredCommit,
    fit_subject,
    validate_rationale,
)
from strata.core.repo import DEFAULT_LOCK_TIMEOUT, Repo, repo_lock
from strata.extract import rob as rob_mod
from strata.ingest import pipeline as pipeline_mod
from strata.protocol import criteria as criteria_mod
from strata.protocol import pool as pool_mod
from strata.protocol import retrieval as retrieval_mod
from strata.protocol import screening as screening_mod
from strata.protocol import searches as searches_mod
from strata.protocol import studies as studies_mod
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


#: Operations that cannot move a PRISMA count, so they do not regenerate derived/counts.json.
COUNT_NEUTRAL_OPS = frozenset({"extract", "reconcile", "rob", "analyze", "prisma", "report"})

#: Where the work of a domain operation can land (those that exist are what gets committed).
_DOMAIN_PATHS = (
    "records", "events", "derived", "fulltext/manifest.ndjson", "extraction", "rob", "analysis",
    "reports",
)  # fmt: skip


def commit_domain_work(
    repo: Repo,
    *,
    op: str,
    scope: str | None,
    summary: str,
    actor: str,
    extra_trailers: dict[str, str] | None = None,
    commit: bool = True,
    rationale: RationaleSource = None,
) -> bool:
    """Regenerate what a domain operation moved and commit what it wrote; whether it committed.

    For the operations whose work is files under `records`, `events`, `derived` and the like.
    Nothing is committed when the work left the tree as it was (a form re-created identically),
    and then no rationale is asked for. The counts are regenerated even without a commit.
    """
    if op not in COUNT_NEUTRAL_OPS:
        counts_mod.regenerate_counts_json(repo)  # whatever this changed, the counts follow it
    if not commit:
        return False
    paths = [p for p in _DOMAIN_PATHS if repo.path(*p.split("/")).exists()]
    if not gitio.has_changes(repo.root, paths):
        return False
    text = _resolve_rationale(repo, rationale)
    _commit(
        repo,
        op=op,
        scope=scope,
        summary=summary,
        rationale=text,
        trailers={"Op": op, "Actor": actor, **(extra_trailers or {})},
        paths=paths,
    )
    return True


# ------------------------------------------------------------------------------------ searches


@dataclass(frozen=True)
class SearchRecorded:
    record: dict[str, Any]
    committed: bool
    #: The process that left the lock behind, if the previous holder died holding it.
    lock_reclaimed_from: int | None = None

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
    lock_timeout: float = DEFAULT_LOCK_TIMEOUT,
) -> SearchRecorded:
    """Record an executed search (`strata search add`): write `protocol/searches/<id>.yaml`, commit.

    `on_written` is called with the result once the file exists and before the rationale is asked
    for, so a surface can say what it has done first.
    """
    _check_up_front(repo, rationale, commit=commit)
    with repo_lock(repo, timeout=lock_timeout) as held:
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
        recorded = SearchRecorded(
            record=record, committed=False, lock_reclaimed_from=held.reclaimed_from
        )
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
    return SearchRecorded(record=record, committed=True, lock_reclaimed_from=held.reclaimed_from)


# ------------------------------------------------------------------------------------ imports


@dataclass(frozen=True)
class ImportResult:
    outcome: pipeline_mod.ImportOutcome
    committed: bool
    #: The process that left the lock behind, if the previous holder died holding it.
    lock_reclaimed_from: int | None = None


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
    lock_timeout: float = DEFAULT_LOCK_TIMEOUT,
) -> ImportResult:
    """Import one export file (`strata import`): copy it raw, parse it, assign ids, commit.

    Each file is its own import and its own commit. A file already imported changes nothing and
    commits nothing; a dry run writes nothing at all and takes no lock. The PRISMA counts are
    regenerated for any real import, committed or not, because the identified and duplicate counts
    moved.
    """
    if dry_run:
        outcome = pipeline_mod.import_file(
            repo,
            source_path,
            imported_by=imported_by,
            search_id=search_id,
            via=via,
            fmt=fmt,
            mapping=mapping,
            sheet=sheet,
            dry_run=True,
        )
        result = ImportResult(outcome=outcome, committed=False)
        if on_written is not None:
            on_written(result)
        return result

    _check_up_front(
        repo,
        rationale,
        commit=commit,
        needed=pipeline_mod.find_import_by_file(repo, source_path) is None,
    )
    with repo_lock(repo, timeout=lock_timeout) as held:
        outcome = pipeline_mod.import_file(
            repo,
            source_path,
            imported_by=imported_by,
            search_id=search_id,
            via=via,
            fmt=fmt,
            mapping=mapping,
            sheet=sheet,
        )
        result = ImportResult(
            outcome=outcome, committed=False, lock_reclaimed_from=held.reclaimed_from
        )
        if on_written is not None:
            on_written(result)
        if outcome.already_imported:
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
    return ImportResult(outcome=outcome, committed=True, lock_reclaimed_from=held.reclaimed_from)


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


# ------------------------------------------------------------------------------ record filters


class FilterError(Exception):
    """A filter expression that cannot be used (openspec:filter-language).

    `str()` is the reason alone, without the name of any option, so each surface can put it in its
    own words. `record_id` is set when the expression parsed but could not be evaluated on a
    record.
    """

    def __init__(self, detail: str, *, record_id: str | None = None) -> None:
        super().__init__(detail)
        self.detail = detail
        self.record_id = record_id


def filter_records(
    records: list[dict[str, Any]], filter_expr: str, repo: Repo | None = None
) -> list[dict[str, Any]]:
    """The records a filter expression matches (openspec:filter-language).

    Given `repo`, a filter that names `rob_overall` / `rob.<domain>` sees each record's study-level
    risk-of-bias judgements (openspec:risk-of-bias#rob-plots-and-moderators). Raises `FilterError`
    for an expression that does not parse or cannot be evaluated on a record.
    """
    try:
        ast = filters_mod.parse(filter_expr)
    except filters_mod.FilterSyntaxError as exc:
        raise FilterError(str(exc)) from None
    moderators = (
        rob_mod.moderators_by_record(repo) if repo is not None and "rob" in filter_expr else None
    )
    matched = []
    for record in records:
        study_fields = None if moderators is None else moderators.get(record["id"], {})
        try:
            if filters_mod.evaluate(
                ast, records_mod.record_field_resolver(record, study_fields=study_fields)
            ):
                matched.append(record)
        except filters_mod.FilterEvaluationError as exc:
            raise FilterError(str(exc), record_id=record["id"]) from None
    return matched


def matching_record_ids(repo: Repo, filter_expr: str | None = None) -> list[str]:
    """Ids of the canonical records a filter matches (every canonical record without one)."""
    records = [
        r for r in records_mod.read_records(repo) if r.get("strata", {}).get("canonical", True)
    ]
    if filter_expr:
        records = filter_records(records, filter_expr, repo)
    return sorted(r["id"] for r in records)


# ------------------------------------------------------------------------------------ records


@dataclass(frozen=True)
class RecordAmended:
    record_id: str
    field: str
    old: Any
    new: Any
    committed: bool
    lock_reclaimed_from: int | None = None


def amend_record(
    repo: Repo,
    *,
    record_id: str,
    field: str,
    value: str,
    actor: str,
    commit: bool = True,
    rationale: RationaleSource = None,
    on_written: Callable[[RecordAmended], None] | None = None,
    lock_timeout: float = DEFAULT_LOCK_TIMEOUT,
) -> RecordAmended:
    """Correct one plain-string field of a record (`strata fix`) as a `record-amend` event.

    `record_id` is a full id; turning a prefix into one is the surface's business. A field that
    cannot be corrected, or an id with no record, raises before anything is written.
    """
    _check_up_front(repo, rationale, commit=commit)
    with repo_lock(repo, timeout=lock_timeout) as held:
        old, new = records_mod.amend_field(
            repo, record_id=record_id, field=field, value=value, actor=actor
        )
        amended = RecordAmended(
            record_id=record_id,
            field=field,
            old=old,
            new=new,
            committed=False,
            lock_reclaimed_from=held.reclaimed_from,
        )
        if on_written is not None:
            on_written(amended)
        committed = commit_domain_work(
            repo,
            op="fix",
            scope=record_id,
            summary=f"corrected {field}",
            actor=actor,
            commit=commit,
            rationale=rationale,
        )
    return RecordAmended(
        record_id=record_id,
        field=field,
        old=old,
        new=new,
        committed=committed,
        lock_reclaimed_from=held.reclaimed_from,
    )


# ---------------------------------------------------------------------------------- criteria


@dataclass(frozen=True)
class CriterionAdded:
    criterion: dict[str, Any]
    #: The criteria version after the addition.
    version: int
    committed: bool
    lock_reclaimed_from: int | None = None


def add_criterion(
    repo: Repo,
    *,
    kind: str,
    label: str,
    definition: str,
    applies_at: Sequence[str],
    actor: str,
    rationale: str,
    criterion_id: str | None = None,
    commit: bool = True,
    on_written: Callable[[CriterionAdded], None] | None = None,
    lock_timeout: float = DEFAULT_LOCK_TIMEOUT,
) -> CriterionAdded:
    """Add a criterion (`strata criteria add`); a criterion added behaves as `tightened`
    (openspec:criteria-management#declaring-the-direction-of-a-change).

    The rationale is required whatever `git.require_rationale` says, and with or without a commit,
    because it is recorded in the criteria event itself; it is validated before anything is
    written. What the change makes stale is regenerated even when nothing is committed.
    """
    text = validate_rationale(rationale)
    with repo_lock(repo, timeout=lock_timeout) as held:
        criterion = criteria_mod.add_criterion(
            repo,
            kind=kind,  # type: ignore[arg-type]
            label=label,
            definition=definition,
            applies_at=list(applies_at),
            actor=actor,
            rationale=text,
            criterion_id=criterion_id,
        )
        version = int(criteria_mod.read_criteria_doc(repo)["version"])
        added = CriterionAdded(
            criterion=criterion,
            version=version,
            committed=False,
            lock_reclaimed_from=held.reclaimed_from,
        )
        if on_written is not None:
            on_written(added)
        pool_mod.regenerate_all(repo)
        if commit:
            _commit(
                repo,
                op="criteria-add",
                scope=criterion["id"],
                summary=f"add criterion {criterion['id']}",
                rationale=text,
                trailers={"Op": "criteria-add", "Criterion": criterion["id"], "Actor": actor},
                paths=["protocol/criteria.yaml", "events/criteria", "derived"],
            )
    return CriterionAdded(
        criterion=criterion,
        version=version,
        committed=commit,
        lock_reclaimed_from=held.reclaimed_from,
    )


# ---------------------------------------------------------------------------------- assignment


@dataclass(frozen=True)
class ReviewersAssigned:
    stage: str
    actors: list[str]
    record_count: int
    committed: bool
    lock_reclaimed_from: int | None = None


def assign_reviewers(
    repo: Repo,
    *,
    stage: str,
    actors: Sequence[str],
    actor: str,
    filter_expr: str | None = None,
    commit: bool = True,
    rationale: RationaleSource = None,
    on_written: Callable[[ReviewersAssigned], None] | None = None,
    lock_timeout: float = DEFAULT_LOCK_TIMEOUT,
) -> ReviewersAssigned:
    """Assign reviewers to the canonical records at a stage (`strata assign`), all of them or
    those a filter expression matches. Raises `FilterError` for a filter that cannot be used and
    `ScreeningError` for an unknown stage, no actors, or no matching records.

    The handles are not checked against the review's actors, as the command line has never done;
    a surface that wants that checks before calling.
    """
    _check_up_front(repo, rationale, commit=commit)
    handles = [a.strip() for a in actors if a.strip()]
    with repo_lock(repo, timeout=lock_timeout) as held:
        record_ids = matching_record_ids(repo, filter_expr)
        screening_mod.assign_reviewers(
            repo,
            stage=stage,
            actors=handles,
            record_ids=record_ids,
            actor=actor,
            filter_expr=filter_expr,
        )
        assigned = ReviewersAssigned(
            stage=stage,
            actors=handles,
            record_count=len(record_ids),
            committed=False,
            lock_reclaimed_from=held.reclaimed_from,
        )
        if on_written is not None:
            on_written(assigned)
        committed = commit_domain_work(
            repo,
            op="assign",
            scope=stage,
            summary=f"assigned {len(record_ids)} {stage} record(s)",
            actor=actor,
            extra_trailers={"Actors": ",".join(handles)},
            commit=commit,
            rationale=rationale,
        )
    return ReviewersAssigned(
        stage=stage,
        actors=handles,
        record_count=len(record_ids),
        committed=committed,
        lock_reclaimed_from=held.reclaimed_from,
    )


# -------------------------------------------------------------------------------- retrieval


@dataclass(frozen=True)
class RetrievalRecorded:
    event: dict[str, Any]
    committed: bool
    lock_reclaimed_from: int | None = None


def record_retrieval(
    repo: Repo,
    *,
    report: str,
    outcome: str,
    actor: str,
    source: str | None = None,
    version: str | None = None,
    locator: dict[str, str] | None = None,
    reason: str | None = None,
    reason_text: str | None = None,
    path: str | None = None,
    commit: bool = True,
    rationale: RationaleSource = None,
    lock_timeout: float = DEFAULT_LOCK_TIMEOUT,
) -> RetrievalRecorded:
    """Record one retrieval outcome for a report (`strata retrieve --report --outcome`).

    Everything is validated before anything is written (`RetrievalError`), so a refused outcome
    leaves the tree as it was. `path` is a convenience of the command line, which names a file on
    the person's own machine; the web interface never passes one and strata does not store full
    texts either way.
    """
    _check_up_front(repo, rationale, commit=commit)
    with repo_lock(repo, timeout=lock_timeout) as held:
        event = retrieval_mod.record_retrieval(
            repo,
            report=report,
            status=outcome,
            actor=actor,
            source=source,
            locator=locator,
            version=version,
            reason=reason,
            reason_text=reason_text,
            path=path,
        )
        pool_mod.regenerate_all(repo)
        committed = commit_domain_work(
            repo,
            op="retrieve",
            scope=None,
            summary=f"{outcome}: {report}",
            actor=actor,
            commit=commit,
            rationale=rationale,
        )
    return RetrievalRecorded(
        event=event, committed=committed, lock_reclaimed_from=held.reclaimed_from
    )


# ----------------------------------------------------------------------------------- studies


@dataclass(frozen=True)
class StudyDecided:
    event: dict[str, Any]
    #: What the commit says was done, e.g. "grouped 2 report(s) into std_...".
    summary: str
    committed: bool
    lock_reclaimed_from: int | None = None


def _decide_study(
    repo: Repo,
    *,
    actor: str,
    rationale: str,
    commit: bool,
    lock_timeout: float,
    write: Callable[[str], tuple[dict[str, Any], str]],
) -> StudyDecided:
    text = validate_rationale(rationale)
    with repo_lock(repo, timeout=lock_timeout) as held:
        event, summary = write(text)
        committed = commit_domain_work(
            repo,
            op="studies",
            scope=None,
            summary=summary,
            actor=actor,
            commit=commit,
            rationale=text,
        )
    return StudyDecided(
        event=event, summary=summary, committed=committed, lock_reclaimed_from=held.reclaimed_from
    )


def group_reports(
    repo: Repo,
    *,
    reports: Sequence[str],
    actor: str,
    rationale: str,
    study: str | None = None,
    commit: bool = True,
    lock_timeout: float = DEFAULT_LOCK_TIMEOUT,
) -> StudyDecided:
    """Make reports one study (`strata studies --group`); with `study`, redefine that one.

    A grouping needs a rationale whatever `git.require_rationale` says, validated before anything
    is written. Suggestions are never applied by anything but a person calling this.
    """

    def write(text: str) -> tuple[dict[str, Any], str]:
        event = studies_mod.group_reports(
            repo, reports=list(reports), actor=actor, rationale=text, study=study
        )
        return event, f"grouped {len(set(reports))} report(s) into {event['body']['study']}"

    return _decide_study(
        repo,
        actor=actor,
        rationale=rationale,
        commit=commit,
        lock_timeout=lock_timeout,
        write=write,
    )


def split_report(
    repo: Repo,
    *,
    report: str,
    parts: int,
    actor: str,
    rationale: str,
    commit: bool = True,
    lock_timeout: float = DEFAULT_LOCK_TIMEOUT,
) -> StudyDecided:
    """Split one report into several studies (`strata studies --split`); a rationale is required."""

    def write(text: str) -> tuple[dict[str, Any], str]:
        event = studies_mod.split_report(
            repo, report=report, parts=parts, actor=actor, rationale=text
        )
        return event, f"split {report} into {parts} studies"

    return _decide_study(
        repo,
        actor=actor,
        rationale=rationale,
        commit=commit,
        lock_timeout=lock_timeout,
        write=write,
    )
