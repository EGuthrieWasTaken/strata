# architecture Specification

## Purpose

The normative seams of the `strata` codebase: module boundaries and their
invariants, the derived-state cache, concurrency and locking, plugin interfaces
(including the reorder-only constraint on screening prioritisers), the optional
`metafor` engine, and deliberate dependency choices such as hand-written
deterministic SVG.

Rationale and worked examples: [design.md](design.md).

## Requirements

### Requirement: Module boundaries

The source tree MUST keep these module responsibilities: `cli` (Typer commands,
argument parsing, output formatting only), `web` (FastAPI app, templates,
static assets), `mcpserver` (MCP tool marshalling only), `core` (repository,
events, fold, ids, canonical serialisation, derived views), `protocol`
(criteria, searches, moderators, staleness), `ingest` (parsers, profiles,
enrichment), `dedup`, `extract`, `stats`, `report`, `gitio`, and `schemas`
(shipped JSON Schema data).

#### Scenario: New parser

- **WHEN** a contributor adds a parser for a new export format
- **THEN** it lives under `ingest/parsers/` and is registered through the `Parser` interface

### Requirement: The fold is pure

`core.fold` MUST be pure: events in, state out, with no I/O, no clock, no
randomness, and no git.

#### Scenario: Folding in isolation

- **WHEN** the fold is called with an in-memory list of events
- **THEN** it returns state without touching the filesystem, the clock, or git

### Requirement: Only gitio invokes git

`gitio` MUST be the only module that invokes git; everything else operates on
the working tree.

#### Scenario: Searching for git invocations

- **WHEN** the source tree is searched for subprocess calls to `git`
- **THEN** they occur only in `gitio`

### Requirement: Presentation layers contain no domain logic

`cli`, `web`, and `mcpserver` MUST contain no domain logic: they are thin
adapters over the same service layer in `core`/`protocol`, which guarantees
they cannot diverge in behaviour.

#### Scenario: Screening from two surfaces

- **WHEN** the same decision is recorded once via the CLI and once via the web UI on identical repositories
- **THEN** the resulting events and derived views are identical apart from ids and timestamps

### Requirement: Statistics know nothing of the repository

`stats` MUST have no knowledge of the repository: it takes arrays and options
and returns numbers.

#### Scenario: Using stats as a library

- **WHEN** a stats function is called with plain arrays
- **THEN** it computes its result without a repository present

### Requirement: Parsers never write events

`ingest.parsers` MUST NOT write events; they parse bytes to record dicts and
report failures, so parsers can be fuzzed in isolation.

#### Scenario: Fuzzing a parser

- **WHEN** a parser is invoked on arbitrary bytes
- **THEN** it returns records and parse errors and has no side effects on any repository

### Requirement: Derived-state cache is an optimisation only

`.strata/cache/` MAY hold the fold result keyed by the digest of the event-log
inputs. It MUST be gitignored and never authoritative; it MUST be invalidated
when any event file's digest changes, on `post-checkout`, and on schema version
change; and it MUST be deletable at any time with no loss. The fold MUST be fast
enough to run without it (under 5 seconds for 50,000 records).

#### Scenario: Corrupt cache

- **GIVEN** a corrupted file in `.strata/cache/`
- **WHEN** any command runs
- **THEN** the cache is ignored or rebuilt and the command succeeds

### Requirement: Concurrency and locking

The web server and the CLI MUST be able to run simultaneously against one
repository. A single advisory lock file `.strata/lock` MUST guard mutating
operations for the duration of append plus commit, with a 30-second timeout and
a clear message naming the holding process. Readers MUST NOT take the lock.
Appends MUST be complete-line `O_APPEND` writes (atomic under `PIPE_BUF` on
POSIX), longer lines written via temp file and rename; on Windows appends are
serialised through the lock.

#### Scenario: Lock held by another process

- **GIVEN** `strata serve` holds the lock while committing
- **WHEN** a CLI mutating command cannot acquire the lock within 30 seconds
- **THEN** it fails with a message naming the holding process

### Requirement: Plugin boundaries

The following interfaces MUST be defined, with only built-in implementations in
v1: `Parser`, `Enricher`, `Prioritiser`, `Engine`, `Instrument`, `Renderer`. A
`Prioritiser` MUST only reorder the screening queue; it can never make or
withhold a decision, and this constraint MUST hold for any future
implementation.

#### Scenario: Prioritiser output

- **WHEN** a prioritiser is applied to a screening queue
- **THEN** the queue contains exactly the same records in a possibly different order, and no decision events are produced

### Requirement: Optional metafor engine

`engine = "metafor"` MUST shell out to `Rscript` with a JSON contract on stdin
and stdout. It MUST be optional and detected at runtime, and its absence MUST
never be an error unless it is explicitly selected.

#### Scenario: R not installed

- **GIVEN** `engine = "native"` and no R installation
- **WHEN** any command runs
- **THEN** nothing fails because R is missing

### Requirement: Deterministic plotting and small dependencies

Dependencies MUST be kept deliberately small. Committed and verified plots MUST
be produced by a hand-written deterministic SVG emitter; `matplotlib` MAY be
offered as an optional renderer but MUST NOT produce output that is committed
and verified.

#### Scenario: Plot regeneration

- **WHEN** a committed forest plot is regenerated on another platform
- **THEN** the SVG is byte-identical
