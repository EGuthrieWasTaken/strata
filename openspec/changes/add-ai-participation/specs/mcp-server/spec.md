# Spec Delta

## RENAMED Requirements

- FROM: `### Requirement: Read, analysis, and preview tools only`
- TO: `### Requirement: Read, analysis, and preview tools`

## MODIFIED Requirements

### Requirement: Read, analysis, and preview tools

The server MUST always expose read, analysis, and preview tools: `status`, `why`,
`log`, `records` (using the filter language), `criteria_diff`, and
`preview_criterion_change_impact` (the same non-mutating preview that backs the
web criteria editor), together with the reads an agent needs to do the work the
review's AI policy allows (the active criteria, the agent's own screening queue,
extraction and risk-of-bias forms, the retrieval queue, study suggestions, and
the AI policy). These tools MUST NOT write to the repository or commit.

#### Scenario: Previewing a criteria change

- **WHEN** a client calls `preview_criterion_change_impact` for a tightened `EXC-03`
- **THEN** it returns the stale-decision counts and the repository and git history are unchanged

#### Scenario: Filtering records

- **WHEN** a client calls `records` with `stale == true and fulltext == 'include'`
- **THEN** it returns exactly the records the CLI's `records list --filter` returns for the same expression

#### Scenario: Reading the policy

- **WHEN** a client calls the policy tool
- **THEN** it learns whether AI participation is enabled, the mode for each kind of work, and the models the review accepts

## REMOVED Requirements

### Requirement: No autonomous decisions

**Reason**: The write-capable tool this requirement anticipated is now specified. Its concern, that an agent
could record a decision unsupervised and unattributed, is met by `openspec:ai-participation`: writes are off
unless a review's reviewers enable them, are recorded as suggestions or as the registered agent's own events,
and always name the model and the person who invoked it.

**Migration**: Reviews that want the old behaviour change nothing: AI participation is off by default and the
server then lists read tools only. Reviews that want suggestions without effect set the relevant kinds of work
to `suggest`.

## ADDED Requirements

### Requirement: Write tools

When AI participation is enabled, the server MUST offer a write tool for each operation the command line can
write, except the operations in `openspec:ai-participation#operations-an-agent-cannot-perform`. Each MUST
require the agent's model and a rationale, and MUST obey the review's policy for its kind of work.

#### Scenario: Tools offered

- **GIVEN** AI participation is enabled
- **WHEN** a client lists the tools
- **THEN** it includes writes for screening, extraction, risk of bias, retrieval, study grouping, deduplication, record correction, searches and imports, criteria, adjudication and analysis
- **AND** none for policy, actors, assignment, configuration, initialisation, cloning, repair or synchronisation

#### Scenario: Missing rationale

- **WHEN** a write tool is called without a rationale
- **THEN** it is refused and nothing is recorded

#### Scenario: Result names its effect

- **WHEN** a write tool succeeds
- **THEN** the result says whether a suggestion or an event was recorded, and gives its id

### Requirement: The invoking person

`strata mcp --as <handle>` MUST name the active, non-observer person on whose behalf agents act, and that
handle MUST be recorded as `invoked_by`. Without `--as` the server MUST use the review's only active person
if there is exactly one; otherwise it MUST offer no write tools and say why.

#### Scenario: Naming the person

- **WHEN** a client launches `strata mcp --as ada`
- **THEN** every agent event it causes records `invoked_by: "ada"`

#### Scenario: Several people, no `--as`

- **GIVEN** three active people
- **WHEN** `strata mcp` is launched without `--as`
- **THEN** only read tools are offered and the policy tool says `--as` is needed

#### Scenario: Observer

- **WHEN** `strata mcp --as` names an observer
- **THEN** no write tool is offered

### Requirement: Reads honour blinding

While `blind_reviewers` is set, no read tool and no write result MUST reveal another reviewer's opinion on a
record, or that a record is in conflict, to the agent or to the person invoking it, beyond the aggregate
counts the dashboard shows. The agent's queue MUST contain only records assigned to it that it has not yet
decided.

#### Scenario: Colleague already decided

- **GIVEN** `blind_reviewers` is set and `sam` has excluded a record assigned to the agent
- **WHEN** the agent reads its queue and the record
- **THEN** nothing indicates `sam`'s decision

#### Scenario: Result of a decision

- **WHEN** an agent records a decision on a record another reviewer has decided differently
- **THEN** the result does not say that they disagree

### Requirement: File arguments are confined

A tool that takes a file path MUST resolve links and accept the path only if it lies inside the repository
or inside a directory the person allowed with `--allow-dir` when starting the server.

#### Scenario: Path outside

- **WHEN** an import tool is given `../../.ssh/id_rsa`
- **THEN** it is refused and nothing is read

#### Scenario: Allowed directory

- **GIVEN** the server was started with `--allow-dir ~/exports`
- **WHEN** an import tool is given a file in `~/exports`
- **THEN** it is accepted for the import the policy allows

### Requirement: Instructions state the policy

The instructions the server gives a client MUST describe the review's AI policy and that every write is
attributed to a named model and person, and MUST NOT state that writes are impossible or reserved for people
when they are enabled.

#### Scenario: Disabled review

- **GIVEN** AI participation is not enabled
- **WHEN** a client connects
- **THEN** the instructions say the tools are read-only for this review

#### Scenario: Enabled review

- **GIVEN** screening is `suggest` and retrieval is `count`
- **WHEN** a client connects
- **THEN** the instructions name those modes
