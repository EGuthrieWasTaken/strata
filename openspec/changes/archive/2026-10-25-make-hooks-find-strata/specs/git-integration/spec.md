# git-integration Specification Delta

## MODIFIED Requirements

### Requirement: Versioned hooks

`strata init` MUST set `core.hooksPath = .strata/hooks` so hooks are versioned
and every collaborator gets them on clone:

| Hook | Action | Failure |
|---|---|---|
| `pre-commit` | `strata verify --fast` | blocks the commit |
| `commit-msg` | validate `Strata-` trailers when `commit_style = "structured"` | blocks the commit |
| `post-merge` | regenerate derived files, then `strata verify` | warns |
| `post-checkout` | invalidate `.strata/cache` if HEAD moved | never fails |

All hooks MUST be skippable via `STRATA_SKIP_HOOKS=1` and MUST print that the
variable exists when they block an operation.

The hooks run `strata` from `PATH`. A hook that cannot find it MUST say so, and
where it would block (`pre-commit`, `commit-msg`) it MUST name `STRATA_SKIP_HOOKS=1`;
`post-merge` and `post-checkout` MUST NOT fail the operation. When `strata` runs git
itself, the hooks that git triggers MUST be able to find that same `strata`, even if
it was started by a path that is not on `PATH`.

#### Scenario: Hook blocks a commit

- **WHEN** the pre-commit hook blocks a commit because verification failed
- **THEN** its message mentions `STRATA_SKIP_HOOKS=1`

#### Scenario: Recovery bypass

- **WHEN** a commit is made with `STRATA_SKIP_HOOKS=1`
- **THEN** no strata hook runs

#### Scenario: strata is not on PATH

- **WHEN** a hook runs in an environment where `strata` is not on `PATH`
- **THEN** the pre-commit and commit-msg hooks block with a message that `strata` was not found and that mentions `STRATA_SKIP_HOOKS=1`
- **AND** the post-merge and post-checkout hooks warn and succeed

#### Scenario: Started by absolute path

- **WHEN** `/opt/venv/bin/strata actor add sam "Sam"` runs and `/opt/venv/bin` is not on `PATH`
- **THEN** its commit succeeds, with the hooks run by that same `strata`
