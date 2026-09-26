# data-schemas Specification

## Purpose

The persisted objects of a review repository that exist from the first
milestones — the project manifest, bibliographic records, the criteria file,
planned moderators, and recorded searches — field by field, together with the
rule that every one of them has a shipped machine-readable JSON Schema.

Rationale and full examples: `docs/spec/03-schemas.md` §1–§5.

## Requirements

### Requirement: Machine-readable schemas are shipped and enforced

Every persisted object MUST have a JSON Schema (Draft 2020-12) shipped in the
source tree under `strata/schemas/`, and MUST be validated on write and on
load. The shipped schema is the contract; where human-readable documentation
disagrees with it, the shipped schema is a bug to be fixed.

_Source: `docs/spec/03-schemas.md` preamble_

#### Scenario: Invalid manifest on load

- **WHEN** a repository whose `strata.toml` violates the manifest schema is loaded
- **THEN** loading fails with `E_SCHEMA`

### Requirement: Project manifest

`strata.toml` MUST carry `schema_version`, `created_with`, a `[project]` table
(`id`, `title`, `slug`, `created`, optional `registry`, and a data `license`),
an `[[actors]]` array (`handle`, `name`, `email`, optional `orcid`, `role` of
`lead | screener | extractor | adjudicator | observer | inactive`), and the
`[screening]`, `[screening.assignment]`, `[dedup]`, `[git]`, `[enrichment]`, and
`[analysis]` tables. It MUST enforce:

- `actors[].handle` matches `^[a-z0-9][a-z0-9-]{0,31}$` and is unique.
- An actor who has authored an event MUST NOT be removed; they are set to
  `role = "inactive"` instead.
- `screening.mode = "dual"` with an assignment list of length 1 is a
  configuration error (`E_CONFIG`).
- `enrichment.enabled = true` with an empty `contact_email` is a configuration
  error.

_Source: `docs/spec/03-schemas.md` §1_

#### Scenario: Invalid actor handle

- **WHEN** an actor is added with handle `Ethan G`
- **THEN** it is rejected because it does not match the handle pattern

#### Scenario: Removing an actor with history

- **GIVEN** actor `sam` has authored screening events
- **WHEN** a user tries to remove `sam`
- **THEN** removal is refused and `strata actor deactivate` is offered instead

#### Scenario: Dual screening with one reviewer

- **WHEN** `mode = "dual"` and `"title-abstract" = ["ethan"]`
- **THEN** configuration validation fails with `E_CONFIG`

### Requirement: Record schema is CSL-JSON plus a namespaced extension

A record in `records/records.ndjson` MUST be CSL-JSON with a single `strata`
extension object:

| Field | Required | Notes |
|---|---|---|
| `id` | yes | Record id |
| `type` | yes | CSL type; default `article-journal` |
| `title` | yes | Empty title is a hard import error |
| `author` | no | CSL name objects; `literal` allowed for corporate authors |
| `issued` | no | CSL date; `date-parts` only |
| `DOI`, `PMID`, `PMCID`, `URL`, `ISBN` | no | Normalised |
| `abstract` | no | Verbatim from source; structured-abstract labels preserved |
| `keyword` | no | `;`-joined list |
| `strata.canonical` | yes | `false` means retained only for provenance |
| `strata.sources` | yes | Append-only; one entry per import that saw this record |
| `strata.field_provenance` | no | Which source each field's current value came from |
| `strata.flags` | no | `no-abstract`, `no-doi`, `retracted`, `preprint`, `non-english`, `id-unstable` |

Unknown CSL fields MUST be preserved on round-trip; `strata` MUST NOT silently
drop metadata. If enrichment is enabled, `strata` SHOULD check Crossref for
`update-to` relations and set the `retracted` flag.

_Source: `docs/spec/03-schemas.md` §2_

#### Scenario: Unknown CSL field

- **GIVEN** an imported CSL-JSON record with a `collection-title` field
- **WHEN** the record is written and read back
- **THEN** `collection-title` is preserved unchanged

#### Scenario: Empty title

- **WHEN** an import row has an empty title
- **THEN** the row is rejected as a hard import error for that row

### Requirement: Criteria file schema and digests

`protocol/criteria.yaml` MUST carry a `version`, a GENERATED `digest`, and a
`criteria` list whose entries have `id` (`INC-nn` / `EXC-nn`, never reused),
`kind` (`inclusion` | `exclusion`), `label` (at most 80 characters),
`definition`, `applies_at` (a non-empty subset of configured stages),
`since_version`, `status` (`active` | `retired`; retired criteria stay in the
file forever), and optional `examples`.

The **per-criterion digest** MUST be `sha256` over the canonical serialisation
of `{id, kind, definition, applies_at}`; `label` and `examples` are excluded so
relabelling can never make work stale. The **set digest** MUST be `sha256` over
the concatenation of per-criterion digests of active criteria, sorted by id.

_Source: `docs/spec/03-schemas.md` §3_

#### Scenario: Relabelling a criterion

- **WHEN** only a criterion's `label` changes
- **THEN** its per-criterion digest and the set digest are unchanged

#### Scenario: Retired criterion

- **WHEN** a criterion is retired
- **THEN** it remains in `criteria.yaml` with `status: retired`
- **AND** it no longer contributes to the set digest

### Requirement: Moderators schema

`protocol/moderators.yaml` MUST declare each planned moderator with `name`,
`label`, `type` (`continuous | categorical | ordinal | boolean | count`), type
specific fields (`unit`, `range`, `levels`, `reference`), `planned`, and
`since_version`. Moderators with `planned: false` MUST be reported as post hoc
in all generated output.

_Source: `docs/spec/03-schemas.md` §4_

#### Scenario: Post hoc moderator

- **GIVEN** a moderator declared with `planned: false`
- **WHEN** any report mentioning it is generated
- **THEN** the moderator is labelled post hoc

### Requirement: Search schema

A search file `protocol/searches/<id>.yaml` MUST record `id`, `database`,
`platform`, `executed`, `executed_by`, `query`, `limits`, `hits`,
`export_files`, optional `peer_reviewed_by` and `notes`, and `supersedes`.
`query` MUST be a literal block scalar and MUST round-trip byte-for-byte.
Re-running a search on a later date MUST create a new search file with
`supersedes` set, never an edit of the earlier one.

_Source: `docs/spec/03-schemas.md` §5_

#### Scenario: Update search

- **GIVEN** search `S-01-medline` executed on 2026-03-04
- **WHEN** the same strategy is rerun on 2026-09-01
- **THEN** a new search file is created with `supersedes: "S-01-medline"`
- **AND** `S-01-medline.yaml` is unchanged
