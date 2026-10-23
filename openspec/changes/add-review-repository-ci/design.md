# Design: CI for review repositories

## Context

Everything in the `ci-gate` capability concerns the `strata` source repository.
Review teams that collaborate through pull requests — the pattern the
`git-integration` design recommends for protocol changes — want the same
assurance for their *data*: that a change about to be merged does not break the
review.

## Goals / Non-Goals

**Goals:**

- A co-author can review a protocol change before it lands, seeing in the pull
  request exactly which decisions it invalidates and what leaves the pool.
- A review repository can require that it still verifies before a manuscript is
  submitted.

**Non-Goals:**

- CI providers other than GitHub Actions in the first iteration; the checks are
  plain `strata` commands, so porting is straightforward.

## Decisions

- **Build on existing contracts only.** The workflow uses `strata verify` and
  the versioned `strata status --json` output, so it can land any time after M0
  and never needs private hooks into `strata`.
- **Label rather than block protocol amendments.** A criteria change is a
  legitimate methodological event; the workflow labels it `protocol-amendment`
  and requests the methodologist's review instead of failing.

- **A thin caller, a reusable workflow, and one pinned ref.** `strata init --ci` writes
  `.github/workflows/strata.yml`, which only calls the reusable workflow in the `strata`
  repository and passes the same ref for installing the CLI, so a review repository decides which
  version of the checks it trusts. The `strata verify` action installs `strata` from its own
  checkout (`$GITHUB_ACTION_PATH/../..`), so the action and the CLI cannot drift apart.
- **`pull_request`, never `pull_request_target`.** Fork code must not get a write token or secrets,
  so for fork pull requests the comment and label are skipped and only the verify check runs.
- **The comment reads `status --json` only.** Records entering and leaving come from the pool size,
  decisions invalidated from the rise in stale decisions, and "papers that could leave the pool"
  from the stale decisions that are `include` decisions (`stale_included`, added to each stage in
  `status --json`; an additive change to the contract). What re-screening will decide is not
  known before it happens, so the comment says "could".
- **The shell steps are tested.** The workflow's `run:` steps are executed in the test suite against
  a fake `gh`, and the file is checked with actionlint when changed; neither replaces a run on a
  real runner.

## Risks / Trade-offs

- The pull-request comment exposes pool-level counts to anyone who can read the
  pull request; for private review repositories that is the same audience as the
  repository itself.
