# literature-import Specification

## Purpose

Getting literature into a review: recording each executed search verbatim,
importing database exports through tolerant parsers and CSV mapping profiles,
and doing so idempotently with full provenance, including records found through
methods other than database searching.

Rationale: `docs/spec/05-workflow-import.md` §1–§2.

## Requirements

### Requirement: Recording a search

`strata search add` MUST record the search that produced an export in
`protocol/searches/<id>.yaml` before import. It MUST NOT let the user skip the
query string: if the query is not to hand, `strata` records
`query: "PENDING"` and `strata status` MUST report it as an outstanding
requirement (PRISMA item 7) until supplied.

Where an export format carries the query, `strata import` MUST offer to
pre-fill it and MUST show the user what it extracted for confirmation rather
than accepting it silently.

_Source: `docs/spec/05-workflow-import.md` §1_

#### Scenario: Query not available yet

- **WHEN** a search is recorded without its query string
- **THEN** the search file has `query: "PENDING"`
- **AND** `strata status` flags the search as missing its query, citing PRISMA item 7

#### Scenario: Export carries the query

- **GIVEN** an Ovid export that embeds its search strategy
- **WHEN** it is imported
- **THEN** the extracted query is shown to the user for confirmation before it is recorded

### Requirement: Supported import formats

`strata import` MUST support these formats:

| Format | Extensions | Notes |
|---|---|---|
| RIS | `.ris`, `.txt` | Tag-per-line; both `TY  - ` and `TY - ` spacing |
| PubMed / MEDLINE | `.nbib`, `.txt` | `PMID- `, `TI  - `, continuation lines indented six spaces |
| BibTeX | `.bib` | Brace-balanced; preserve `@misc` and unknown fields |
| EndNote XML | `.xml` | `<records><record>` with style-nested text nodes |
| CSL-JSON | `.json` | Round-trips losslessly; the native format |
| CSV / TSV | `.csv`, `.tsv` | Platform-specific column mapping |
| Excel | `.xlsx` | Read-only; first sheet unless `--sheet` given |
| PRISMA-style citation list | `.txt` | Best-effort; always routed to manual review |

_Source: `docs/spec/05-workflow-import.md` §2.1_

#### Scenario: RIS with single-space tag separator

- **WHEN** a RIS file using `TY - JOUR` spacing is imported
- **THEN** its records parse the same as with `TY  - JOUR` spacing

#### Scenario: BibTeX with unknown fields

- **WHEN** a `@misc` BibTeX entry with a non-standard field is imported
- **THEN** the entry is imported and the unknown field is preserved

### Requirement: Tolerant parsing

Parsers MUST tolerate the malformations real platforms emit: a BOM at start of
file, CRLF and CR line endings, unescaped `&` in EndNote XML, RIS records
missing `ER  -`, non-UTF-8 encodings (try UTF-8, then UTF-8 with BOM, then
CP1252, then Latin-1, recording which was used in the manifest), and HTML
entities in titles and abstracts.

A row that cannot be parsed MUST NOT abort the import: it is written verbatim to
`imports/<id>/rejected.txt` with the parse error and a line number, counted in
the manifest, and reported.

_Source: `docs/spec/05-workflow-import.md` §2.1_

#### Scenario: CP1252 export

- **WHEN** a CP1252-encoded RIS file with smart quotes is imported
- **THEN** the titles decode correctly and the manifest records `CP1252` as the encoding

#### Scenario: One malformed row among many

- **GIVEN** an export of 500 rows where one row cannot be parsed
- **WHEN** it is imported
- **THEN** 499 records are imported, the bad row is written to `rejected.txt` with its line number and error, and the rejection is reported

### Requirement: CSV column mapping

Because CSV exports vary by platform and user configuration, `strata` MUST:

1. Ship detection profiles for common exports (EBSCOhost, Scopus, Web of
   Science, ProQuest, Dimensions, Google Scholar via Publish or Perish),
   matched by header signature.
2. On an unrecognised header row, present an interactive mapping UI or accept
   `--map title=Article Title,doi=DOI,...`.
3. Save the resolved mapping to `imports/<id>/manifest.yaml` and offer to reuse
   it for the next import with the same signature.

_Source: `docs/spec/05-workflow-import.md` §2.2_

#### Scenario: Scopus CSV

- **WHEN** a Scopus CSV export is imported
- **THEN** the Scopus profile is detected from its header row and applied without prompting

#### Scenario: Unknown CSV header

- **WHEN** a CSV with an unrecognised header is imported with `--map title=Article Title,doi=DOI`
- **THEN** the mapping is applied and saved in the import manifest

### Requirement: What import does

`strata import <file> --search <id>` MUST:

1. Copy the file unmodified to `imports/<import-id>/raw/` and record its sha256.
2. Parse it into records and apply normalisation.
3. Compute record ids and emit `record-add` events.
4. For an id already present, append to `strata.sources` rather than creating a
   duplicate row — an exact-id match is a same-record re-import, not a dedup
   candidate.
5. Write `imports/<id>/manifest.yaml`: source file, digest, parser, encoding
   detected, rows read, records created, rows rejected, column mapping, search id.
6. Emit an `import` event, regenerate derived views, and commit.

_Source: `docs/spec/05-workflow-import.md` §2.3_

#### Scenario: Paper already present from another database

- **GIVEN** a record with DOI `10.1111/j.1467-9280.2008.02209.x` imported from MEDLINE
- **WHEN** an Embase export containing the same DOI is imported
- **THEN** no new record row is created and the existing record gains a second `strata.sources` entry

#### Scenario: Raw file preserved

- **WHEN** an export is imported
- **THEN** a byte-identical copy exists under `imports/<import-id>/raw/` and its sha256 is in the manifest

### Requirement: Idempotent import

Importing the same file twice MUST create no new records and no second `import`
event (detected by file digest), and MUST say so rather than appearing to
succeed silently.

_Source: `docs/spec/05-workflow-import.md` §2.3_

#### Scenario: Re-importing a file

- **WHEN** a file already imported is imported again
- **THEN** no records, events, or commits are created
- **AND** the user is told the file was already imported

### Requirement: Records from other sources

`strata import --via citation-searching | website | organisation | registry | contact`
MUST tag records accordingly, and those tags MUST flow through to the "other
methods" column of the PRISMA flow diagram. Citation chasing results MAY be
imported as a normal export with `--via citation-searching`; `strata` v1 does
not perform the chasing itself.

_Source: `docs/spec/05-workflow-import.md` §2.4_

#### Scenario: Citation-chased records

- **WHEN** an export is imported with `--via citation-searching`
- **THEN** its records are tagged `citation-searching` and counted in the other-methods column
