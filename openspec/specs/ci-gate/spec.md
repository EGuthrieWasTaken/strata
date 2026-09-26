# ci-gate Specification

## Purpose

Continuous integration for the `strata` source repository: the tiered
pull-request gate, the always-running `gate` job, branch protection, the
nightly deep checks, specification integrity checks, the flake policy, and
release requirements. The gate was built first because the project's
byte-identity and statistical claims cannot be checked on one laptop.

Rationale and worked examples: [design.md](design.md).

## Requirements

### Requirement: CI files

The source repository MUST carry `.github/workflows/ci.yml` (the pull-request
gate), `docs.yml` (specification integrity), `nightly.yml` (scheduled deep
checks), `release.yml` (tag-triggered build, sign, publish, SBOM), and
`codeql.yml`, plus `PULL_REQUEST_TEMPLATE.md`, `ISSUE_TEMPLATE/bug.yml`,
`ISSUE_TEMPLATE/parser.yml` (which asks for the failing export file and whether
it may be redistributed as a fixture), and `dependabot.yml`.

#### Scenario: Reporting a parser bug

- **WHEN** a user opens a parser issue
- **THEN** the template asks them to attach the export and say whether it may be redistributed as a test fixture

### Requirement: Tiered pull-request gate

Every pull request MUST run these jobs:

| Tier | Job | Budget | Blocking |
|---|---|---|---|
| 1 | `lint` — `ruff check`, `ruff format --check`, `mypy --strict` | < 2 min | yes |
| 1 | `test-fast` — unit + property, Linux, one Python version | < 3 min | yes |
| 2 | `test` — full suite on the 3 OS x 3 Python matrix | < 15 min | yes |
| 2 | `statistical` — the committed `metafor` fixtures | < 5 min | yes |
| 2 | `determinism` — pipeline twice, byte-compare, randomised `PYTHONHASHSEED` | < 10 min | yes |
| 2 | `coverage` — global floors, 100%-branch modules, diff coverage | < 2 min | yes |
| 2 | `docs` — specification integrity | < 1 min | yes |
| 3 | `benchmark` — scale targets at 1k/10k | < 10 min | warn only |
| 3 | `codeql` | — | warn |

#### Scenario: Non-deterministic output

- **WHEN** a pull request introduces output that differs between two runs
- **THEN** the `determinism` job fails and the merge is blocked

### Requirement: Workflow hygiene

Workflows MUST:

- Trigger on `pull_request`, never `pull_request_target`; jobs needing secrets
  MUST no-op on forks and MUST NOT be required checks.
- Use `concurrency: group: ci-${{ github.ref }}` with `cancel-in-progress: true`.
- Set `timeout-minutes` on every job.
- Cache the dependency environment keyed on the lock-file hash only.
- Pin third-party actions to a commit SHA, not a tag.
- Upload failure artefacts: differing files and a diff for `determinism`, the
  pytest report for `test`, the timing JSON for `benchmark`.

#### Scenario: Action pinned by tag

- **WHEN** a workflow references a third-party action by a moving tag
- **THEN** the change violates this requirement and must pin the commit SHA instead

### Requirement: Branch protection and the gate job

`main` MUST be protected with strict required status checks, at least one
approving review (waived on a solo project, the checks are not), linear
history, no force-push, no deletion, and administrators included. One
always-running `gate` job MUST depend on every tier-1 and tier-2 job and assert
each finished `success` or `skipped`; `gate` is the required check, so
documentation-only pull requests stay mergeable while no check that should have
run can be skipped.

#### Scenario: Documentation-only pull request

- **WHEN** a pull request changes only documentation and path filters skip the test jobs
- **THEN** `gate` succeeds and the pull request can merge

#### Scenario: A tier-2 job fails

- **WHEN** `statistical` fails
- **THEN** `gate` fails and the pull request cannot merge

### Requirement: Nightly checks

A nightly workflow MUST run `metafor-live` (regenerate statistical fixtures and
fail on drift), `fuzz`, `benchmark-50k` (blocking), `audit` (`pip-audit` and
dependency review), and `cold-install` (install the published artefact from
scratch on each platform and run the quickstart). Nightly failures MUST open an
issue automatically.

#### Scenario: Nightly failure

- **WHEN** a nightly job fails
- **THEN** an issue is opened automatically

### Requirement: Specification integrity checks

`docs.yml` MUST verify on every pull request that:

1. Every relative Markdown link in `README.md`, `docs/`, `openspec/`, and
   `.github/` resolves to an existing file.
2. Every `#anchor` in those links resolves to an existing heading in the target
   file.
3. Every fenced `toml`, `yaml`, and `json` block in `openspec/` and `docs/`
   parses.
4. Every capability under `openspec/specs/` has both a `spec.md` and a
   `design.md` and is listed in `openspec/README.md`, and every capability
   listed there exists.
5. Every `openspec:<capability>` and `openspec:<capability>#<requirement-slug>`
   reference in the repository resolves to an existing capability and
   requirement, in `openspec/specs/` or in a change's delta specs.
6. No file outside the historical milestone plans and the changelog refers to
   the retired long-form specification directory.
7. The OpenSpec specs and change proposals under `openspec/` pass
   `openspec validate --all --strict`.

#### Scenario: Renamed requirement

- **WHEN** a requirement is renamed and a code comment still cites its old slug
- **THEN** the `docs` job fails naming the file, line, and unresolved reference

#### Scenario: Renumbered section

- **WHEN** a heading is renamed and another document still links to its old anchor
- **THEN** the `docs` job fails naming the broken anchor

#### Scenario: Requirement without a scenario

- **WHEN** a pull request adds an OpenSpec requirement with no scenario
- **THEN** the `docs` job fails

#### Scenario: Capability without a design note

- **WHEN** a pull request adds `openspec/specs/<capability>/spec.md` without a `design.md`
- **THEN** the `docs` job fails

### Requirement: Flake policy

Blanket retry plugins MUST NOT be configured. A job MAY be re-run at most once,
and only when it died before any test body executed. Skipping, `xfail`-ing, or
quarantining a test to get a green build is forbidden; a nondeterministic test
is a bug in the test and MUST be seeded.

#### Scenario: Intermittent failure

- **WHEN** a test fails intermittently
- **THEN** it is fixed or seeded, never marked `xfail` or retried to green

### Requirement: Release requirements

A release MUST additionally require a green nightly, a clean full suite on all
platforms, updated documentation, a `CHANGELOG` entry, signed artefacts, a
published SBOM, and `cold-install` green on the release candidate.

#### Scenario: Missing changelog

- **WHEN** a release is attempted without a `CHANGELOG` entry
- **THEN** the release is not made
