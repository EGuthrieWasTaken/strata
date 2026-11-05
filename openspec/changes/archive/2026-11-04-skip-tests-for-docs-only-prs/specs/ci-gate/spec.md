# ci-gate Specification Delta

## ADDED Requirements

### Requirement: Documentation-only pull requests skip the test jobs

A pull request that changes only documentation MUST skip the test jobs, and every other change MUST run
all of them. A `code-changes` job in `ci.yml` MUST decide which, from the files the pull request changes,
by running `scripts/ci_changes.py`:

- Documentation is `README.md`, `CHANGELOG.md` and `CONTRIBUTING.md` at the repository root, and every
  file under `docs/`, `wiki/` and `openspec/`. Everything else is code: sources, tests, scripts, workflows,
  `pyproject.toml`, `uv.lock`, the `Dockerfile` and what it is built from, and `LICENSE`. A rename MUST be
  read as a deletion and an addition.
- `test-fast` MUST run only when `code-changes` finds a change to code, and every job that waits for
  `test-fast` (`test`, `statistical`, `determinism`, `coverage`, `benchmark` and `traceability`) MUST be
  skipped with it. `lint`, `docs` and `gate` MUST run on every pull request.
- When `code-changes` cannot tell, it MUST report code, so that every job runs: the event is not a pull
  request, the base commit is missing, the changed files cannot be read, or there are none. A push to
  `main` MUST run every job.
- `gate` MUST depend on `code-changes`. The test jobs are skipped when `code-changes` fails, and `gate`
  accepts a skipped job, so a classifier that did not run MUST fail the gate and never skip the tests.
- A file that a test reads MUST NOT be documentation. A change that adds such a test MUST move the file's
  path out of the documentation set in the same pull request.

#### Scenario: Only documentation changes

- **WHEN** a pull request changes `README.md` and a page under `wiki/`
- **THEN** `code-changes` reports no change to code, the test jobs are skipped, `lint` and `docs` run, and `gate` succeeds

#### Scenario: Code and documentation together

- **WHEN** a pull request changes `docs/roadmap.md` and `src/strata/core/ids.py`
- **THEN** every job runs

#### Scenario: A source file moved into the documentation

- **WHEN** a pull request moves `src/strata/mod.py` to `docs/mod.py`
- **THEN** `code-changes` reports a change to code, because the old path is a deletion of code

#### Scenario: The classifier cannot tell

- **WHEN** the base commit is missing or the changed files cannot be read
- **THEN** `code-changes` reports a change to code and every job runs

#### Scenario: The classifier did not run

- **WHEN** `code-changes` fails
- **THEN** `gate` fails, although the test jobs are skipped

#### Scenario: A push to main

- **WHEN** a commit is pushed to `main`
- **THEN** every job runs, whatever the commit changed
