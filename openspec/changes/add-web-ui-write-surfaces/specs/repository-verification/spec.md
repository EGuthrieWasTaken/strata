# Spec Delta

## ADDED Requirements

### Requirement: Derived files are held to regeneration

`strata verify` MUST report `E_DERIVED_DRIFT`, naming the file, for every file under `derived/` that exists and differs from what regenerating it now produces, and MUST fail. A derived file that does not exist is not drift. `strata verify --fix` MUST regenerate the files that drifted, MUST leave other problems reported and unrepaired, and MUST leave the regenerated files uncommitted.

#### Scenario: A counts file that is out of date

- **GIVEN** a review whose `derived/counts.json` no longer matches its records and events
- **WHEN** `strata verify` runs
- **THEN** it reports `E_DERIVED_DRIFT` for `derived/counts.json` and exits non-zero

#### Scenario: A change that forgot the pool

- **GIVEN** a record's title was corrected without `derived/pool.tsv` being regenerated
- **WHEN** `strata verify` runs
- **THEN** it reports `E_DERIVED_DRIFT` for `derived/pool.tsv` only

#### Scenario: Repairing drift

- **GIVEN** `derived/irr.json` has drifted
- **WHEN** `strata verify --fix` runs
- **THEN** it regenerates `derived/irr.json`, says so, and verifies clean
- **AND** the regenerated file is modified in the working tree and not committed

#### Scenario: A file that is not there

- **GIVEN** `derived/pool.tsv` has been deleted
- **WHEN** `strata verify` runs
- **THEN** it reports no drift for it

### Requirement: Commands keep derived files current

Every command that changes what a derived file shows MUST regenerate it, and `strata init` MUST write the derived files as regeneration writes them, so that a repository built only with `strata` verifies clean after every command.

#### Scenario: A new review

- **WHEN** `strata init` creates a review and `strata verify` runs
- **THEN** it verifies clean, and `derived/irr.json` and `derived/counts.json` are what regeneration writes, not placeholders

#### Scenario: A review taken through its commands

- **WHEN** a review is taken through `import`, `dedup`, `fix`, `assign`, `screen`, `retrieve`, `criteria add|edit` and `actor deactivate`
- **THEN** no derived file differs from regeneration after any of them
