# Tasks

## 1. Specification

- [x] 1.1 Add `openspec:ci-gate#documentation-only-pull-requests-skip-the-test-jobs`: what is documentation, what is skipped, and the rules that make skipping safe (report code when unsure, read a rename as a deletion and an addition, `gate` waits for the classifier)
- [x] 1.2 Add the reasoning, and the rejected alternatives, to `openspec/specs/ci-gate/design.md`

## 2. Implementation

- [x] 2.1 Add `scripts/ci_changes.py` (standard library only): the documentation set, `git diff --name-only --no-renames -z`, and a default of "code" for everything it cannot classify
- [x] 2.2 Add the `code-changes` job to `ci.yml`; make `test-fast` wait for it and run only when it reports code; make `gate` wait for it

## 3. Tests

- [x] 3.1 Classification: every documentation path, a long list of near misses that must be code (nested `README.md`, `Docs/`, `docsy/`, a file named `wiki`, `.github/` Markdown), mixed changes, no changes
- [x] 3.2 The decision: a push, a missing base, a failing `git`, and no files all run everything; the log names the code files and shortens a long list
- [x] 3.3 Against real `git`: a documentation-only change, a source change, a workflow-only change, a source file moved into `docs/`, a documentation file moved out, a deleted source file, non-ASCII file names, an unknown base commit; `main()` appends to `$GITHUB_OUTPUT`
- [x] 3.4 `ci.yml`'s wiring: the job's output and inputs, `test-fast` gated, every other test job waiting for `test-fast` with no condition of its own, `lint` ungated, `gate` waiting for the classifier, and no job but the container and gate jobs able to run without reaching it
- [x] 3.5 Each guarantee fails when broken: dropping `--no-renames`, dropping `-z`, reporting "skip" when the diff cannot be read, a test job that no longer waits for `test-fast`, a gate that forgets the classifier, a job given `if: always()`

## 4. Checks

- [x] 4.1 `ruff check`, `ruff format --check` and `mypy src` pass, and `scripts/check_docs.py` and `openspec validate --all --strict` pass with the new change
- [x] 4.2 Observe it on GitHub: a pull request that changes only documentation skips the test jobs and `gate` succeeds, and the branch protection accepts the skipped jobs. The first documentation-only pull request after this merges is the check; archive this change then (`openspec archive skip-tests-for-docs-only-prs`), which is itself such a pull request

## Notes

Written and tested locally, then seen working on GitHub (4.2). The pull request that added this change
changed `ci.yml`, a script and tests, so it ran the whole gate and could not show the skip; the pull request that
archived it (#75, only files under `openspec/`) did.

- **What #75 showed.** `code-changes` reported no change to code in 4 seconds. `test-fast`, `test`, `statistical`,
  `determinism`, `coverage`, `benchmark`, `traceability` and `container` were skipped; `lint`, `docs` and `gate`
  succeeded, `gate` in 2 seconds. The pull request was mergeable (`clean`) about a minute after it was opened;
  #72, a documentation-only pull request before this change, waited about two hours. The skipped matrix
  reported no `test (os, python)` checks and the pull request was still `clean`, so the branch protection on
  `main` waits for `gate` and `docs` and not for the individual test checks.
- Replaying the classifier over the last 20 commits on `main`, one (#72, the documentation update) would have
  skipped the test jobs; the other 19 change code or configuration. A commit titled "docs:" that also edited
  `.github/PULL_REQUEST_TEMPLATE.md` runs everything, by design: `.github/` is code.
