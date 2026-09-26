# cli Specification

## Purpose

The `strata` command-line interface: global options and conventions, exit codes,
the command reference for setup, protocol, literature, screening, and
repository operations, the `strata status` dashboard, non-interactive use, and
the error-message contract.

Rationale and worked examples: [design.md](design.md).

## Requirements

### Requirement: Global options

`strata [global options] <command> [subcommand] [arguments] [options]` MUST
accept these global options:

| Option | Effect |
|---|---|
| `-C <path>` | Run as if started in `<path>` |
| `--why <text>` | Supply the commit rationale non-interactively |
| `--why-file <path>` | Read the rationale from a file |
| `--no-commit` | Perform the operation, stage nothing, leave the tree dirty |
| `--json` | Machine-readable output on stdout; human output moves to stderr |
| `-q` / `-v` / `-vv` | Quieter / verbose / debug |
| `--yes` | Assume yes for confirmations; never bypasses a rationale prompt |
| `--no-color` | Also honoured via `NO_COLOR` |
| `--version`, `--help` | Standard |

#### Scenario: Yes does not bypass the rationale

- **WHEN** a mutating command runs with `--yes` but without `--why` in a non-interactive context
- **THEN** it exits with code 7

#### Scenario: Running elsewhere

- **WHEN** `strata -C ../my-review status` runs
- **THEN** it reports the status of `../my-review`

### Requirement: CLI conventions

- Every command that mutates the repository MUST commit, unless `--no-commit`.
- Every mutating command MUST be safe to interrupt: events are appended and
  fsynced before any derived regeneration, so Ctrl-C loses at most the commit,
  which `strata status` then offers to complete.
- Long operations MUST show progress on stderr and be silent under `-q`.
- `--json` output MUST be a stable, versioned contract; breaking it is a
  minor-version bump.
- Record ids MUST be accepted as any unambiguous prefix, as in git.

#### Scenario: Abbreviated record id

- **GIVEN** exactly one record id starts with `rec_3kq8`
- **WHEN** `strata why rec_3kq8` runs
- **THEN** it resolves to that record

#### Scenario: Ambiguous prefix

- **GIVEN** two record ids start with `rec_3k`
- **WHEN** `strata records show rec_3k` runs
- **THEN** it fails with an error saying the prefix is ambiguous rather than guessing

### Requirement: Exit codes

Commands MUST use these exit codes:

| Code | Meaning |
|---|---|
| 0 | Success |
| 1 | Generic failure |
| 2 | Usage error |
| 3 | Not a `strata` repository |
| 4 | Validation failure (`strata verify` found problems) |
| 5 | Merge/sync conflict requiring human resolution |
| 6 | Schema version too new (`E_SCHEMA_TOO_NEW`) |
| 7 | Refused: the operation would require a rationale and none was available |
| 8 | Refused: a guardrail blocked the operation (use `--force`) |

#### Scenario: Outside a repository

- **WHEN** `strata status` runs in a directory that is not a strata repository
- **THEN** it exits with code 3

#### Scenario: Verification failure

- **WHEN** `strata verify` finds a problem
- **THEN** it exits with code 4

### Requirement: Setup commands

`strata` MUST provide:

| Command | Description |
|---|---|
| `strata init [--title T] [--remote URL]` | Create a repository: layout, `strata.toml`, `.gitattributes`, hooks, merge drivers, initial commit; interactive unless `--title` given |
| `strata clone <url>` | `git clone` plus merge-driver and hook installation plus `strata verify` |
| `strata doctor [--fix]` | Diagnose and repair missing merge drivers, missing hooks, stale cache, git version, unreadable files |
| `strata migrate` | Upgrade the repository to the current schema version |
| `strata config <key> [value]` | Read or set `strata.toml` values |
| `strata actor add\|list\|deactivate` | Manage contributors |

#### Scenario: Initialising and verifying

- **WHEN** `strata init my-review --title "..."` completes
- **THEN** `strata verify` passes on the new repository

#### Scenario: Cloning

- **WHEN** `strata clone <url>` completes
- **THEN** merge drivers and hooks are installed and `strata verify` has passed

### Requirement: Protocol commands

`strata` MUST provide `criteria list|add|edit|retire|diff`,
`search add [--id ID]`, `search list` (all searches with dates and hit counts),
and `moderators add|list|edit`.

#### Scenario: Listing searches

- **WHEN** `strata search list` runs
- **THEN** every recorded search is shown with its execution date and hit count

### Requirement: Literature commands

`strata` MUST provide:

| Command | Description |
|---|---|
| `strata import <file>... --search <id>` | Import exports; `--via`, `--map`, `--format`, `--dry-run` |
| `strata dedup [--review] [--strict]` | Run deduplication; `--review` opens the queue |
| `strata dedup --undo <canonical> <absorbed>` | Reverse a merge |
| `strata records list [--filter EXPR]` | List records; `--format tsv\|json\|csl` |
| `strata records show <id>` | Full record with sources and provenance |
| `strata fix <id> --field <f> --value <v>` | Correct a metadata field, recording a `record-amend` event |

#### Scenario: Correcting a field

- **WHEN** `strata fix rec_3kq8 --field DOI --value 10.1111/x --why "..."` runs
- **THEN** a `record-amend` event records the old and new values and the record id is unchanged

#### Scenario: Dry-run import

- **WHEN** `strata import export.ris --search S-01 --dry-run` runs
- **THEN** it reports what would be imported and writes nothing

### Requirement: Screening commands

`strata` MUST provide `screen <stage> [--filter EXPR] [--limit N]`,
`rescreen [--stage S]`, `adjudicate [--stage S]`,
`assign <stage> --actors a,b [--filter EXPR]`, `irr [--stage S]`, and
`audit --criteria [--sample N]`.

#### Scenario: Limited screening session

- **WHEN** `strata screen title-abstract --limit 50` runs
- **THEN** the session ends after at most 50 records

### Requirement: Repository operation commands

`strata` MUST provide `status`, `sync`, `verify [--fast] [--fix]`,
`log [--criteria] [--stage S] [--actor A]`, `why <id>`,
`diff <ref>..<ref>`, `serve [--port N]` (the local web UI), and `mcp` (the
local, read-only MCP server over stdio).

#### Scenario: Starting the web UI

- **WHEN** `strata serve` runs
- **THEN** the local web UI is served on `127.0.0.1`

### Requirement: The status dashboard

`strata status` MUST be the answer to "where am I?": project title and criteria
version, commit/actor/sync summary, and sections for searches, deduplication,
each screening stage, and (as they exist) extraction and analysis, followed by
a NEXT line. Every line that reports a problem MUST name the command that
addresses it; the tool MUST never report a state the user cannot act on.

#### Scenario: Pending dedup pairs

- **GIVEN** 47 dedup pairs awaiting review
- **WHEN** `strata status` runs
- **THEN** the deduplication line reports 47 pairs and names `strata dedup --review`

#### Scenario: Search without a query

- **GIVEN** a search recorded with `query: "PENDING"`
- **WHEN** `strata status` runs
- **THEN** the searches section flags it with a PRISMA item 7 note

### Requirement: Non-interactive use

Every interactive workflow MUST have a scriptable equivalent, so reviews can be
driven from CI or reproduced from a script (for example
`strata import *.ris --search S-01 --why "..."`,
`strata screen title-abstract --decisions decisions.tsv --why "..."`,
`strata verify --json`).

#### Scenario: Verify from CI

- **WHEN** `strata verify --json` runs in CI
- **THEN** it emits machine-readable results on stdout and the exit code reflects the outcome

### Requirement: Error messages

Every error MUST state what happened, why, and what to do next. Errors MUST NOT
include stack traces unless `-vv` is set. A crash MUST write a full report to
`.strata/crash-<timestamp>.log` and print the path plus the issue tracker URL.

#### Scenario: Ordinary error

- **WHEN** a command fails because of a user-correctable condition
- **THEN** the message explains the cause and names the next command to run, with no stack trace

#### Scenario: Unexpected crash

- **WHEN** an unhandled exception occurs without `-vv`
- **THEN** a crash log is written under `.strata/` and its path and the issue tracker URL are printed

### Requirement: Worked examples in help

Every CLI command's `--help` MUST include at least one worked example.

#### Scenario: Help for dedup

- **WHEN** `strata dedup --help` runs
- **THEN** the output contains at least one example invocation
