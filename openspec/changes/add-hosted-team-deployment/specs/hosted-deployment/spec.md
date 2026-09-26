# hosted-deployment Specification

## Purpose

Running `strata serve` as a shared, always-on team instance: automatic sync with
a git remote, per-user authentication mapped to actor handles, isolation
between teams' repositories, and remote access to the read-only MCP tools.

## ADDED Requirements

### Requirement: Automatic git sync loop

In hosted mode, the server MUST pull before serving a page that reads
repository state (or on a short poll) and MUST push after each commit, retrying
with exponential backoff. A merge conflict MUST be surfaced to the user as a
clear in-app message and MUST NOT be resolved silently or lost.

_Source: `docs/spec/15-roadmap.md` M5.1_

#### Scenario: Concurrent edits

- **WHEN** two team members edit concurrently through the hosted UI
- **THEN** their work either merges cleanly or a conflict is surfaced explicitly, and neither member's work is silently dropped

#### Scenario: Remote unreachable

- **WHEN** a push fails because the remote is unreachable
- **THEN** the server retries with exponential backoff and tells the user if it ultimately fails

### Requirement: Per-user authentication

Hosted mode MUST authenticate each user with a GitHub identity (OAuth device
flow or a personal access token) and map it to a `strata` actor handle, so every
commit and decision is attributed to the real reviewer, not to the instance.

_Source: `docs/spec/15-roadmap.md` M5.1_

#### Scenario: Attributed decision

- **GIVEN** GitHub user `samokonkwo` mapped to actor `sam`
- **WHEN** they record a screening decision through the hosted UI
- **THEN** the event's actor is `sam`

#### Scenario: Unmapped identity

- **WHEN** an authenticated GitHub user with no actor mapping tries to record a decision
- **THEN** the request is refused

### Requirement: Multi-tenancy isolation

One hosted instance MUST be able to serve more than one review repository, and
one team's repository data MUST never be reachable through another team's
session.

_Source: `docs/spec/15-roadmap.md` M5.1_

#### Scenario: Cross-team request

- **WHEN** a member of team A requests a record URL belonging to team B's repository
- **THEN** the request is refused and no team B data is returned

### Requirement: Remote MCP access

The read-only MCP tool set MUST be reachable over MCP's HTTP transport in hosted
mode, behind the same per-user authentication, and MUST remain unable to commit
a screening or criteria decision.

_Source: `docs/spec/15-roadmap.md` M5.1, M2.1_

#### Scenario: Unauthenticated MCP client

- **WHEN** an MCP client connects over HTTP without valid credentials
- **THEN** the connection is refused
