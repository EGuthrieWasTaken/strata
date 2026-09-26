# record-identity Specification

## Purpose

Deterministic, permanent identifiers for records and the other review entities,
the exact normalisation rules those identifiers and deduplication depend on,
and the alias map that keeps every id that ever existed resolvable. Determinism
is what lets two collaborators import the same export on different machines and
produce byte-identical files that merge without conflict.

Rationale and worked examples: [design.md](design.md).

## Requirements

### Requirement: Canonical key ladder

On import, the system MUST compute a record's canonical key from the first
available source, in this priority order:

| Priority | Source | Canonical key form |
|---|---|---|
| 1 | DOI | `doi:` + normalised DOI |
| 2 | PubMed ID | `pmid:` + digits |
| 3 | PMC ID | `pmcid:PMC` + digits |
| 4 | arXiv ID | `arxiv:` + normalised id |
| 5 | ISBN (books) | `isbn:` + digits, check digit normalised |
| 6 | Fallback | `sig:` + normalised title + `\|` + year + `\|` + normalised first-author family name |
| 7 | Last resort (no title) | `ulid:` + a fresh ULID |

Priority 7 is the only non-deterministic branch and MUST emit a warning naming
the offending import row.

#### Scenario: Record with DOI and PMID

- **WHEN** a record carrying both a DOI and a PMID is imported
- **THEN** its canonical key is `doi:` plus the normalised DOI

#### Scenario: Record with no identifiers and no title

- **WHEN** a row with no DOI, PMID, PMCID, arXiv id, ISBN, or title is imported
- **THEN** its canonical key is `ulid:` plus a fresh ULID
- **AND** a warning names the import row

### Requirement: Record id derivation

The record id MUST be computed as
`"rec_" + base32_crockford(sha256(canonical_key)[0:10]).lower()` (16 characters
after the prefix), e.g. `rec_3kq8v1r0zx2m4a7b`. The same input record MUST yield
the same id regardless of import order, source file, or platform.

#### Scenario: Same paper imported on two machines

- **GIVEN** two collaborators import the same Scopus export independently
- **WHEN** ids are computed on each machine
- **THEN** every record receives the same id on both machines

### Requirement: Identifiers are permanent

A record id is a name, not a checksum. Correcting a record's DOI after import
MUST NOT change its id; it creates an alias instead.

#### Scenario: DOI corrected after import

- **GIVEN** record `rec_3kq8v1r0zx2m4a7b` was imported with a mistyped DOI
- **WHEN** the DOI is corrected with `strata fix`
- **THEN** the record keeps id `rec_3kq8v1r0zx2m4a7b`

### Requirement: Normalisation rules

Normalisation MUST be implemented exactly as follows; any change to these rules
is a breaking format change governed by format versioning:

- **DOI**: strip a leading `https://doi.org/`, `http://dx.doi.org/`, `doi:` or
  `DOI:` (case-insensitive); strip surrounding whitespace and a single trailing
  `.`, `,`, `;`, or `)`; lowercase. A value not matching `^10\.\d{4,9}/\S+$` is
  not a DOI and MUST be ignored for identity purposes.
- **Title**: decode HTML entities and strip inline markup first; Unicode NFKD
  normalise; strip combining marks; lowercase; replace any run of characters
  outside `[a-z0-9]` with a single space; trim.
- **Author family name**: as Title, additionally stripping a leading particle
  (`van`, `von`, `de`, `del`, `della`, `da`, `di`, `du`, `la`, `le`, `ter`,
  `ten`, `al`, `bin`, `ibn`), retaining both stripped and unstripped forms as
  blocking alternates.
- **Year**: 4-digit integer; from a range or season take the first 4-digit
  number in `[1400, current_year + 2]`.
- **Pages**: the first integer run.
- **Journal / container title**: as Title, plus whole-token expansion from a
  shipped abbreviation table (`j` to `journal`, `psychol` to `psychology`, ...).

Normalisation MUST be idempotent: `normalise(normalise(s)) == normalise(s)`.

#### Scenario: DOI with URL prefix and trailing punctuation

- **WHEN** the DOI `https://doi.org/10.1111/J.1467-9280.2008.02209.X.` is normalised
- **THEN** the result is `10.1111/j.1467-9280.2008.02209.x`

#### Scenario: Non-DOI string in DOI field

- **WHEN** a DOI field contains `n/a`
- **THEN** it is ignored for identity and the next rung of the ladder is used

#### Scenario: Title with diacritics and markup

- **WHEN** the title `<i>Über</i> spacing &amp; retention` is normalised
- **THEN** the result is `uber spacing retention`

#### Scenario: Leading author particle

- **WHEN** the family name `van der Berg` is normalised
- **THEN** both `der berg` and `van der berg` are available as blocking alternates

### Requirement: Alias resolution

`records/aliases.ndjson` MUST map non-canonical ids to canonical ids. Alias
resolution MUST be transitive and MUST be cycle-checked at load; a cycle is a
hard error `E_ALIAS_CYCLE`. Every id that has ever existed MUST resolve forever,
so an old commit, export, or stale branch still names something real. Any
sequence of merges MUST yield a resolvable, acyclic alias graph.

#### Scenario: Chained aliases

- **GIVEN** `rec_a` was absorbed into `rec_b`, and later `rec_b` into `rec_c`
- **WHEN** `rec_a` is resolved
- **THEN** it resolves to `rec_c`

#### Scenario: Alias cycle

- **GIVEN** an alias file mapping `rec_a -> rec_b` and `rec_b -> rec_a`
- **WHEN** the repository is loaded
- **THEN** loading fails with `E_ALIAS_CYCLE`

### Requirement: Identifiers for other entities

Other entities MUST use these identifier forms:

| Entity | Form | Assignment |
|---|---|---|
| Report | `rpt_` + the same 16 chars as its canonical record | derived |
| Study | `std_` + 16 chars, ULID-derived | assigned at creation, permanent |
| Effect | `eff_` + study suffix + `_` + 4-char sequence | assigned at creation |
| Criterion | `INC-nn` / `EXC-nn`, zero-padded, assigned in order | user-visible |
| Search | `S-nn` or a user-chosen slug (`S-embase-2026-03`) | user-visible |
| Import | `imp_` + ULID | assigned |
| Event | `ev_` + lowercase ULID (26 chars) | assigned |
| Analysis | user-chosen slug (`primary`, `sensitivity-rct-only`) | user-visible |

Criterion numbers MUST NOT be reused after a criterion is retired, because
historical events cite them.

#### Scenario: Report id mirrors its record

- **WHEN** record `rec_3kq8v1r0zx2m4a7b` is promoted to a report
- **THEN** the report id is `rpt_3kq8v1r0zx2m4a7b`

#### Scenario: New criterion after a retirement

- **GIVEN** exclusion criteria `EXC-01` through `EXC-05`, with `EXC-05` retired
- **WHEN** a new exclusion criterion is added
- **THEN** it is assigned `EXC-06`, never `EXC-05`
