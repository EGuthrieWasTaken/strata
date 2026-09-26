# copyright-and-licensing Specification

## Purpose

`strata`'s legal posture around copyrighted full texts, unauthorised sources,
database terms of service, third-party content in generated output, and the
licensing of the tool, its format specification, and its test fixtures.

Rationale: `docs/spec/13-nonfunctional.md` §6, §9.

## Requirements

### Requirement: Full texts are not committed

`.gitignore` MUST exclude `fulltext/` (except its manifest), and `strata` MUST
refuse to `git add` a PDF from that directory without an explicit override.

_Source: `docs/spec/13-nonfunctional.md` §6_

#### Scenario: Staging a PDF

- **GIVEN** `fulltext/cepeda-2008.pdf` exists
- **WHEN** a `strata` operation stages files
- **THEN** the PDF is not staged

### Requirement: Identifiers, not files

Full-text provenance MUST be preserved in `fulltext/manifest.ndjson` by DOI or
equivalent identifier, without redistributing the document; content hashes MUST
NOT be used to establish document identity.

_Source: `docs/spec/13-nonfunctional.md` §6_

#### Scenario: Two reviewers with differently annotated copies

- **GIVEN** two reviewers hold copies of the same article with different annotations
- **WHEN** their manifests are compared
- **THEN** both are recorded as the same document by identifier

### Requirement: No unauthorised sources or scraping

`strata` MUST NOT retrieve articles from unauthorised sources (no Sci-Hub, no
LibGen, no institutional-proxy credential handling); Unpaywall integration is
limited to surfacing links to legally open copies. `strata` MUST NOT scrape or
automate queries against subscription databases; it consumes their exports.

_Source: `docs/spec/13-nonfunctional.md` §6; `docs/spec/00-overview.md` §4 (N1)_

#### Scenario: Open-access lookup

- **GIVEN** enrichment with Unpaywall enabled
- **WHEN** a report has a legal open-access copy
- **THEN** `strata` offers the link and downloads nothing automatically

### Requirement: Attribution in generated output

Generated diagrams and checklists derived from PRISMA materials MUST carry the
CC BY 4.0 attribution. The terms of RoB 2 and ROBINS-I MUST be checked and
documented before shipping those instrument definitions. `strata export package`
MUST include the review data licence declared in `project.license`.

_Source: `docs/spec/13-nonfunctional.md` §6_

#### Scenario: Flow diagram

- **WHEN** a PRISMA flow diagram is generated
- **THEN** it includes the PRISMA 2020 CC BY 4.0 attribution

### Requirement: Licences

`strata` itself MUST be licensed GNU GPL v3.0 or later. Test fixtures derived
from published datasets MUST retain their original licences and MUST be
attributed in `tests/fixtures/SOURCES.md`. The licence of the repository-format
specification is an open decision (see `docs/spec/16-open-questions.md` Q2).

_Source: `docs/spec/13-nonfunctional.md` §9_

#### Scenario: New fixture from a published dataset

- **WHEN** a fixture derived from a published dataset is added
- **THEN** `tests/fixtures/SOURCES.md` attributes it with its licence
