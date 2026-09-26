# full-text-retrieval Specification

## Purpose

Obtaining the full texts of records promoted out of title/abstract screening,
recording each by identifier and version in a committed manifest, and reporting
the gap between reports sought and reports assessed.

## ADDED Requirements

### Requirement: Retrieval queue

`strata retrieve` MUST work the queue of reports sought for retrieval, offering
per report: I have the file, open the DOI in a browser, interlibrary loan
requested, not retrievable, and skip. Each outcome MUST be recorded as a
`retrieval` event.

_Source: `docs/spec/07-workflow-extraction.md` §1_

#### Scenario: Outstanding reports

- **GIVEN** 204 reports sought of which 196 are resolved
- **WHEN** `strata retrieve` runs
- **THEN** it reports 8 outstanding and presents them one at a time

### Requirement: Full-text manifest by identifier

Recording a retrieved document MUST append to `fulltext/manifest.ndjson` an
entry with `report`, `locator` (DOI, or PMID/PMCID/arXiv id/ISBN/URL where no
DOI exists), `version`, optional `path`, `retrieved`, `source`, and `actor`. The
manifest is committed; the file is not. `locator` is authoritative; `path` is a
local convenience with no guarantee.

_Source: `docs/spec/07-workflow-extraction.md` §1, §1.1_

#### Scenario: File obtained via institutional access

- **WHEN** a reviewer presses `f` for a report and supplies a local path
- **THEN** a manifest entry with the report's DOI as `locator` and `source: institutional-access` is appended and committed, and the PDF is not committed

### Requirement: Documents are never identified by content hash

`strata` MUST NOT require or depend on a content hash of a retrieved file. A
`sha256` MAY be recorded as advisory metadata; a mismatch MUST NOT be treated as
an error, MUST NOT produce a warning, and MUST NOT be used to decide whether two
reviewers saw the same document.

_Source: `docs/spec/07-workflow-extraction.md` §1.1_

#### Scenario: Annotated copies

- **GIVEN** two reviewers' manifest entries for the same DOI with different `sha256` values
- **WHEN** `strata verify` runs
- **THEN** no error or warning is reported about the difference

### Requirement: Document versions

The manifest MUST distinguish document versions by `version` (`preprint`,
`accepted-manuscript`, `version-of-record`, `corrected`, `retracted`, `unknown`),
with `locator` being the identifier of that version and optional `related`
identifiers of other versions.

_Source: `docs/spec/07-workflow-extraction.md` §1.1_

#### Scenario: Preprint and version of record

- **WHEN** one reviewer assessed the preprint and another the version of record
- **THEN** their manifest entries carry different `version` values and different `locator` DOIs

### Requirement: Not-retrieved reasons

Marking a report not retrievable MUST require a reason from the fixed vocabulary
`no-access`, `not-found`, `retracted`, `language`, `no-response-from-author`,
`other` (with free text). These reasons MUST populate the "Reports not
retrieved" box of the flow diagram.

_Source: `docs/spec/07-workflow-extraction.md` §1_

#### Scenario: Author did not respond

- **WHEN** a report is marked not retrievable with reason `no-response-from-author`
- **THEN** it is counted in "Reports not retrieved" and its full-text state is `not-retrieved`

### Requirement: Legal open-access links only

With enrichment enabled, `strata` MAY query Unpaywall for a legal open-access
copy and offer the link. It MUST NOT download anything automatically and MUST
NOT touch Sci-Hub or comparable sources.

_Source: `docs/spec/07-workflow-extraction.md` §1_

#### Scenario: Open-access copy available

- **WHEN** Unpaywall reports an open-access copy for a report
- **THEN** the link is offered and nothing is downloaded
