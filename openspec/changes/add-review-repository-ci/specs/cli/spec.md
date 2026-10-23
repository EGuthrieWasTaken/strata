# cli Specification Delta

## ADDED Requirements

### Requirement: Initialising with review CI

`strata init --ci` MUST, in addition to its normal behaviour, install the
reusable review-repository workflow and `strata verify` action.

#### Scenario: Without the flag

- **WHEN** `strata init` runs without `--ci`
- **THEN** no CI workflow is written

### Requirement: CI helper commands

`strata ci amendment` MUST report, as JSON, whether the criteria differ between two commits
(compared as data, so reformatting is not a change) and which criteria were added, changed or
retired; `strata ci comment` MUST render the pull-request comment, as Markdown, from two
`strata status --json` documents and that report. Both MUST need nothing from the network.

#### Scenario: Reformatted criteria file

- **WHEN** `strata ci amendment` compares two commits whose criteria files differ only in comments or layout
- **THEN** it reports that the criteria did not change

#### Scenario: Base that is not a review repository

- **WHEN** `strata ci comment` is given `null` for the base status
- **THEN** it renders the head as it stands and says that the base has no strata repository

