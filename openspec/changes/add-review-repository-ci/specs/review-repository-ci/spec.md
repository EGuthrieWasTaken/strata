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

### Requirement: One comment, updated in place

The review CI MUST keep a single pool-impact comment on a pull request and update it
when the pull request changes, rather than adding a comment for every push.

#### Scenario: Second push to a pull request

- **WHEN** a pull request that already has the comment receives another commit
- **THEN** the existing comment is edited and no second comment is added

### Requirement: Pull requests from forks

The review CI MUST run the verification check for pull requests from forks, and MUST NOT use a
trigger that gives fork code a write token or secrets; the comment, label and review request,
which need write access, MAY be skipped for them.

#### Scenario: Fork pull request

- **WHEN** a pull request comes from a fork
- **THEN** `strata verify` runs and fails the check on a violation, and no comment, label or review request is attempted

### Requirement: Review request that cannot be made

The review CI MUST NOT fail a pull request because the methodologist could not be asked to
review it; the amendment label and the comment stand, and the failure is reported as a warning.

#### Scenario: Methodologist is the author

- **WHEN** a criteria-changing pull request is opened by the configured methodologist and GitHub refuses the review request
- **THEN** the pull request is still labelled `protocol-amendment` and the check does not fail

