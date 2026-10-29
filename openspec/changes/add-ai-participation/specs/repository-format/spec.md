# Spec Delta

## MODIFIED Requirements

### Requirement: Format versioning

`.strata/schema-version` MUST hold a single integer, and `strata.toml` MUST
record the `strata` version that created the repository.

- A tool reading a repository with a **higher** schema version than it supports
  MUST refuse to operate and say so (`E_SCHEMA_TOO_NEW`, exit code 6).
- A tool MUST operate on every schema version in its supported range. For a
  repository below the newest version it MUST offer `strata migrate`, in
  `strata status` and in the error of any command that needs the newer
  version, and MUST NOT migrate implicitly or on every command.
- `strata migrate` MUST perform the upgrade as an ordinary commit with a
  generated message. Migrations MUST be forward-only, idempotent, and MUST NOT
  rewrite history.
- Version 2 is the format that permits AI participation
  (`openspec:ai-participation`). A repository enters it only through
  `strata migrate` or `strata ai enable`, which runs it, and a repository that
  never enables AI MAY stay at version 1 indefinitely.
- Adding an optional field to an event body is not a schema bump. Changing the
  meaning of an existing field, the normalisation rules, the fold, or the
  canonical serialisation is.

#### Scenario: Repository from a newer strata

- **GIVEN** `.strata/schema-version` contains `2` and the tool supports up to `1`
- **WHEN** any command runs
- **THEN** it refuses with `E_SCHEMA_TOO_NEW` and exits with code 6, so a tool that predates AI participation cannot fold agent events as a person's

#### Scenario: Repository from an older strata

- **GIVEN** a repository at schema version 1 and a tool that supports versions 1 and 2
- **WHEN** a command runs
- **THEN** the command runs as before, `strata status` mentions that format 2 is available, and the repository is not modified

#### Scenario: A feature that needs version 2

- **GIVEN** a repository at schema version 1
- **WHEN** `strata actor add --kind agent` is run
- **THEN** it is refused with a message naming `strata ai enable` and `strata migrate`

#### Scenario: Migrating

- **WHEN** `strata migrate` is run on a version 1 repository with a rationale
- **THEN** `.strata/schema-version` becomes `2` in one commit

#### Scenario: Migration run twice

- **WHEN** `strata migrate` is run twice
- **THEN** the second run makes no changes and creates no commit
