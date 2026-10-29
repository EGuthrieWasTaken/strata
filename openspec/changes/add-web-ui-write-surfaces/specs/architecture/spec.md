# Spec Delta

## ADDED Requirements

### Requirement: Mutating operations are shared services

An operation that writes to a review and commits (recording a search, importing, correcting a record, adding a criterion, assigning, recording a retrieval or a study decision) MUST be implemented once in `core` and called by every surface that offers it. A surface MUST add only argument handling, rationale elicitation, and presentation.

#### Scenario: Same search from either surface

- **GIVEN** two identical repositories
- **WHEN** a search is recorded with `strata search add` in one and through the web UI in the other
- **THEN** the written files are byte-identical and the commits carry the same message and trailers

#### Scenario: A surface cannot skip the lock

- **WHEN** a web request and a CLI command both import into one repository at the same time
- **THEN** one waits for the other and both imports are committed, in either order

#### Scenario: Output is unchanged

- **GIVEN** a command that was moved onto the shared operation
- **WHEN** it runs with the same arguments as before the move
- **THEN** its output, exit code, files and commit message are identical to what it produced before

## MODIFIED Requirements

### Requirement: Concurrency and locking

The web server and the CLI MUST be able to run simultaneously against one
repository. A single advisory lock file `.strata/lock` MUST guard mutating
operations for the duration of append plus commit, with a 30-second timeout and
a clear message naming the holding process. A lock left by a process that is no
longer running MUST be reclaimed, and the reclaim MUST be reported. Readers MUST
NOT take the lock. Appends MUST be complete-line `O_APPEND` writes (atomic under
`PIPE_BUF` on POSIX), longer lines written via temp file and rename; on Windows
appends are serialised through the lock.

#### Scenario: Lock held by another process

- **GIVEN** `strata serve` holds the lock while committing
- **WHEN** a CLI mutating command cannot acquire the lock within 30 seconds
- **THEN** it fails with a message naming the holding process

#### Scenario: Holder crashed

- **GIVEN** a lock file naming a process that has exited
- **WHEN** a mutating command runs
- **THEN** it reclaims the lock, says so, and completes without waiting out the timeout

#### Scenario: Holder still running

- **GIVEN** a lock file naming a process that is running
- **WHEN** a mutating command runs
- **THEN** the lock is not reclaimed
