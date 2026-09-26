# Design: ci-gate

*Informative.* The requirements are in [spec.md](spec.md).

## Why the gate was built first

The CI pipeline and its pull-request gate were the first deliverable of M0,
before the event log and before any feature code:

- Three of the project's correctness guarantees are cross-platform byte-identity
  claims, which cannot be checked on one developer's laptop. A determinism bug
  found by the pull request that causes it costs ten minutes; found six months
  later, it is expensive.
- Statistical validation is the project's entire credibility argument. A suite
  that runs only when someone remembers is not a validation argument.
- P10 and P11 protect claims the product is sold on and must be un-skippable.

A repository whose gate arrives late accumulates untested code that nobody wants
to retrofit tests for, and the retrofit never happens.

## Why tiers

Contributors get a useful signal within minutes (lint, fast tests) while the
expensive checks still block the merge.

## Why one always-running `gate` job

Path filters and conditional matrices cause skipped jobs, and a *skipped*
required check blocks a merge forever. One `gate` job that depends on every
tier-1 and tier-2 job and accepts `success` or `skipped` keeps
documentation-only pull requests mergeable without making it possible to skip a
check that should have run. Administrators are included in branch protection: a
gate the maintainer can walk past gets walked past at 2am, which is exactly when
it is most needed.

## Why pinned SHAs and no `pull_request_target`

A moving tag in a workflow with repository write access is a supply-chain
exposure, and `pull_request_target` would hand fork pull requests the secrets.

## Why the specification is checked too

The specification is edited more often than code in early milestones, and its
characteristic failure is a reference that no longer resolves after something is
renamed. The `docs` job therefore validates the OpenSpec specs and changes,
Markdown links and anchors, `openspec:` references anywhere in the repository,
and fenced config blocks.

## Flakes

A failing test is a failure until proven otherwise. Blanket retries convert a
real intermittent bug into invisible noise, and quarantining a test to get green
removes the check exactly when it is finding something. A nondeterministic test
is a bug in the test: seed it.
