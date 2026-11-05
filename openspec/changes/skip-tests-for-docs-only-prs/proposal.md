# Proposal: Skip the test jobs on documentation-only pull requests

## Why

`openspec:ci-gate#branch-protection-and-the-gate-job` has said since M0 that documentation-only pull
requests stay mergeable because "path filters skip the test jobs" and the always-running `gate` accepts
a skipped job. No such filter was ever written. Only the `container` job is filtered; every other pull
request runs the whole gate: the `test` matrix on three operating systems and three Python versions,
`coverage`, `determinism`, `statistical`, `benchmark` and `traceability`.

That costs a lot for nothing. On the last run on `main` the slowest Windows leg took about 1h45, and the
documentation-only pull request that brought the roadmap, README and CHANGELOG up to date (#72) waited
about two hours for the same suite to prove that Markdown still parses. Nothing in it could have failed
a test.

## What Changes

- **A `code-changes` job** in `ci.yml` runs `scripts/ci_changes.py` and reports whether the pull request
  touches anything but documentation. `test-fast` runs only when it does, and so does every job that waits
  for `test-fast`: `test`, `statistical`, `determinism`, `coverage`, `benchmark` and `traceability`.
  `lint`, `docs` and `gate` run on every pull request, and a push to `main` runs everything.
- **What counts as documentation is small and was checked against the tests.** `README.md`,
  `CHANGELOG.md` and `CONTRIBUTING.md` at the root, and every file under `docs/`, `wiki/` and `openspec/`.
  No test reads any of them: the unit tests of `scripts/check_docs.py` build their own repositories, and
  `tests/integration/test_wiki.py` runs `scripts/check_wiki.py` on the real wiki, which the `docs` job (on
  every pull request) runs too. Everything else is code, including the Markdown under `.github/` and the
  `LICENSE`, so the list errs towards running the tests.
- **It cannot skip a test that should have run.** The script's default is "code": a push, a missing base
  commit, files that cannot be read, or no changed files all run everything. A rename is read as a
  deletion and an addition, so moving `src/x.py` into `docs/` is a change to code. `gate` waits for
  `code-changes`, so a classifier that did not run fails the gate (its dependants would otherwise all be
  skipped, and `gate` accepts a skipped job).

Milestone: M0 (the `ci-gate` capability), already shipped.

This does not alter identity, normalisation, canonical serialisation, the fold, or the staleness rules, and
needs no schema version bump.

### Rejected

- **`paths-ignore` on the workflow's `pull_request` trigger.** A workflow that a path filter skips never
  reports `gate`, and a required check that never reports blocks the merge for good: the failure the single
  `gate` job exists to prevent (`openspec:ci-gate`, design).
- **A third-party "paths filter" action.** Another action to pin and trust for thirty lines of logic, and its
  rules could not be unit-tested here.
- **A `grep` in the workflow, as `container-changes` does.** It cannot be tested without a runner, and the
  cases that matter (a rename, an unusual file name, a failure to read the diff) are exactly the ones a
  one-line regular expression gets wrong.
- **Skipping `lint` as well.** It takes about twenty seconds, and it is the one tier-1 check that also covers
  the scripts and the tests.

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `ci-gate`: adds the "Documentation-only pull requests skip the test jobs" requirement.

## Impact

- `.github/workflows/ci.yml`: the `code-changes` job; `test-fast` waits for it; `gate` waits for it.
- `scripts/ci_changes.py`, with unit tests (`tests/unit/test_ci_changes.py`) and a test that pins how
  `ci.yml` uses it (`tests/integration/test_ci_docs_only_skip.py`).
- `openspec/specs/ci-gate/design.md` gains the reasoning; `CONTRIBUTING.md` says which pull requests skip.
- A change that edits only the files above gets a faster, narrower gate. A change to anything else, including
  a workflow, a script, a test, the lock file or the Dockerfile, gets exactly the gate it gets today.
