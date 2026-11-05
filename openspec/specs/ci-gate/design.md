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

## Why documentation-only pull requests skip the tests, and how

The full gate takes one to two hours (the `test` matrix on the slowest Windows leg), and a change to a README
cannot fail a test. So a pull request that changes only documentation skips `test-fast` and everything that
waits for it, and runs `lint`, `docs` and `gate`.

The skipping is decided by a script, `scripts/ci_changes.py`, inside the workflow, not by a path filter on
the workflow: a workflow that a path filter skips never reports `gate`, and a required check that never
reports blocks the merge for good. Skipping inside the workflow is only safe if the skipping is itself
checked, because `gate` accepts a skipped job. So the script's default is "code" (a push, a missing base, a
`git` that fails, or no changed files all run everything); a rename counts as a deletion and an addition, so a
source file moved into `docs/` is still a change to code; the script is tested against real `git`; a test
pins how `ci.yml` uses it; and `gate` waits for the job that decides, so one that did not run fails the gate
instead of skipping the tests unseen.

The documentation set is small on purpose. Each path in it was checked against the tests, and none reads a
file under `docs/`, `wiki/` or `openspec/`, or the three root files. (`tests/integration/test_wiki.py` runs
`check_wiki.py` on the real wiki, but the `docs` job, which runs on every pull request, runs the same script,
and so does it run `check_docs.py` and `openspec validate`.) `.github/` is code even where it is Markdown:
a workflow is code, and the rule is cheaper to keep than to explain. A test that starts to read a documentation
file takes that path out of the set in the same change.

Rejected: `paths-ignore` on the trigger (the required `gate` would never report); a third-party "paths filter"
action (a dependency to pin and trust for thirty lines whose rules could not be unit-tested here); a `grep` in
the workflow, as `container-changes` does (untestable without a runner, and a regular expression is easy to get
wrong on renames and unusual file names); skipping `lint` too (twenty seconds, and the one tier-1 check that
also covers the scripts and the tests).

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
