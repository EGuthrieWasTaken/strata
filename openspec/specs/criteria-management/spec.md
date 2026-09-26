# criteria-management Specification

## Purpose

Adding, editing, retiring, listing, and diffing inclusion/exclusion criteria as
a versioned protocol, including the mandatory classification of every
definition change by direction — the input the staleness engine needs to
compute exactly which prior decisions a change invalidates.

Rationale and worked examples: [design.md](design.md).

## Requirements

### Requirement: Criteria commands and versioning

`strata` MUST provide `criteria add`, `criteria edit <ID>`,
`criteria retire <ID>`, `criteria list [--at STAGE] [--version N]`, and
`criteria diff <v1> <v2>` (showing what changed between versions and what it
invalidated). Any change to the active criteria set MUST increment
`criteria.version` by one, recompute digests, and emit a `criteria-change` event
carrying the deltas, the rationale, and the from/to versions.

#### Scenario: Adding a criterion

- **GIVEN** criteria at version 3
- **WHEN** `strata criteria add --kind exclusion --label "Mean sample age under 18" ...` completes
- **THEN** the criteria file is at version 4 with recomputed digests
- **AND** a `criteria-change` event from version 3 to 4 is recorded

#### Scenario: Listing criteria at a stage

- **WHEN** `strata criteria list --at full-text` runs
- **THEN** only criteria whose `applies_at` includes `full-text` are shown

### Requirement: Declaring the direction of a change

When a criterion's `definition` changes, `strata` MUST ask the user to classify
the change, because the tool cannot reliably infer it from text:

| Direction | Meaning | Semantics |
|---|---|---|
| `tightened` | The included pool can only shrink (an exclusion excludes more, or an inclusion includes fewer) | May invalidate prior inclusions |
| `loosened` | The included pool can only grow | May invalidate prior exclusions citing it |
| `both` | Unknown or genuinely bidirectional | Invalidates both directions |
| `editorial` | No semantic change | Invalidates nothing |

A criterion **added** MUST behave as `tightened`; a criterion **retired** MUST
behave as `loosened`.

#### Scenario: Definition edited interactively

- **WHEN** a user edits `EXC-03`'s definition
- **THEN** they are shown the old and new definitions and asked to choose tightened, loosened, both, or editorial

#### Scenario: Retiring a criterion

- **WHEN** `INC-05` is retired
- **THEN** the change is treated as `loosened` for staleness

### Requirement: The editorial claim is verified

Because `editorial` is the one option asserting "nothing to redo", `strata` MUST
NOT accept it on trust: it MUST verify that only `label`, `examples`, or
whitespace changed, and MUST refuse `editorial` if the `definition` text changed
in any other way. `both` MUST always be available as the safe choice.

#### Scenario: Meaningful edit claimed as editorial

- **WHEN** a user changes "not written in English" to "not written in English or French" and chooses `editorial`
- **THEN** the classification is refused and the user must choose tightened, loosened, or both

#### Scenario: Whitespace-only edit

- **WHEN** a definition changes only by reflowed whitespace and the user chooses `editorial`
- **THEN** the change is accepted and no decision becomes stale

### Requirement: Retired criteria and ids are permanent

Retired criteria MUST stay in `protocol/criteria.yaml` forever, and criterion
ids MUST never be reused (`E_CRITERION_REUSE`).

#### Scenario: Id reuse detected

- **GIVEN** a criteria file in which a new active criterion reuses a retired criterion's id
- **WHEN** `strata verify` runs
- **THEN** it reports `E_CRITERION_REUSE`
