# Tasks

## 1. Specification

- [x] 1.1 State in `openspec:git-integration#eliciting-the-rationale` that a refused command changes no file, and that a rejected `--why` is refused at the same point
- [x] 1.2 Reword the "Script without a rationale" scenario; add scenarios for a rejected `--why` and for `--no-commit`

## 2. Implementation

- [x] 2.1 Add `_preflight_rationale` to `strata.cli.main`, sharing the reading and validation of `--why`/`--why-file` with the commit-time prompt
- [x] 2.2 Call it ahead of the first write in every mutating command and mode
- [x] 2.3 Let `dedup` and `import` skip the refusal when a non-mutating check finds nothing to commit
- [x] 2.4 Report an unreadable `--why-file` as an error with exit code 7

## 3. Tests

- [x] 3.1 For every mutating command and mode: run it non-interactively without `--why`, expect exit code 7 and an empty `git status --porcelain`, then expect the same command to succeed with `--why`
- [x] 3.2 A stop-listed `--why` and an unreadable `--why-file` are refused before any write
- [x] 3.3 `--no-commit` and `git.require_rationale = false` need no rationale; the always-required operations still do
- [x] 3.4 An interactive run is still prompted after the work
- [x] 3.5 Read-only modes need no rationale
- [x] 3.6 A rerun with nothing to commit is not refused, and a failing import reports its own error
- [x] 3.7 Tests that asserted the old dirty tree now assert a clean one; usage-error tests supply a rationale
- [x] 3.8 `test_dedup_requires_rationale_when_auto_merging` asserts a clean tree, not a dirty one

## 4. Checks

- [x] 4.1 `openspec validate --all --strict` and `scripts/check_docs.py` pass
