# Proposal: CI for review repositories (M6)

## Why

A review team collaborating through pull requests — the pattern the
`git-integration` spec recommends for protocol changes — wants the same
assurance for their data that this project has for its code: that a change
about to be merged does not break the review. This turns the origin scenario
into something a co-author can review before it lands: the pull request says,
in the diff and in a comment, that a criteria edit invalidates 180 decisions and
removes 42 papers from the pool.

Roadmap milestone: M6 ([docs/roadmap.md](../../../docs/roadmap.md)); it depends only on
`strata verify` and `strata status --json` and may land any time after M0.
Design detail: [design.md](design.md).

## What Changes

- A reusable GitHub Actions workflow and a matching `strata verify` action,
  installed into a review repository by `strata init --ci`.
- Checks: `strata verify`; a pull-request comment built from
  `strata status --json` summarising pool changes, invalidated decisions, and
  opened conflicts; and criteria-change detection that labels the pull request
  `protocol-amendment` and requests the methodologist's review.

## Capabilities

### New Capabilities

- `review-repository-ci`: the reusable workflow, the verify action, and the
  pull-request checks for review repositories.

### Modified Capabilities

- `cli`: adds `strata init --ci`.

## Impact

- A published, versioned GitHub Action and reusable workflow.
- `strata status --json` becomes a consumed contract (already stable per the
  `cli` spec).
