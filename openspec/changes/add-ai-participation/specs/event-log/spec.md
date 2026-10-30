# Spec Delta

## MODIFIED Requirements

### Requirement: Event envelope

Each event MUST be one JSON object per line, not pretty-printed, with envelope
keys in this order:

| Field | Type | Required | Meaning |
|---|---|---|---|
| `ev` | string | yes | Event type |
| `id` | string | yes | `ev_` + lowercase ULID; globally unique; time-ordered |
| `ts` | string | yes | RFC 3339, UTC, second precision, always `Z` |
| `actor` | string | yes | Actor handle from `strata.toml` |
| `agent` | object | no | Present only on events an AI agent caused: `model` (as the agent reported it), `client` (`name`, `version`, when the client gave them) and `invoked_by` (the handle of the person who started the server) |
| `seq` | integer | yes | Monotonic per (actor, file); starts at 1 |
| `body` | object | yes | Type-specific payload |
| `tool` | string | yes | Producing tool and version |
| `prev` | string | no | `digest` of the previous line in this file, absent on line 1 |
| `digest` | string | yes | `sha256` over the canonical serialisation of all preceding fields |

The `agent` key MUST appear only in a repository whose schema version is 2 or higher
(`openspec:repository-format#format-versioning`). An event without it MUST serialise exactly as it
did before the key existed.

#### Scenario: First event in a new file

- **WHEN** the first event is appended to `events/screen/title-abstract.ethan.ndjson`
- **THEN** it has `seq` 1, no `prev` field, and a `digest` over the preceding fields

#### Scenario: Subsequent event

- **WHEN** a second event is appended to the same file
- **THEN** its `prev` equals the first line's `digest` and its `seq` is 2

#### Scenario: Event an agent caused

- **WHEN** an agent invoked by `ada` causes an event
- **THEN** its line has `agent` between `actor` and `seq`, and its `digest` covers the `agent` value

#### Scenario: Event no agent caused

- **GIVEN** an event written by a person
- **WHEN** it is serialised
- **THEN** its bytes are identical to what earlier versions of `strata` wrote for it

## ADDED Requirements

### Requirement: Suggestion events

The system MUST support the event types `suggestion` (body: `op`, `args`, `rationale`,
`criteria_version`, and for criteria changes `preview`) and `suggestion-resolve` (body: `suggestion`,
`outcome` of `adopted`, `rejected` or `superseded`, `reason`, and for adopted ones `result`, the ids of
the events produced). They MUST be sharded as `events/suggestion/<actor>.ndjson`, validated on write and
on load, and MUST NOT take part in the fold of any record state, count or view.

#### Scenario: Suggestion event does not move state

- **GIVEN** a folded state
- **WHEN** a `suggestion` event is added to the log
- **THEN** the folded state is identical

#### Scenario: Suggestion body fails its schema

- **WHEN** a `suggestion` event without an `op` is written or loaded
- **THEN** it is rejected with `E_SCHEMA`

### Requirement: Only assigned actors' opinions resolve a record

The fold MUST resolve a record from the opinions of the actors assigned to it at that stage, and MUST
ignore, for resolution, an opinion from any actor who is not assigned. Such an opinion MUST remain in the
log and in provenance.

#### Scenario: Unassigned actor records an opinion

- **GIVEN** a record assigned to `ethan` and `sam`
- **WHEN** `ethan` and an unassigned actor both record `include`
- **THEN** the record's state is partial

#### Scenario: Shuffled and duplicated events

- **WHEN** the same log, including opinions from unassigned actors, is folded in different orders or with duplicates
- **THEN** the states are identical
