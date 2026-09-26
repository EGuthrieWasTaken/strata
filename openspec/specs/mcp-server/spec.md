# mcp-server Specification

## Purpose

`strata mcp`, a local Model Context Protocol server over stdio that lets an
MCP-aware client query a review repository's status, staleness, provenance,
records, and history — as a fourth thin presentation layer that never records a
screening or criteria decision on its own.

Rationale and worked examples: [design.md](design.md).

## Requirements

### Requirement: Local stdio server

`strata mcp` MUST run an MCP server over stdio, spawned locally by an MCP-aware
client against a local clone, with no new infrastructure and no dependency on a
hosted deployment.

#### Scenario: Client spawns the server

- **WHEN** an MCP-aware client launches `strata mcp` in a review repository
- **THEN** the server speaks MCP over stdin/stdout and lists its tools

### Requirement: Read, analysis, and preview tools only

The server MUST expose read, analysis, and preview tools only: `status`, `why`,
`log`, `records` (using the filter language), `criteria_diff`, and
`preview_criterion_change_impact` (the same non-mutating preview that backs the
web criteria editor). These tools MUST NOT write to the repository or commit.

#### Scenario: Previewing a criteria change

- **WHEN** a client calls `preview_criterion_change_impact` for a tightened `EXC-03`
- **THEN** it returns the stale-decision counts and the repository and git history are unchanged

#### Scenario: Filtering records

- **WHEN** a client calls `records` with `stale == true and fulltext == 'include'`
- **THEN** it returns exactly the records the CLI's `records list --filter` returns for the same expression

### Requirement: No autonomous decisions

An MCP tool MUST NOT commit a screening or criteria decision on its own. A future
write-capable tool, if ever added, MUST only produce a proposal (a drafted
decision or rationale) for a human to review and execute themselves.

#### Scenario: Listing tools

- **WHEN** a client lists the server's tools
- **THEN** none of them records a screening decision, adjudication, or criteria change

### Requirement: No domain logic in the MCP layer

The MCP server MUST contain no domain logic beyond argument marshalling into
existing `core`/`protocol` functions — the same relationship the web routes and
CLI have to the service layer.

#### Scenario: Status parity

- **WHEN** a client calls the `status` tool
- **THEN** the result is produced by the same function that backs `strata status`
