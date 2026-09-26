# repository-verification Specification

## Purpose

`strata verify` and the reliability guarantees it enforces: the cross-schema
validation rules and their error codes, derived-drift detection, crash safety,
and the `--fix` recovery path that restores every invariant after arbitrary
manual git surgery.

Rationale: `docs/spec/03-schemas.md` §10, `docs/spec/13-nonfunctional.md` §2,
`docs/spec/04-git-integration.md` §1.

## Requirements

### Requirement: Cross-schema validation rules

`strata verify` MUST enforce all of the following and report every violation,
not just the first:

| Code | Rule |
|---|---|
| `E_SCHEMA` | Any file fails its JSON Schema |
| `E_DANGLING_REF` | An event names a record, criterion, actor, study, or stage that does not exist |
| `E_ALIAS_CYCLE` | Alias resolution cycles |
| `E_CHAIN` | An event file's hash chain is broken |
| `E_DERIVED_DRIFT` | A committed derived file differs from regeneration |
| `E_CRITERION_REUSE` | A criterion id is reused after retirement |
| `E_EXCLUSION_NO_CRITERION` | An `exclude` decision cites no criterion while `require_exclusion_reason` is set |
| `E_CRITERION_STAGE` | A decision cites a criterion that does not apply at that stage |
| `E_ORPHAN_EXTRACTION` | An extraction file exists for a study that is not included |
| `E_MISSING_EXTRACTION` | An included study has no consensus extraction (warning until analysis) |
| `E_COUNT_RECONCILE` | The PRISMA counts do not satisfy the reconciliation identities |
| `E_UNIT` | A `quantity` value has a unit outside `accepts_units` |
| `E_EFFECT_INPUTS` | An effect lacks the fields its declared design requires |

Each code is an identified requirement and MUST be named by at least one test.

_Source: `docs/spec/03-schemas.md` §10; `docs/spec/14-testing.md` §10.5_

#### Scenario: Multiple violations

- **GIVEN** a repository with a broken hash chain and a dangling criterion reference
- **WHEN** `strata verify` runs
- **THEN** it reports both `E_CHAIN` and `E_DANGLING_REF`
- **AND** exits with code 4

#### Scenario: Exclusion without a criterion

- **GIVEN** `require_exclusion_reason = true`
- **WHEN** an `exclude` screen event with an empty `criteria` list is verified
- **THEN** `strata verify` reports `E_EXCLUSION_NO_CRITERION`

#### Scenario: Criterion cited at the wrong stage

- **GIVEN** `EXC-07` applies only at `full-text`
- **WHEN** a title-abstract exclusion cites `EXC-07`
- **THEN** `strata verify` reports `E_CRITERION_STAGE`

### Requirement: Fast verification for hooks

`strata verify --fast` MUST check schemas, chains, dangling references, and
derived drift, and MUST complete in under 2 seconds on a 50,000-record
repository. The full `strata verify` MAY take longer and runs in CI.

_Source: `docs/spec/04-git-integration.md` §4_

#### Scenario: Pre-commit check

- **WHEN** the pre-commit hook runs `strata verify --fast` on a 50,000-record repository
- **THEN** it completes in under 2 seconds

### Requirement: No silent data loss

Every mutation MUST be an append to a log that is fsynced before the user sees
confirmation. A power failure mid-session loses at most the uncommitted tail,
which `strata status` MUST detect and offer to commit.

_Source: `docs/spec/13-nonfunctional.md` §2_

#### Scenario: Power loss after decisions were confirmed

- **GIVEN** a reviewer has seen confirmation for 30 decisions that were not yet committed
- **WHEN** the machine loses power and `strata status` is run afterwards
- **THEN** all 30 decisions are present in the event log
- **AND** `strata status` offers to commit them

### Requirement: Crash safety and partial lines

Interrupting any command MUST leave the repository in a valid state. A
partially written NDJSON line has no valid digest; readers MUST skip it rather
than fail, and `strata verify --fix` MUST truncate it.

_Source: `docs/spec/13-nonfunctional.md` §2; `docs/spec/12-architecture.md` §4_

#### Scenario: Truncated last line

- **GIVEN** an event file whose last line was cut off mid-write
- **WHEN** a reader folds the log
- **THEN** the partial line is skipped and the fold succeeds
- **AND** `strata verify --fix` removes the partial line

### Requirement: Recovery with verify --fix

`strata verify --fix` MUST regenerate every derived artefact and re-link event
chains after any amount of manual git surgery. `strata` MUST NOT wrap git so
tightly that manual git use can corrupt the repository beyond what `--fix`
restores.

_Source: `docs/spec/04-git-integration.md` §1; `docs/spec/13-nonfunctional.md` §2; E2E-08 in `docs/spec/14-testing.md` §5_

#### Scenario: Corrupted derived file, truncated event file, deleted cache

- **GIVEN** a repository with a corrupted `derived/pool.tsv`, an event file truncated mid-line, and a deleted `.strata/cache/`
- **WHEN** `strata verify --fix` runs
- **THEN** the repository verifies cleanly afterwards

### Requirement: No destructive defaults

Nothing MUST be deleted by ordinary operation: deduplication absorbs,
retirement retains, exclusion records. The only command that removes data is
`strata gc --imports`, which prunes raw import files, MUST require
confirmation, and MUST be documented as breaking reproducibility.

_Source: `docs/spec/13-nonfunctional.md` §2_

#### Scenario: Pruning raw imports

- **WHEN** a user runs `strata gc --imports`
- **THEN** the command asks for confirmation and warns that reproducibility will be lost before deleting anything
