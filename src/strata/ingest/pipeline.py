"""`strata import`: turn a bibliographic export file into records.

Implements openspec:literature-import#what-import-does -- copy the file unmodified,
parse it, normalise and assign ids, append to an existing record's sources on
an exact-id match rather than duplicating it, write the import manifest, emit
`import`/`record-add` events, and regenerate `records/records.ndjson`.

Import is idempotent by file digest (openspec:literature-import#what-import-does): re-importing the
same bytes finds
the earlier `imports/<id>/manifest.yaml` and makes no changes, reporting that
rather than silently repeating the import.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from strata.core import manifest as manifest_mod
from strata.core import records as records_mod
from strata.core.canon import canonical_json, dump_yaml_str, load_yaml_str
from strata.core.events import append_new_event, append_new_events
from strata.core.ids import (
    assign_record_id,
    new_import_id,
    normalise_doi,
    normalise_isbn,
    normalise_pmcid,
    normalise_pmid,
)
from strata.core.repo import Repo
from strata.core.validate import validate
from strata.ingest.parsers import ParseResult, RejectedRow, decode_bytes, normalise_newlines
from strata.ingest.parsers import bibtex as bibtex_parser
from strata.ingest.parsers import citation_list as citation_list_parser
from strata.ingest.parsers import csl_json as csl_json_parser
from strata.ingest.parsers import csv_tsv as csv_tsv_parser
from strata.ingest.parsers import endnote_xml as endnote_xml_parser
from strata.ingest.parsers import medline as medline_parser
from strata.ingest.parsers import ris as ris_parser
from strata.ingest.parsers import xlsx as xlsx_parser
from strata.ingest.profiles import detect_profile
from strata.protocol import searches as searches_mod

IMPORTS_DIR = ("imports",)

# Set on every record from a parser that infers its fields (openspec:literature-import); the
# deduplication pass leaves such a record for a person instead of merging it.
BEST_EFFORT_FLAG = "best-effort-parse"

VALID_VIA = frozenset({"citation-searching", "website", "organisation", "registry", "contact"})

_PARSERS = {
    "csl-json": csl_json_parser.parse,
    "ris": ris_parser.parse,
    "bibtex": bibtex_parser.parse,
    "medline": medline_parser.parse,
    "endnote-xml": endnote_xml_parser.parse,
    "citation-list": citation_list_parser.parse,
}

# CSV/TSV are handled separately (see `_parse_csv_like`): they need a column
# mapping resolved from the header row before `csv_tsv_parser.parse` can run,
# so they don't fit the uniform `parse(text) -> ParseResult` shape above.
_CSV_LIKE_DELIMITERS = {"csv": ",", "tsv": "\t"}

_EXTENSION_FORMATS = {
    ".json": "csl-json",
    ".ris": "ris",
    ".bib": "bibtex",
    ".nbib": "medline",
    ".csv": "csv",
    ".tsv": "tsv",
    ".xml": "endnote-xml",
    ".xlsx": "xlsx",
}

# `.txt` is ambiguous (RIS, MEDLINE, and PRISMA-text exports all use it, per
# openspec:literature-import's table) so it is sniffed by content
# rather than mapped by extension.
_MEDLINE_SNIFF_PREFIX = "PMID"
_RIS_SNIFF_PREFIX = "TY"
_NUMBERED_ENTRY_RE = re.compile(r"^(?:\[\d{1,5}\]|\d{1,5}[.)])\s+\S")


class ImportPipelineError(ValueError):
    pass


@dataclass
class ImportOutcome:
    import_id: str
    already_imported: bool
    dry_run: bool
    format: str
    encoding: str
    rows_read: int
    records_created: int
    rows_rejected: int
    existing_ids_appended: int
    rejected: list[RejectedRow] = field(default_factory=list)
    nondeterministic_rows: list[int] = field(default_factory=list)
    column_mapping: dict[str, str] | None = None


def imports_dir(repo: Repo) -> Path:
    return repo.path(*IMPORTS_DIR)


def import_manifest_path(repo: Repo, import_id: str) -> Path:
    return imports_dir(repo) / import_id / "manifest.yaml"


def list_import_manifests(repo: Repo) -> list[dict[str, Any]]:
    """All import manifests, sorted by id (which is a ULID, so this is chronological)."""
    if not imports_dir(repo).exists():
        return []
    results = []
    for manifest_path in sorted(imports_dir(repo).glob("*/manifest.yaml")):
        data = load_yaml_str(manifest_path.read_text(encoding="utf-8"))
        if data:
            results.append(dict(data))
    return sorted(results, key=lambda m: str(m["id"]))


def file_digest(raw: bytes) -> str:
    """The digest an import is identified by: `sha256:` and the hex of the file's bytes."""
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def find_import_by_digest(repo: Repo, digest: str) -> dict[str, Any] | None:
    for manifest_data in list_import_manifests(repo):
        if manifest_data.get("digest") == digest:
            return manifest_data
    return None


def find_import_by_file(repo: Repo, source_path: str | Path) -> dict[str, Any] | None:
    """The earlier import of exactly this file's bytes, or `None` (also for an unreadable file)."""
    try:
        raw = Path(source_path).read_bytes()
    except OSError:
        return None
    return find_import_by_digest(repo, file_digest(raw))


def detect_format(path: Path, text: str) -> str:
    """Map a file to a parser, by extension where unambiguous and by content for `.txt`."""
    ext = path.suffix.lower()
    if ext in _EXTENSION_FORMATS:
        return _EXTENSION_FORMATS[ext]
    if ext == ".txt":
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith(_MEDLINE_SNIFF_PREFIX):
                return "medline"
            if stripped.startswith(_RIS_SNIFF_PREFIX):
                return "ris"
            if _NUMBERED_ENTRY_RE.match(stripped):
                return "citation-list"
            break
        raise ImportPipelineError(
            f"cannot determine the format of {path.name!r} from its contents; "
            "pass --format (ris, medline, or citation-list for a plain-text reference list)"
        )
    raise ImportPipelineError(f"unsupported file extension {ext!r}; pass --format explicitly")


def _apply_identifier_normalisation(record: dict[str, Any]) -> None:
    """openspec:data-schemas#record-schema-is-csl-json-plus-a-namespaced-extension --
    DOI/PMID/PMCID/ISBN are normalised per openspec:record-identity#normalisation-rules on storage.

    A value that fails to normalise (not DOI-shaped, no digits) is left as
    parsed rather than dropped: strata never silently discards metadata, it
    simply plays no role in identity (`canonical_key` re-derives the same
    normalisation independently for that purpose).
    """
    for field_name, normaliser in (
        ("DOI", normalise_doi),
        ("PMID", normalise_pmid),
        ("PMCID", normalise_pmcid),
        ("ISBN", normalise_isbn),
    ):
        if field_name in record:
            normalised = normaliser(record[field_name])
            if normalised:
                record[field_name] = normalised


def _write_rejected(path: Path, rejected: list[RejectedRow]) -> None:
    blocks = []
    for row in rejected:
        location = f"line {row.line}" if row.line is not None else "location unknown"
        blocks.append(f"--- {location}: {row.error} ---\n{row.raw}\n")
    path.write_text("\n".join(blocks), encoding="utf-8")


def _resolve_csv_mapping(
    resolved_format: str, text: str, mapping: dict[str, str] | None
) -> dict[str, str]:
    """An explicit `--map` wins (strict: a named column absent from the header is an error,
    almost always a typo). Otherwise, detect a known platform by its header row and use only
    the fields *this* export actually has -- a profile lists every column a platform might
    emit, not the ones a particular export was configured to include.
    """
    if mapping is not None:
        return mapping
    delimiter = _CSV_LIKE_DELIMITERS[resolved_format]
    header = csv_tsv_parser.read_header(text, delimiter=delimiter)
    profile = detect_profile(header)
    if profile is None:
        raise ImportPipelineError(
            "could not detect a known export platform from this file's header row "
            f"({header!r}); pass --map title=<column>,author=<column>,..."
        )
    header_columns = set(header)
    return {field: column for field, column in profile.mapping.items() if column in header_columns}


def sniff_format(source_path: str | Path, *, fmt: str | None = None) -> str:
    """The format `import_file` would take this file to be: nothing is parsed or written.

    For a surface that wants to turn a file away at the door with the reason `strata import` would
    give, from the same detection.
    """
    path = Path(source_path)
    if not path.is_file():
        raise ImportPipelineError(f"no such file: {path}")
    if fmt == "xlsx" or (fmt is None and path.suffix.lower() == ".xlsx"):
        return "xlsx"
    text, _encoding = decode_bytes(path.read_bytes())
    return fmt or detect_format(path, normalise_newlines(text))


@dataclass(frozen=True)
class _Source:
    """A file's bytes as the parsers see them: text, how it was decoded and which format it is."""

    text: str
    encoding: str
    resolved_format: str  # what the import manifest records (`xlsx`, not `tsv`)
    parse_format: str  # what picks the parser (a workbook's sheet is parsed as `tsv`)
    sheet_name: str | None


def _read_source(raw: bytes, source_path: Path, *, fmt: str | None, sheet: str | None) -> _Source:
    if fmt == "xlsx" or (fmt is None and source_path.suffix.lower() == ".xlsx"):
        # A workbook is not text: read its sheet, then treat the sheet as the TSV export it is.
        try:
            sheet_name, rows = xlsx_parser.read_rows(raw, sheet)
        except xlsx_parser.XlsxError as exc:
            raise ImportPipelineError(f"{source_path.name}: {exc}") from None
        return _Source(xlsx_parser.rows_to_tsv(rows), "xlsx", "xlsx", "tsv", sheet_name)
    if sheet is not None:
        raise ImportPipelineError("--sheet only applies to an .xlsx workbook")
    text, encoding = decode_bytes(raw)
    text = normalise_newlines(text)
    resolved_format = fmt or detect_format(source_path, text)
    return _Source(text, encoding, resolved_format, resolved_format, None)


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
) -> ImportOutcome:
    source_path = Path(source_path)
    if not source_path.is_file():
        raise ImportPipelineError(f"no such file: {source_path}")
    if (search_id is None) == (via is None):
        raise ImportPipelineError("exactly one of --search or --via is required")
    if via is not None and via not in VALID_VIA:
        raise ImportPipelineError(f"invalid --via {via!r}; must be one of {sorted(VALID_VIA)}")

    manifest_doc = manifest_mod.load_manifest_doc(repo.root)
    if manifest_mod.find_actor(manifest_doc, imported_by) is None:
        raise ImportPipelineError(f"imported_by {imported_by!r} is not a configured actor")
    search_record: dict[str, Any] | None = None
    if search_id is not None:
        search_record = searches_mod.get_search(repo, search_id)
        if search_record is None:
            raise ImportPipelineError(f"unknown search {search_id!r}")

    raw = source_path.read_bytes()
    digest = file_digest(raw)

    existing = find_import_by_digest(repo, digest)
    if existing is not None:
        return ImportOutcome(
            import_id=str(existing["id"]),
            already_imported=True,
            dry_run=dry_run,
            format=str(existing["format"]),
            encoding=str(existing["encoding"]),
            rows_read=int(existing["rows_read"]),
            records_created=0,
            rows_rejected=int(existing["rows_rejected"]),
            existing_ids_appended=0,
            column_mapping=existing.get("column_mapping"),
        )

    source = _read_source(raw, source_path, fmt=fmt, sheet=sheet)
    text, encoding = source.text, source.encoding
    resolved_format, parse_format, sheet_name = (
        source.resolved_format,
        source.parse_format,
        source.sheet_name,
    )

    resolved_mapping: dict[str, str] | None = None
    parsed: ParseResult
    if parse_format in _CSV_LIKE_DELIMITERS:
        resolved_mapping = _resolve_csv_mapping(parse_format, text, mapping)
        try:
            parsed = csv_tsv_parser.parse(
                text, delimiter=_CSV_LIKE_DELIMITERS[parse_format], mapping=resolved_mapping
            )
        except csv_tsv_parser.ColumnMappingError as exc:
            raise ImportPipelineError(str(exc)) from None
    else:
        parser = _PARSERS.get(resolved_format)
        if parser is None:
            raise ImportPipelineError(f"unsupported format {resolved_format!r}")
        parsed = parser(text)

    import_id = new_import_id()
    by_id = records_mod.index_by_id(records_mod.read_records(repo))
    existing_ids_appended = 0
    new_records: list[tuple[str, dict[str, Any]]] = []
    nondeterministic_rows: list[int] = []

    for row_number, raw_record in enumerate(parsed.records, start=1):
        record = dict(raw_record)
        _apply_identifier_normalisation(record)
        rid, key, deterministic = assign_record_id(record)
        if not deterministic:  # pragma: no cover - unreachable while every parser rejects
            # a title-less record before it reaches this loop (see has_title()
            # in strata.ingest.parsers); kept as a defensive flag per
            # openspec:record-identity priority 7 in case a future
            # parser ever admits one.
            nondeterministic_rows.append(row_number)
        source_entry: dict[str, Any] = {
            "import": import_id,
            "row": row_number,
            "retrieved": date.today().isoformat(),
        }
        if search_id is not None:
            source_entry["search"] = search_id
        if search_record is not None:
            # `database`/`platform` are both required by the search schema,
            # so always present here. `strata.dedup.merge`'s source_trust
            # ranking matches against either field, since `[dedup]
            # source_trust` mixes database-like names (pubmed, embase) and
            # platform/interface names (scopus, wos, ebsco) -- the spec's
            # own example list does the same.
            source_entry["database"] = str(search_record["database"]).lower()
            source_entry["platform"] = str(search_record["platform"]).lower()
        if via is not None:
            source_entry["via"] = via

        if rid in by_id:
            by_id[rid]["strata"]["sources"].append(source_entry)
            existing_ids_appended += 1
            continue

        record["id"] = rid
        record["strata"] = {"canonical_key": key, "canonical": True, "sources": [source_entry]}
        if parsed.best_effort:
            record["strata"]["flags"] = [BEST_EFFORT_FLAG]
        by_id[rid] = record
        new_records.append((rid, raw_record))

    outcome = ImportOutcome(
        import_id=import_id,
        already_imported=False,
        dry_run=dry_run,
        format=resolved_format,
        encoding=encoding,
        rows_read=len(parsed.records) + len(parsed.rejected),
        records_created=len(new_records),
        rows_rejected=len(parsed.rejected),
        existing_ids_appended=existing_ids_appended,
        rejected=parsed.rejected,
        nondeterministic_rows=nondeterministic_rows,
        column_mapping=resolved_mapping,
    )
    if dry_run:
        return outcome

    records_mod.write_records(repo, list(by_id.values()))

    import_dir = imports_dir(repo) / import_id
    (import_dir / "raw").mkdir(parents=True, exist_ok=True)
    (import_dir / "raw" / source_path.name).write_bytes(raw)
    if parsed.rejected:
        _write_rejected(import_dir / "rejected.txt", parsed.rejected)

    manifest_data: dict[str, Any] = {
        "id": import_id,
        "search": search_id,
        "via": via,
        "source_file": source_path.name,
        "digest": digest,
        "format": resolved_format,
        "encoding": encoding,
        "column_mapping": resolved_mapping,
        **({"sheet": sheet_name} if sheet_name is not None else {}),
        "rows_read": outcome.rows_read,
        "records_created": outcome.records_created,
        "rows_rejected": outcome.rows_rejected,
        "existing_ids_appended": outcome.existing_ids_appended,
        "imported": date.today().isoformat(),
        "imported_by": imported_by,
    }
    validate("import-manifest", manifest_data)
    import_manifest_path(repo, import_id).write_text(dump_yaml_str(manifest_data), encoding="utf-8")

    events_path = repo.path("events", "import", f"{imported_by}.ndjson")
    record_add_entries = []
    for record_id, raw_record in new_records:
        raw_row_digest = (
            "sha256:" + hashlib.sha256(canonical_json(raw_record).encode("utf-8")).hexdigest()
        )
        record_add_entries.append(
            (
                "record-add",
                imported_by,
                {"record": record_id, "import_id": import_id, "raw_row_digest": raw_row_digest},
            )
        )
    # `append_new_events`, not `append_new_event` per record: the latter
    # re-reads the whole (growing) events file on every call, which turns an
    # O(n)-record import into an O(n^2) one at scale -- see that function's
    # docstring.
    append_new_events(events_path, record_add_entries)
    append_new_event(
        events_path,
        ev="import",
        actor=imported_by,
        body={
            "import_id": import_id,
            "search_id": search_id,
            "source": source_path.name,
            "count": outcome.records_created,
            "file_digest": digest,
        },
    )

    return outcome


class MappingSyntaxError(ValueError):
    """A column mapping that is not a comma-separated list of `field=Column`."""


def parse_mapping(raw: str) -> dict[str, str]:
    """`title=Article Title,doi=DOI` -> `{"title": "Article Title", "doi": "DOI"}`.

    openspec:literature-import#csv-column-mapping's own example uses exactly this comma-separated
    `field=Column Name` syntax; a column name containing a literal comma is not expressible this
    way, a known limitation. Which fields are valid is the CSV parser's to say, not this
    function's.
    """
    mapping: dict[str, str] = {}
    for pair in raw.split(","):
        if "=" not in pair:
            raise MappingSyntaxError(f"entry {pair!r} is not of the form field=Column")
        field_name, column = pair.split("=", 1)
        mapping[field_name.strip()] = column.strip()
    return mapping


#: The fields a column mapping can target, for a surface that offers the choice.
MAPPABLE_FIELDS: tuple[str, ...] = tuple(sorted(csv_tsv_parser.FIELDS))


@dataclass(frozen=True)
class TableLayout:
    """What a spreadsheet-like export looks like before it is imported (nothing is written)."""

    format: str  # csv | tsv | xlsx
    columns: list[str]  # the header row
    platform: str | None  # the platform whose export these columns match, if any
    detected_mapping: dict[str, str] | None  # the mapping that platform implies
    sheets: list[str] | None  # a workbook's sheet names, in order
    sheet: str | None  # the sheet `columns` were read from


def describe_table(
    source_path: str | Path, *, fmt: str | None = None, sheet: str | None = None
) -> TableLayout | None:
    """The header and recognised platform of a CSV, TSV or workbook, or `None` for any other format.

    Read-only, and decided by the same code as `import_file`, so a surface that offers a column or
    sheet choice cannot disagree with the import about what the file is.
    """
    path = Path(source_path)
    if not path.is_file():
        raise ImportPipelineError(f"no such file: {path}")
    raw = path.read_bytes()
    source = _read_source(raw, path, fmt=fmt, sheet=sheet)
    delimiter = _CSV_LIKE_DELIMITERS.get(source.parse_format)
    if delimiter is None:
        return None
    sheets: list[str] | None = None
    if source.resolved_format == "xlsx":
        try:
            sheets = xlsx_parser.sheet_names(raw)
        except xlsx_parser.XlsxError as exc:
            raise ImportPipelineError(f"{path.name}: {exc}") from None
    columns = csv_tsv_parser.read_header(source.text, delimiter=delimiter)
    profile = detect_profile(columns)
    detected = None
    if profile is not None:
        present = set(columns)
        detected = {f: c for f, c in profile.mapping.items() if c in present}
    return TableLayout(
        format=source.resolved_format,
        columns=columns,
        platform=profile.name if profile is not None else None,
        detected_mapping=detected,
        sheets=sheets,
        sheet=source.sheet_name,
    )
