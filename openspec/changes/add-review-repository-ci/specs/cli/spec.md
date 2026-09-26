# cli Specification Delta

## ADDED Requirements

### Requirement: Initialising with review CI

`strata init --ci` MUST, in addition to its normal behaviour, install the
reusable review-repository workflow and `strata verify` action.

#### Scenario: Without the flag

- **WHEN** `strata init` runs without `--ci`
- **THEN** no CI workflow is written
