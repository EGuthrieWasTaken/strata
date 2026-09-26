# event-log Specification

## Purpose

The append-only, per-actor-sharded event log that carries every decision and
state change in a review, its tamper-evident hash chain, the deterministic fold
that reduces it to current state, and the catalogue of event types. The event
log provides provenance, conflict-free merging, and recomputable staleness.

Rationale: `docs/spec/02-repository-format.md` §4.

## Requirements

### Requirement: Event envelope

Each event MUST be one JSON object per line, not pretty-printed, with envelope
keys in this order:

| Field | Type | Required | Meaning |
|---|---|---|---|
| `ev` | string | yes | Event type |
| `id` | string | yes | `ev_` + lowercase ULID; globally unique; time-ordered |
| `ts` | string | yes | RFC 3339, UTC, second precision, always `Z` |
| `actor` | string | yes | Actor handle from `strata.toml` |
| `seq` | integer | yes | Monotonic per (actor, file); starts at 1 |
| `body` | object | yes | Type-specific payload |
| `tool` | string | yes | Producing tool and version |
| `prev` | string | no | `digest` of the previous line in this file, absent on line 1 |
| `digest` | string | yes | `sha256` over the canonical serialisation of all preceding fields |

_Source: `docs/spec/02-repository-format.md` §4.2_

#### Scenario: First event in a new file

- **WHEN** the first event is appended to `events/screen/title-abstract.ethan.ndjson`
- **THEN** it has `seq` 1, no `prev` field, and a `digest` over the preceding fields

#### Scenario: Subsequent event

- **WHEN** a second event is appended to the same file
- **THEN** its `prev` equals the first line's `digest` and its `seq` is 2

### Requirement: Per-file hash chain

`prev` and `digest` MUST form a per-file hash chain, and `strata verify` MUST
check the chain and report the first broken line. The chain defends against
accidental corruption (a file opened in a spreadsheet, a partial write) and MUST
NOT be described as defending against a determined adversary.

Because git's `union` merge driver concatenates both sides of a divergent
append, implementations MUST validate the chain per contiguous run and treat a
chain restart as valid if and only if the restarting line's `prev` matches the
digest of some earlier line in the same file.

_Source: `docs/spec/02-repository-format.md` §4.2_

#### Scenario: Edited line

- **GIVEN** a line in the middle of an event file whose body was hand-edited
- **WHEN** `strata verify` runs
- **THEN** it reports `E_CHAIN` naming that line

#### Scenario: Union-merged file

- **GIVEN** an event file produced by a union merge of two branches by the same actor
- **WHEN** the chain is validated
- **THEN** the restart point is accepted because its `prev` matches an earlier line's digest

### Requirement: Merged event files are normalised and re-linked

`strata sync` MUST rewrite a merged event file into canonical `(ts, id)` order,
drop exact duplicate ids, re-link the `prev`/`digest` chain, and record an
`ev:"relink"` event so the rewrite itself is auditable.

_Source: `docs/spec/02-repository-format.md` §4.2; `docs/spec/04-git-integration.md` §5 step 5_

#### Scenario: Sync after a same-actor divergence

- **GIVEN** `ethan` appended screening events on two machines and a union merge interleaved them
- **WHEN** `strata sync` completes
- **THEN** the file is sorted by `(ts, id)`, its chain is linear, and a `relink` event describes the rewrite

### Requirement: The fold

Current state MUST be computed by folding all events, and the fold MUST be:

- **Deterministic**: every event is sorted by `(ts, id)` before reduction, so
  the result does not depend on file order, merge order, or filesystem
  iteration order.
- **Idempotent**: replaying the same event twice is a no-op; `id` is the dedup key.
- **Last-write-wins per key**: for screening, the key is
  `(stage, record, actor)`; the last event for a key is that actor's current opinion.
- **Total**: an event referencing an unknown record, criterion, or stage is a
  hard error (`E_DANGLING_REF`), not a silent skip.

Applying two disjoint event sets in either order MUST yield the same state.

_Source: `docs/spec/02-repository-format.md` §4.3; properties P1, P2, P9 in `docs/spec/14-testing.md` §2_

#### Scenario: Shuffled event log

- **WHEN** the same event log is folded in two different orders
- **THEN** the resulting states are identical

#### Scenario: Duplicated events

- **WHEN** a subset of events is duplicated in the log
- **THEN** the folded state is unchanged

#### Scenario: Event names an unknown record

- **WHEN** an event references a record id that does not exist
- **THEN** the fold fails with `E_DANGLING_REF`

### Requirement: Resolving opinions to a record state

The fold MUST resolve per-actor opinions to a record's state as follows:

```
assigned    = reviewers assigned to (stage, record)   # from strata.toml or an assign event
opinions    = latest event per assigned actor
adjudicated = latest adjudication event for (stage, record), if any

if adjudicated exists            -> its decision (include | exclude)
elif no opinions                 -> unscreened
elif |opinions| < |assigned|     -> partial
elif all opinions agree          -> that decision
else                             -> conflict
```

A `maybe` opinion counts as a decision for the `partial` test but never
resolves: any `maybe` among the opinions yields `conflict`.

_Source: `docs/spec/02-repository-format.md` §4.3_

#### Scenario: Both reviewers answer maybe

- **GIVEN** a record assigned to `ethan` and `sam`
- **WHEN** both record `maybe`
- **THEN** the record's state is `conflict`

#### Scenario: Adjudication overrides disagreement

- **GIVEN** a record in `conflict`
- **WHEN** an adjudicator records `exclude`
- **THEN** the record's state is `exclude`

### Requirement: First opinions are retained

The fold MUST retain the first event per `(stage, record, actor)` as well as the
last, so inter-rater reliability can be computed over independent first
opinions only.

_Source: `docs/spec/02-repository-format.md` §6.5_

#### Scenario: Reviewer changes their mind after seeing a conflict

- **GIVEN** `sam` first excluded a record, then later included it
- **WHEN** the fold runs
- **THEN** `sam`'s current opinion is `include` and `sam`'s first opinion is `exclude`

### Requirement: Undo is an appended correction

Undoing a decision MUST append a correcting event, and a decision followed by
its undo MUST fold to the pre-decision state.

_Source: `docs/spec/06-workflow-screening.md` §7; property P13 in `docs/spec/14-testing.md` §2_

#### Scenario: Decide then undo

- **GIVEN** an unscreened record
- **WHEN** a reviewer includes it and then undoes the decision
- **THEN** the record folds to `unscreened` and both events remain in the file

### Requirement: Event types

The system MUST support these event types, each with a JSON Schema in the
source tree validated on write and on load:

| `ev` | Emitted by | Key body fields |
|---|---|---|
| `import` | `strata import` | `import_id`, `search_id`, `source`, `count`, `file_digest` |
| `record-add` | `strata import` | `record`, `import_id`, `raw_row_digest` |
| `record-amend` | `strata fix` | `record`, `field`, `old`, `new`, `source` |
| `dedup-merge` | `strata dedup` | `canonical`, `absorbed`, `score`, `method`, `features` |
| `dedup-distinct` | `strata dedup` | `a`, `b`, `score`, `method` |
| `dedup-unmerge` | `strata dedup --undo` | `canonical`, `restored` |
| `assign` | `strata assign` | `stage`, `records` or `filter`, `actors` |
| `screen` | `strata screen` | `stage`, `record`, `decision`, `criteria[]`, `note`, `criteria_version`, `criteria_digest`, `confidence` |
| `adjudicate` | `strata adjudicate` | `stage`, `record`, `decision`, `criteria[]`, `rationale`, `supersedes[]` |
| `retrieval` | `strata retrieve` | `report`, `status`, `source`, `locator`, `version`, `reason` |
| `study-group` | `strata studies` | `study`, `reports[]`, `rationale` |
| `study-split` | `strata studies` | `report`, `studies[]`, `rationale` |
| `extract` | `strata extract` | `study`, `actor`, `fields_changed[]`, `digest` |
| `reconcile` | `strata extract --reconcile` | `study`, `field`, `chosen`, `from`, `rationale` |
| `rob` | `strata rob` | `study`, `domain`, `judgement`, `support` |
| `criteria-change` | `strata criteria` | `from_version`, `to_version`, `deltas[]`, `rationale`, `amendment_id` |
| `relink` | `strata sync` | `file`, `lines_reordered`, `reason` |
| `note` | `strata note` | `subject`, `text` |

_Source: `docs/spec/02-repository-format.md` §4.4_

#### Scenario: Event body fails its schema

- **WHEN** a `screen` event without a `decision` field is written or loaded
- **THEN** it is rejected with `E_SCHEMA`

### Requirement: File sharding

Event files MUST be sharded as `events/<domain>/<stage>.<actor>.ndjson`, or
`events/<domain>/<actor>.ndjson` where the domain has no stage, so two actors
never append to the same file. A file SHOULD be split when it exceeds 100,000
lines by appending `.2`, `.3` to the stem, and the fold MUST read all matching
shards.

_Source: `docs/spec/02-repository-format.md` §4.5_

#### Scenario: Two reviewers screening

- **WHEN** `ethan` and `sam` both screen at title-abstract
- **THEN** their events are written to `events/screen/title-abstract.ethan.ndjson`
  and `events/screen/title-abstract.sam.ndjson` respectively

#### Scenario: Split shard

- **GIVEN** `title-abstract.ethan.ndjson` and `title-abstract.ethan.2.ndjson`
- **WHEN** the fold runs
- **THEN** events from both shards are included
