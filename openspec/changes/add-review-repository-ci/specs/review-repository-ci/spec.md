# review-repository-ci Specification

## Purpose

Continuous integration for review repositories (not the `strata` source
repository): a reusable workflow and `strata verify` action that let a review
team see, before merging, whether a change breaks the review and what it does
to the pool.

## ADDED Requirements

### Requirement: Installable review CI

`strata` MUST ship a reusable GitHub Actions workflow and a matching
`strata verify` action, and `strata init --ci` MUST install them into a review
repository.

#### Scenario: Initialising with CI

- **WHEN** `strata init my-review --ci` runs
- **THEN** the review repository contains a workflow that runs the strata checks on pull requests

### Requirement: Verification check

The review CI MUST run `strata verify` (schemas, hash chains, dangling
references, derived drift, count reconciliation) on every pull request and fail
the check on any violation.

#### Scenario: Hand-edited event file

- **WHEN** a pull request contains a hand-edited event file
- **THEN** the verify check fails citing `E_CHAIN`

### Requirement: Pool-impact comment

The review CI MUST post a pull-request comment built from
`strata status --json` summarising what the change does to the pool: records
entering and leaving, decisions invalidated, and conflicts opened.

#### Scenario: Criteria edit under review

- **WHEN** a pull request tightens a criterion
- **THEN** the comment states how many decisions it invalidates and how many papers would leave the pool

### Requirement: Protocol-amendment detection

When a pull request changes the criteria, the review CI MUST label it
`protocol-amendment` and request review from the configured methodologist.

#### Scenario: Criterion added

- **WHEN** a pull request adds a criterion
- **THEN** it is labelled `protocol-amendment` and the methodologist is requested as a reviewer
