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

## Risks / Trade-offs

- The pull-request comment exposes pool-level counts to anyone who can read the
  pull request; for private review repositories that is the same audience as the
  repository itself.
