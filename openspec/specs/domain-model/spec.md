# domain-model Specification

## Purpose

Defines the entities of a systematic review (record, report, study, effect,
criterion, search, event, actor), the per-stage screening states derived from
them, and the configurable stage graph. Every PRISMA count is derived from this
model, so the distinctions it draws are what make the flow diagram reconcile.

Rationale and worked examples: [design.md](design.md).

## Requirements

### Requirement: Records, reports, and studies are distinct entities

The system MUST model the three things PRISMA counts separately and MUST derive
every count from the model rather than from typed-in numbers:

- A **Record** is a bibliographic entity, one per row of a database export.
  After deduplication a record is either *canonical* or *absorbed* (merged into
  a canonical record and retained forever as an alias with its own provenance).
- A **Report** is a retrievable document. A canonical record becomes a report
  when it is promoted out of title/abstract screening. A report tracks
  retrieval status (`sought`, `retrieved`, `not-retrieved` with reason), the
  identifier of the exact version obtained, and the date and source of
  retrieval. Documents are identified by DOI or equivalent, never by file hash.
- A **Study** is the unit of research, created during full-text assessment by
  grouping one or more reports. One report MAY describe several studies, and one
  study MAY be reported by several reports. Studies are the unit of data
  extraction and of clustering in analysis.
- An **Effect** is one effect estimate contributed by one study; a study MAY
  contribute many.

"Studies included" and "reports of included studies" are different numbers
whenever one study is reported in more than one paper, and the system MUST
report both.

#### Scenario: One study reported in two papers

- **GIVEN** two included reports that are grouped into a single study
- **WHEN** the PRISMA counts are derived
- **THEN** "reports of included studies" is 2
- **AND** "studies included" is 1

#### Scenario: Raw rows and canonical records are counted separately

- **GIVEN** 7,282 raw records imported, of which 4,364 were absorbed as duplicates
- **WHEN** the counts are derived
- **THEN** "records identified" is 7,282, "duplicates removed" is 4,364, and
  "records screened" is 2,918

### Requirement: Full-text files are never committed

A report's file MUST NOT be committed to the review repository by `strata`; the
report is tracked by identifier only.

#### Scenario: Retrieved report

- **WHEN** a reviewer records that a report's full text was obtained
- **THEN** the report is recorded by its DOI (or equivalent identifier)
- **AND** no PDF is staged or committed

### Requirement: Criteria, searches, events, and actors

The system MUST model:

- **Criterion**: one inclusion or exclusion rule with a stable identifier, a
  short label, a precise definition, and the stages at which it applies.
- **Search**: one executed query against one database on one date, with the
  platform, the exact query string, field tags, applied limits, hit count, and
  export files. The query string MUST be preserved byte-for-byte, including
  whitespace and line breaks.
- **Event**: an immutable, append-only record of one decision or state change.
  Events are the only authoritative carrier of mutable state; every view of
  current state is a fold over the event log.
- **Actor**: a contributor identified by a short stable handle mapped to a
  display name, email, optional ORCID, and role. Events MUST record the handle,
  not the git author, so a reviewer who changes email or institution does not
  fragment their history.

#### Scenario: Actor changes email

- **GIVEN** actor `sam` has authored screening events
- **WHEN** `sam`'s email in `strata.toml` changes and they author further events
- **THEN** all of `sam`'s events carry the handle `sam` and fold as one reviewer's history

#### Scenario: Query string whitespace preserved

- **GIVEN** a search whose query spans four lines with aligned indentation
- **WHEN** the search is recorded and read back
- **THEN** the query string is byte-identical to what was entered

### Requirement: Screening states per stage

Per screening stage (`title-abstract`, `full-text`), a canonical record MUST be
in exactly one state, derived from the fold and never stored as a mutable field:

| State | Meaning |
|---|---|
| `unscreened` | No decision by any reviewer at this stage |
| `partial` | Some but not all assigned reviewers have decided |
| `conflict` | All assigned reviewers decided, and they disagree |
| `include` | Resolved: advances to the next stage |
| `exclude` | Resolved: leaves the pool, citing at least one criterion |
| `not-retrieved` | Full-text stage only: sought, could not be obtained |

#### Scenario: One of two assigned reviewers has decided

- **GIVEN** a record assigned to `ethan` and `sam` at title-abstract
- **WHEN** only `ethan` has recorded a decision
- **THEN** the record's title-abstract state is `partial`

#### Scenario: Two reviewers disagree

- **GIVEN** a record assigned to `ethan` and `sam`
- **WHEN** `ethan` includes it and `sam` excludes it
- **THEN** the record's state is `conflict`

### Requirement: Staleness is an overlay, not a state

`stale` MUST be modelled as an overlay on a resolved state, not as an additional
state: a stale record retains its prior decision and cited criteria so the flow
diagram stays well defined while re-screening is in progress. `strata status`
MUST report both the resolved count and the stale count, and `strata prisma`
MUST refuse to emit a final diagram while any record is stale unless
`--allow-stale` is passed.

#### Scenario: Stale inclusion keeps its decision

- **GIVEN** a record resolved `include` at title-abstract
- **WHEN** a tightening criteria change makes that decision stale
- **THEN** the record's state is still `include`, with the stale overlay set
- **AND** `strata status` counts it both as resolved and as stale

### Requirement: Configurable stage graph

The screening stage list MUST be read from configuration rather than hard-coded,
so an added stage is a configuration change rather than a schema migration. v1
ships the two stages `title-abstract` and `full-text` in the pipeline
`import -> dedup -> title-abstract -> [retrieval] -> full-text -> extraction -> analysis`,
and MUST reject events naming an unknown stage.

#### Scenario: Event names an unconfigured stage

- **GIVEN** `[screening] stages = ["title-abstract", "full-text"]`
- **WHEN** an event with `stage: "tiab-pilot"` is loaded
- **THEN** it is rejected as a dangling reference
