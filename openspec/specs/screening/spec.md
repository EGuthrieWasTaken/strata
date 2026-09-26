# screening Specification

## Purpose

Title/abstract and full-text screening: dual independent review with blinding
enforced by data layout, reviewer assignment, the screening-surface contract
shared by the CLI and web UI, inter-rater reliability, and scriptable import of
screening work done elsewhere.

Rationale and worked examples: [design.md](design.md).

## Requirements

### Requirement: Two screening stages

`strata screen <stage> [--filter EXPR] [--limit N]` MUST open the screening
queue for a stage. At the title-abstract stage the surface MUST be optimised
for speed. At the full-text stage exclusions MUST cite at least one criterion,
and the surface MUST offer opening the local PDF.

#### Scenario: Full-text exclusion without a criterion

- **WHEN** a reviewer tries to exclude a report at full-text without citing a criterion
- **THEN** the decision is refused until a criterion is cited

### Requirement: Dual independent screening with blinding

With `screening.mode = "dual"`, two reviewers MUST screen every assigned record
independently. When `blind_reviewers` is true (the default), a surface MUST
NOT reveal another reviewer's decision before the current reviewer commits their
own. Independence MUST also be enforced by data layout: each reviewer's events
live in their own file. When `blind_metadata` is true, author, journal, and year
MUST be hidden during screening.

#### Scenario: Colleague already decided

- **GIVEN** `blind_reviewers = true` and `sam` has excluded a record
- **WHEN** `ethan` opens that record for screening
- **THEN** nothing on the screen indicates `sam`'s decision

#### Scenario: Blind metadata

- **GIVEN** `blind_metadata = true`
- **WHEN** a record is shown for screening
- **THEN** its authors, journal, and year are not displayed

### Requirement: Single-reviewer mode is disclosed

`single` screening mode MUST be supported for pilot and scoping work, and
generated Methods text MUST state plainly that screening was performed by a
single reviewer.

#### Scenario: Methods under single mode

- **GIVEN** `mode = "single"`
- **WHEN** Methods text is generated
- **THEN** it states that screening was performed by a single reviewer

### Requirement: Reviewer assignment

`strata assign <stage> --actors a,b [--filter EXPR]` MUST record an `assign`
event assigning reviewers to records at a stage; assignment otherwise defaults
to `[screening.assignment]` in `strata.toml`.

#### Scenario: Assigning a subset

- **WHEN** `strata assign full-text --actors ethan,sam --filter "year >= 2010"` runs
- **THEN** an `assign` event is recorded and matching records require both reviewers at full-text

### Requirement: Screening surface contract

Whether CLI or web, the screening surface MUST provide:

| Requirement | Detail |
|---|---|
| Keyboard-first | Every action reachable without a pointer; `i`/`e`/`m` decide, `u` undoes, digits `1`–`9` cite criteria, `n`/`p` navigate, `?` shows help |
| Sub-100 ms response | A decision feels instant; persistence is asynchronous but crash-safe |
| Undo | `u` reverts the last decision within the session by appending a correcting event |
| Criterion definitions visible | Full definition on focus, not just the label |
| Configurable highlighting | User-defined terms highlighted in title and abstract |
| Progress and pace | Records done, remaining, current rate, estimated finish |
| Blinding | Honour `blind_reviewers` and `blind_metadata` |
| Resumability | Closing and reopening resumes at the same record |
| No dead ends | Records with no abstract are flagged, not silently skipped |

#### Scenario: Excluding with a criterion by keyboard

- **WHEN** a reviewer presses `e` then `2`
- **THEN** the record is excluded citing the second listed criterion without using a pointer

#### Scenario: Record without an abstract

- **WHEN** the queue reaches a record with no abstract
- **THEN** the record is shown with a visible no-abstract flag rather than skipped

#### Scenario: Resuming a session

- **GIVEN** a reviewer closed the screening session at record 482
- **WHEN** they reopen the queue
- **THEN** it resumes at record 482

### Requirement: Interrupted sessions lose nothing

Screening decisions MUST be appended and fsynced before the reviewer advances,
so a session killed mid-way (including SIGKILL) resumes with no lost decisions.

#### Scenario: SIGKILL mid-session

- **GIVEN** a reviewer has recorded 37 decisions in a session
- **WHEN** the process is killed with SIGKILL and the queue is reopened
- **THEN** all 37 decisions are present and the queue resumes after the last one

### Requirement: Decision latency

A screening session MUST sustain decision round-trip latency under 100 ms at
p95 (hard limit 250 ms) at 50,000 records.

#### Scenario: Large review

- **WHEN** a reviewer screens in a 50,000-record repository
- **THEN** p95 decision latency is under 100 ms

### Requirement: Inter-rater reliability report

`strata irr [--stage S]` MUST report, per stage and reviewer pair, raw
agreement, Cohen's kappa, PABAK, and the 2x2 table over independent first
opinions only. Adjudication MUST NOT alter IRR, which reflects the original
disagreement.

#### Scenario: IRR after adjudication

- **GIVEN** 14 conflicts that were all adjudicated
- **WHEN** `strata irr --stage title-abstract` runs
- **THEN** the reported agreement still counts those 14 records as disagreements

### Requirement: Importing screening decisions

`strata screen <stage> --decisions <file>` MUST accept a TSV of
`record_id  decision  criteria  note` as the supported path for importing
screening work done in another tool. Imported decisions MUST be attributed to
the declared actor and marked `imported: true` in the event body.

#### Scenario: Pilot decisions from a spreadsheet

- **WHEN** `strata screen title-abstract --decisions pilot.tsv --by sam --why "imported from pilot"` runs
- **THEN** one `screen` event per row is appended to `sam`'s file with `imported: true`
