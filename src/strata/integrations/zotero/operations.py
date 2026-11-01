"""What `strata zotero link | pull | push | status | open` do.

Implements openspec:zotero-integration#commands, #identity-mapping and
#append-only-meets-mutable. The command line only gathers arguments and presents results; every
rule about what crosses between Zotero and the review lives here.

Zotero owns the documents and `strata` owns the decisions, so the traffic is narrow and one-way per
operation: a *pull* brings bibliographic items in as an ordinary import (and corrects records whose
metadata Zotero has since improved, as `record-amend` events); a *push* puts the studies a review
included into a Zotero collection. Neither carries a screening decision across, and neither deletes
or overwrites anything the other side owns.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from strata.core import manifest as manifest_mod
from strata.core import operations as ops_mod
from strata.core import records as records_mod
from strata.core.canon import canonical_json
from strata.core.ids import IDENTIFIER_NORMALISERS
from strata.core.records import Amendment, FieldChange
from strata.core.repo import DEFAULT_LOCK_TIMEOUT, Repo, repo_lock
from strata.dedup import engine as dedup_engine
from strata.ingest import pipeline as pipeline_mod
from strata.ingest.parsers import RejectedRow
from strata.integrations.reference_manager import (
    Collection,
    ItemRef,
    PushItem,
    PushOutcome,
    ReferenceManagerError,
    RemoteItem,
    Resolution,
)
from strata.integrations.zotero import mapping as mapping_mod
from strata.integrations.zotero.connect import Connection, ZoteroLink, read_link
from strata.integrations.zotero.manager import LibraryInfo, list_libraries
from strata.integrations.zotero.mapping import MappingRow
from strata.integrations.zotero.matching import (
    AmbiguousItem,
    MatchReport,
    RecordIndex,
    match_items,
)
from strata.protocol import screening as screening_mod

#: Opens a connection to Zotero: `(transport preference, need_write) -> Connection`. The command
#: line supplies one that knows about keychains and prompts; tests supply one over a fake.
Connector = Callable[[str, bool], Connection]

#: The sets of records `strata zotero push --set` accepts.
PUSH_SETS = ("included",)

#: The bibliographic fields on which Zotero wins a conflict. Anything decision-shaped (screening
#: state, extraction, risk of bias) is not a field of the record at all and never crosses.
BIBLIOGRAPHIC_FIELDS = (
    "title",
    "author",
    "issued",
    "container-title",
    "volume",
    "issue",
    "page",
    "DOI",
    "PMID",
    "PMCID",
    "URL",
    "ISBN",
    "abstract",
    "language",
)

_SLUG_RE = re.compile(r"[^a-z0-9]+")
_GITATTRIBUTES_LINE = "integrations/*.ndjson  merge=union\n"


class ZoteroOperationError(ValueError):
    """An operation that cannot be done as asked; `str()` is fit to show a person."""


class NotLinkedError(ZoteroOperationError):
    """The review has no Zotero link, or the record has no Zotero item."""


class StaleLinkError(ZoteroOperationError):
    """The Zotero item a record was mapped to no longer exists."""


def _today() -> str:
    return date.today().isoformat()


def _require_link(repo: Repo) -> ZoteroLink:
    link = read_link(repo)
    if link is None:
        raise NotLinkedError(
            "this review is not linked to a Zotero library; run `strata zotero link` first"
        )
    return link


# ----------------------------------------------------------------------------------------- link


@dataclass(frozen=True)
class LinkResult:
    library: str
    transport: str
    #: Whether the link can push, and when it cannot, why.
    write: bool
    write_note: str | None
    rows_written: int
    report: MatchReport
    notices: tuple[str, ...]
    committed: bool
    lock_reclaimed_from: int | None = None


def _choose_library(
    libraries: Sequence[LibraryInfo],
    requested: str | None,
    chooser: Callable[[Sequence[LibraryInfo]], str] | None,
) -> str:
    ids = [lib.library for lib in libraries]
    listing = ", ".join(f"{lib.library} ({lib.name})" for lib in libraries)
    if requested is not None:
        if requested not in ids:
            raise ZoteroOperationError(f"{requested!r} is not one of your libraries: {listing}")
        return requested
    if len(ids) == 1:
        return ids[0]
    if chooser is not None:
        chosen = chooser(libraries)
        if chosen in ids:
            return chosen
    raise ZoteroOperationError(f"several libraries are available; pass --library one of: {listing}")


def _write_permission(connection: Connection, library: str) -> tuple[bool, str | None]:
    """Whether a push to `library` can work, decided now rather than at push time."""
    if connection.transport == "web" and connection.key_info is not None:
        if connection.key_info.can_write(library):
            return True, None
        return False, (
            f"the API key cannot write to {library}, so pushes will be refused; give the key "
            "write access at https://www.zotero.org/settings/keys, then link again"
        )
    return False, (
        "linked read-only through the local API; to push included studies back to Zotero, run "
        "`strata zotero link --web` with an API key that can write"
    )


def _save_link(repo: Repo, library: str, transport: str, write: bool) -> None:
    doc = manifest_mod.load_manifest_doc(repo.root)
    manifest_mod.set_value(doc, "zotero.library", library)
    manifest_mod.set_value(doc, "zotero.transport", transport)
    manifest_mod.set_value(doc, "zotero.write", write)
    manifest_mod.write_manifest(repo.root, doc)
    repo.config["zotero"] = {"library": library, "transport": transport, "write": write}


def _has_union_rule(repo: Repo) -> bool:
    path = repo.path(".gitattributes")
    return path.exists() and "integrations/*.ndjson" in path.read_text(encoding="utf-8")


def _ensure_union_merge(repo: Repo) -> None:
    """Make sure two collaborators linking at once merge by union, as the other append-only
    files do. A review created before this integration existed lacks the line."""
    if _has_union_rule(repo):
        return
    path = repo.path(".gitattributes")
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    separator = "" if not text or text.endswith("\n") else "\n"
    path.write_text(text + separator + _GITATTRIBUTES_LINE, encoding="utf-8")


def link(
    repo: Repo,
    *,
    actor: str,
    connector: Connector,
    library: str | None = None,
    web: bool = False,
    choose_library: Callable[[Sequence[LibraryInfo]], str] | None = None,
    commit: bool = True,
    rationale: ops_mod.RationaleSource = None,
    lock_timeout: float = DEFAULT_LOCK_TIMEOUT,
) -> LinkResult:
    """Connect the review to a Zotero library and map the records it already has to its items.

    Detects the local API (or, with `web`, uses the Web API), picks the library, checks now whether
    pushes will be allowed, writes the link to `strata.toml` (never a key), and matches the
    library's items to the review's records by the canonical-key ladder. Items that match nothing
    are reported, not forced onto the nearest record. Nothing about any record changes.
    """
    ops_mod.check_rationale_up_front(repo, rationale, commit=commit, needed=False)
    connection = connector("web" if web else "auto", False)
    libraries = list_libraries(
        connection.api, connection.personal_library, local=connection.transport == "local"
    )
    chosen = _choose_library(libraries, library, choose_library)
    write, write_note = _write_permission(connection, chosen)
    items = connection.manager(chosen).all_items()

    with repo_lock(repo, timeout=lock_timeout) as held:
        records = records_mod.read_records(repo)
        index = RecordIndex(records)
        absorbed = mapping_mod.absorbed_into(records)
        rows = mapping_mod.read_mapping(repo)
        linked_records = frozenset(
            mapping_mod.canonical_record_id(r.record, index.canonical, absorbed) or r.record
            for r in mapping_mod.current_rows(rows, chosen)
        )
        _auto, review_threshold = dedup_engine.thresholds(repo, strict=False)
        report = match_items(
            items, index, review_threshold=review_threshold, exclude_records=linked_records
        )
        new_rows = _rows_for_matches(report, chosen, rows)
        settings = ZoteroLink(chosen, "web" if web else "auto", write)
        # A rerun that finds nothing new is not refused for want of a rationale it would not use.
        ops_mod.check_rationale_up_front(
            repo,
            rationale,
            commit=commit,
            needed=bool(new_rows) or read_link(repo) != settings or not _has_union_rule(repo),
        )
        mapping_mod.append_rows(repo, new_rows)
        _save_link(repo, settings.library, settings.transport, settings.write)
        _ensure_union_merge(repo)
        committed = ops_mod.commit_domain_work(
            repo,
            op="zotero-link",
            scope=chosen,
            summary=f"link Zotero library {chosen}",
            actor=actor,
            extra_paths=("strata.toml", ".gitattributes"),
            commit=commit,
            rationale=rationale,
        )
    return LinkResult(
        library=chosen,
        transport=connection.transport,
        write=write,
        write_note=write_note,
        rows_written=len(new_rows),
        report=report,
        notices=connection.notices,
        committed=committed,
        lock_reclaimed_from=held.reclaimed_from,
    )


def _rows_for_matches(
    report: MatchReport, library: str, existing: Sequence[MappingRow]
) -> list[MappingRow]:
    """Rows for matches that are new, or that Zotero has since moved to a newer version."""
    current = {(r.record, r.item_key): r for r in mapping_mod.current_rows(existing, library)}
    rows: list[MappingRow] = []
    for match in report.matched:
        held = current.get((match.record_id, match.item.ref.key))
        if held is not None and held.item_version >= match.item.version:
            continue
        rows.append(
            MappingRow(
                record=match.record_id,
                library=library,
                item_key=match.item.ref.key,
                item_version=match.item.version,
                linked=held.linked if held is not None else _today(),
                via=held.via if held is not None else match.via,
            )
        )
    return rows


# ----------------------------------------------------------------------------------------- pull


@dataclass(frozen=True)
class PullResult:
    collection: Collection
    items_pulled: int
    #: Items that were already linked to a record and are therefore not imported again.
    already_linked: int
    records_created: int
    existing_records_appended: int
    rows_written: int
    amendments: tuple[Amendment, ...]
    rejected: tuple[RejectedRow, ...]
    unmatched: tuple[RemoteItem, ...]
    ambiguous: tuple[AmbiguousItem, ...]
    #: Linked items whose record has gone from the review.
    vanished: tuple[str, ...]
    import_id: str | None
    committed: bool
    notices: tuple[str, ...] = ()
    lock_reclaimed_from: int | None = None


def _clean_authors(authors: Any) -> list[dict[str, str]]:
    cleaned: list[dict[str, str]] = []
    for author in authors or []:
        if not isinstance(author, Mapping):
            continue
        entry = {
            k: str(v).strip() for k, v in author.items() if k in ("family", "given", "literal")
        }
        entry = {k: v for k, v in entry.items() if v}
        if entry:
            cleaned.append(entry)
    return cleaned


def _zotero_value(field_name: str, csl: Mapping[str, Any]) -> Any:
    """What Zotero says a field is, tidied as an import would tidy it; `None` if it says nothing."""
    value = csl.get(field_name)
    if field_name == "author":
        return _clean_authors(value) or None
    if field_name == "issued":
        return value if isinstance(value, Mapping) and value.get("date-parts") else None
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    normaliser = IDENTIFIER_NORMALISERS.get(field_name)
    if normaliser is not None:
        return normaliser(text) or text
    return text


def metadata_changes(record: Mapping[str, Any], csl: Mapping[str, Any]) -> list[FieldChange]:
    """The bibliographic fields on which Zotero differs from the record, as changes to make.

    Zotero wins conflicts over bibliographic metadata. It never *removes* a field: a Zotero entry
    that lacks an abstract the record has says nothing about the abstract, and taking it away
    would silently change what reviewers screen on. Removal is `strata fix`'s job.
    """
    changes: list[FieldChange] = []
    for field_name in BIBLIOGRAPHIC_FIELDS:
        new = _zotero_value(field_name, csl)
        if new is None:
            continue
        if canonical_json(record.get(field_name)) == canonical_json(new):
            continue
        changes.append(FieldChange(str(record["id"]), field_name, new))
    return changes


def _slug(text: str) -> str:
    return _SLUG_RE.sub("-", text.lower()).strip("-") or "collection"


def _write_pull_file(repo: Repo, collection: Collection, items: Sequence[RemoteItem]) -> Path:
    """The pulled items as the CSL-JSON file `strata import` reads, byte-for-byte reproducible:
    the same items give the same file, so pulling twice is recognised as one import."""
    ordered = sorted(items, key=lambda item: item.ref.key)
    directory = repo.path(".strata", "tmp")
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"zotero-{_slug(collection.name)}-{_today()}.json"
    path.write_text(canonical_json([item.csl for item in ordered]) + "\n", encoding="utf-8")
    return path


def pull(
    repo: Repo,
    *,
    actor: str,
    connector: Connector,
    collection: str,
    search_id: str | None = None,
    via: str | None = None,
    commit: bool = True,
    rationale: ops_mod.RationaleSource = None,
    lock_timeout: float = DEFAULT_LOCK_TIMEOUT,
) -> PullResult:
    """Pull a Zotero collection as an import source.

    A pull is an import: it needs exactly one of `search_id` (the collection holds the results of
    a recorded database search) and `via` (a hand-built collection, which PRISMA counts as another
    method rather than a database search), and the import manifest keeps the collection's name and
    the day it was pulled. Items already linked to a record are not imported again; they correct
    the record where Zotero's bibliographic metadata differs, each correction an ordinary
    `record-amend` event.
    """
    link_ = _require_link(repo)
    pipeline_mod.validate_source(repo, actor, search_id, via)
    ops_mod.check_rationale_up_front(repo, rationale, commit=commit, needed=False)
    connection = connector(link_.transport, False)
    pulled = connection.manager(link_.library).pull(collection)

    with repo_lock(repo, timeout=lock_timeout) as held:
        records = records_mod.read_records(repo)
        by_id = records_mod.index_by_id(records)
        absorbed = mapping_mod.absorbed_into(records)
        rows = mapping_mod.read_mapping(repo)
        linked = {r.item_key: r for r in mapping_mod.current_rows(rows, link_.library)}

        vanished: list[str] = []
        changes: list[FieldChange] = []
        refreshed: list[MappingRow] = []
        unlinked: list[RemoteItem] = []
        for item in pulled.items:
            row = linked.get(item.ref.key)
            target = mapping_mod.canonical_record_id(row.record, by_id, absorbed) if row else None
            if row is None:
                unlinked.append(item)
            elif target is None:
                vanished.append(item.ref.key)
            else:
                changes.extend(metadata_changes(by_id[target], item.csl))
                if row.item_version < item.version:
                    refreshed.append(
                        MappingRow(
                            row.record,
                            link_.library,
                            row.item_key,
                            item.version,
                            row.linked,
                            row.via,
                        )
                    )
        # A rerun that finds nothing new is not refused for want of a rationale it would not use.
        ops_mod.check_rationale_up_front(
            repo, rationale, commit=commit, needed=bool(changes or unlinked or refreshed)
        )
        amendments = tuple(records_mod.amend_fields(repo, changes, actor=actor, source="zotero"))

        outcome: pipeline_mod.ImportOutcome | None = None
        if unlinked:
            outcome = pipeline_mod.import_file(
                repo,
                _write_pull_file(repo, pulled.collection, unlinked),
                imported_by=actor,
                search_id=search_id,
                via=via,
                fmt="csl-json",
                collection={
                    "manager": "zotero",
                    "library": link_.library,
                    "key": pulled.collection.key,
                    "name": pulled.collection.name,
                },
            )

        after = RecordIndex(records_mod.read_records(repo))
        report = match_items(unlinked, after, review_threshold=None)
        new_rows = [
            MappingRow(m.record_id, link_.library, m.item.ref.key, m.item.version, _today(), m.via)
            for m in report.matched
        ]
        written = mapping_mod.append_rows(repo, [*refreshed, *new_rows])

        trailers: dict[str, str] = {"Collection": pulled.collection.key}
        if outcome is not None and not outcome.already_imported:
            trailers["Import"] = outcome.import_id
        committed = ops_mod.commit_domain_work(
            repo,
            op="zotero-pull",
            scope=pulled.collection.key,
            summary=f"pull {pulled.collection.name} from Zotero",
            actor=actor,
            extra_trailers=trailers,
            extra_paths=("imports",),
            commit=commit,
            rationale=rationale,
        )
    return PullResult(
        collection=pulled.collection,
        items_pulled=len(pulled.items),
        already_linked=len(pulled.items) - len(unlinked) - len(vanished),
        records_created=outcome.records_created if outcome else 0,
        existing_records_appended=outcome.existing_ids_appended if outcome else 0,
        rows_written=written,
        amendments=amendments,
        rejected=tuple(outcome.rejected) if outcome else (),
        unmatched=tuple(report.unmatched),
        ambiguous=tuple(report.ambiguous),
        vanished=tuple(vanished),
        import_id=outcome.import_id if outcome is not None else None,
        committed=committed,
        notices=connection.notices,
        lock_reclaimed_from=held.reclaimed_from,
    )


# ----------------------------------------------------------------------------------------- push


@dataclass(frozen=True)
class PushResult:
    collection: str
    outcomes: tuple[PushOutcome, ...]
    committed: bool
    notices: tuple[str, ...] = ()
    lock_reclaimed_from: int | None = None

    def count(self, status: str) -> int:
        return sum(1 for o in self.outcomes if o.status == status)


def _record_csl(record: Mapping[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in record.items() if k not in ("id", "strata")}


def pushable_records(repo: Repo, set_name: str) -> list[str]:
    """Ids of the records in a named set; only `included` exists."""
    if set_name not in PUSH_SETS:
        raise ZoteroOperationError(f"unknown set {set_name!r}; --set takes one of {PUSH_SETS}")
    final_stage = screening_mod.configured_stages(repo)[-1]
    return screening_mod.included_record_ids(repo, final_stage)


def push(
    repo: Repo,
    *,
    actor: str,
    connector: Connector,
    set_name: str,
    collection: str,
    commit: bool = True,
    rationale: ops_mod.RationaleSource = None,
    lock_timeout: float = DEFAULT_LOCK_TIMEOUT,
) -> PushResult:
    """Put a set of records in a Zotero collection, for citing while writing.

    Creates Zotero items for records Zotero lacks (recorded in the mapping as `created`) and adds
    items it already has to the collection. It never deletes, never removes an item from a
    collection, and never writes the bibliographic fields of an item that exists: Zotero wins on
    those. An item edited in Zotero since `strata` last saw it is refused and reported for that
    item alone.
    """
    link_ = _require_link(repo)
    if not link_.write:
        raise ZoteroOperationError(
            "this review's Zotero link cannot write; run `strata zotero link --web` with an API "
            "key that has write access"
        )
    ids = pushable_records(repo, set_name)
    ops_mod.check_rationale_up_front(repo, rationale, commit=commit, needed=bool(ids))
    connection = connector("web", True)
    if connection.key_info is not None and not connection.key_info.can_write(link_.library):
        raise ZoteroOperationError(
            f"the API key no longer has write access to {link_.library}; give it access at "
            "https://www.zotero.org/settings/keys and link again"
        )
    manager = connection.manager(link_.library, writable=True)

    with repo_lock(repo, timeout=lock_timeout) as held:
        records = records_mod.read_records(repo)
        by_id = records_mod.index_by_id(records)
        absorbed = mapping_mod.absorbed_into(records)
        rows = mapping_mod.read_mapping(repo)
        items: list[PushItem] = []
        row_of: dict[str, MappingRow | None] = {}
        for record_id in ids:
            row = mapping_mod.row_for_record(rows, link_.library, record_id, follow=absorbed)
            row_of[record_id] = row
            items.append(
                PushItem(
                    record_id=record_id,
                    csl=_record_csl(by_id[record_id]),
                    existing=ItemRef(link_.library, row.item_key) if row else None,
                    existing_version=row.item_version if row else None,
                    created_by_strata=bool(row and row.created_by_strata),
                )
            )
        outcomes = manager.push(items, collection) if items else []
        mapping_mod.append_rows(repo, _rows_after_push(outcomes, row_of, link_.library))
        committed = ops_mod.commit_domain_work(
            repo,
            op="zotero-push",
            scope=collection,
            summary=f"push {len(ids)} {set_name} record(s) to Zotero",
            actor=actor,
            commit=commit,
            rationale=rationale,
        )
    return PushResult(
        collection=collection,
        outcomes=tuple(outcomes),
        committed=committed,
        notices=connection.notices,
        lock_reclaimed_from=held.reclaimed_from,
    )


def _rows_after_push(
    outcomes: Sequence[PushOutcome], row_of: Mapping[str, MappingRow | None], library: str
) -> list[MappingRow]:
    rows: list[MappingRow] = []
    for outcome in outcomes:
        if outcome.ref is None or outcome.version is None:
            continue
        previous = row_of.get(outcome.record_id)
        if outcome.status == "created":
            rows.append(
                MappingRow(
                    outcome.record_id,
                    library,
                    outcome.ref.key,
                    outcome.version,
                    _today(),
                    mapping_mod.CREATED,
                )
            )
        elif outcome.status == "added" and previous is not None:
            # The version was checked equal to the one `strata` held before the write, so nothing
            # unseen changed; the write's own new version is safe to record.
            rows.append(
                MappingRow(
                    previous.record,
                    library,
                    outcome.ref.key,
                    outcome.version,
                    previous.linked,
                    previous.via,
                )
            )
    return rows


# --------------------------------------------------------------------------------------- status


@dataclass(frozen=True)
class StatusReport:
    library: str
    transport: str
    write: bool
    records: int
    mapped: int
    unmapped: tuple[str, ...]
    #: `(record, item key)` for links whose Zotero item no longer exists; `None` when Zotero could
    #: not be reached to find out.
    stale: tuple[tuple[str, str], ...] | None
    #: Links whose record is no longer in the review.
    orphaned: tuple[str, ...]
    unreachable: str | None = None
    notices: tuple[str, ...] = field(default_factory=tuple)


def status(repo: Repo, *, connector: Connector | None) -> StatusReport:
    """Which records are linked, which are not, and which links have gone stale.

    The counts come from the committed mapping alone and need no Zotero; staleness needs to ask
    Zotero, and when it cannot be reached that is said instead of guessed.
    """
    link_ = _require_link(repo)
    records = records_mod.read_records(repo)
    canonical = {str(r["id"]): r for r in records if r.get("strata", {}).get("canonical", True)}
    absorbed = mapping_mod.absorbed_into(records)
    rows = mapping_mod.current_rows(mapping_mod.read_mapping(repo), link_.library)

    mapped_ids: set[str] = set()
    orphaned: list[str] = []
    live_rows: list[tuple[str, MappingRow]] = []
    for row in rows:
        target = mapping_mod.canonical_record_id(row.record, canonical, absorbed)
        if target is None:
            orphaned.append(row.record)
            continue
        mapped_ids.add(target)
        live_rows.append((target, row))

    stale: tuple[tuple[str, str], ...] | None = None
    unreachable: str | None = None
    notices: tuple[str, ...] = ()
    if connector is not None and live_rows:
        try:
            connection = connector(link_.transport, False)
            resolved = connection.manager(link_.library).resolve(
                [ItemRef(link_.library, row.item_key) for _target, row in live_rows]
            )
            notices = connection.notices
            stale = tuple(
                (target, row.item_key)
                for target, row in live_rows
                if not resolved[row.item_key].present
            )
        except ReferenceManagerError as exc:
            unreachable = str(exc)
    elif not live_rows:
        stale = ()
    return StatusReport(
        library=link_.library,
        transport=link_.transport,
        write=link_.write,
        records=len(canonical),
        mapped=len(mapped_ids),
        unmapped=tuple(sorted(set(canonical) - mapped_ids)),
        stale=stale,
        orphaned=tuple(sorted(set(orphaned))),
        unreachable=unreachable,
        notices=notices,
    )


# ----------------------------------------------------------------------------------- opening


@dataclass(frozen=True)
class OpenTarget:
    record_id: str
    ref: ItemRef
    uri: str
    #: `attachment` opens the PDF; `item` selects the item in Zotero's library.
    kind: str


def open_target(repo: Repo, record_id: str, *, connector: Connector) -> OpenTarget:
    """Where `strata zotero open <record>` should send the person: the PDF if the item has one,
    else the item. A record with no Zotero item, or whose item was deleted, is an error that says
    so; it is never a reason to block screening."""
    link_ = _require_link(repo)
    records = records_mod.read_records(repo)
    absorbed = mapping_mod.absorbed_into(records)
    row = mapping_mod.row_for_record(
        mapping_mod.read_mapping(repo), link_.library, record_id, follow=absorbed
    )
    if row is None:
        raise NotLinkedError(
            f"{record_id} is not linked to a Zotero item; `strata zotero link` maps the records "
            "it can match, `strata zotero pull` brings new ones in"
        )
    ref = ItemRef(link_.library, row.item_key)
    connection = connector(link_.transport, False)
    manager = connection.manager(link_.library)
    resolution: Resolution = manager.resolve([ref])[row.item_key]
    if not resolution.present:
        raise StaleLinkError(
            f"full text unavailable: Zotero item {row.item_key} for {record_id} no longer exists; "
            "`strata zotero link` will map the record again if the paper is back in the library"
        )
    pdf = resolution.pdf
    if pdf is not None:
        return OpenTarget(record_id, ref, manager.open(ref, attachment=pdf.key), "attachment")
    return OpenTarget(record_id, ref, manager.open(ref), "item")
