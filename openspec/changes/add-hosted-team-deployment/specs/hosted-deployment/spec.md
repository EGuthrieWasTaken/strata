# hosted-deployment Specification

## Purpose

A self-hosted `strata` instance that a team runs so collaborators can review in a
browser with their own credentials, backed by git repositories that stay in step
with a shared remote — so hosted and local collaborators can work on the same
review at once.

## ADDED Requirements

### Requirement: Git is always the backend

Every hosted project MUST be an ordinary `strata` review repository (a git
working copy in the standard format) and MAY be configured with a git remote.
The instance MUST NOT store review data anywhere else, and a project MUST always
be retrievable in full by cloning its repository.

#### Scenario: Leaving the instance

- **GIVEN** a hosted project with a configured remote
- **WHEN** a member clones the remote and runs `strata verify` locally
- **THEN** verification passes and the clone contains every decision recorded on the instance

### Requirement: Projects and instance state

`strata host` MUST serve multiple projects from one instance. Instance state —
accounts, memberships, sessions, the sign-in log, and secrets — MUST be stored
separately from every review repository and MUST never be committed to one.

#### Scenario: Two projects on one instance

- **WHEN** an administrator adds two projects to an instance
- **THEN** each has its own working copy and neither repository contains any account, session, or credential data

### Requirement: Per-user authentication

Each person MUST sign in with their own credentials. The instance MUST support
built-in local accounts with passwords hashed using a memory-hard function
(Argon2id), and MAY support OpenID Connect providers. Shared or anonymous logins
MUST NOT be able to record decisions.

#### Scenario: Local account

- **GIVEN** an administrator has created an account for `sam`
- **WHEN** `sam` signs in with their password
- **THEN** a session is issued, and the stored credential is an Argon2id hash, not the password

#### Scenario: No account

- **WHEN** an unauthenticated request tries to record a screening decision
- **THEN** it is refused

### Requirement: Membership maps users to actors

A user MUST be able to act in a project only through a membership that maps them
to exactly one actor handle declared in that project's `strata.toml` and to a
role. Every event and commit made for that user MUST carry that actor handle.
Roles MUST be enforced on every request: observers are read-only, and only
adjudicators may resolve conflicts.

#### Scenario: Attributed decision

- **GIVEN** user `sam.okonkwo` is a member of a project as actor `sam` with role `screener`
- **WHEN** they record a screening decision in the browser
- **THEN** the event's `actor` is `sam` and the commit's author is `sam`'s name and email from `strata.toml`

#### Scenario: Observer attempts a decision

- **GIVEN** a member with role `observer`
- **WHEN** they submit a screening decision
- **THEN** the request is refused and nothing is written

### Requirement: Commit attribution

Commits the instance makes for a user MUST have the acting actor's name and
email as the git author, the instance's configured identity as the git
committer, and the standard `Strata-` trailers including `Strata-Actor`.

#### Scenario: Reading history

- **WHEN** `git log --format='%an | %cn'` is run on a hosted project
- **THEN** each commit shows the reviewer as author and the instance as committer

### Requirement: Automatic git sync loop

For a project with a remote, the instance MUST fetch and merge before serving a
page that reads repository state when its last fetch is older than a configured
interval, and MUST push after each commit, retrying failures with exponential
backoff. Merges MUST follow `strata sync`'s algorithm. A genuine conflict in a
human-authored file MUST block pushes for that project and be presented to
members with the lead role in domain terms; it MUST NOT be resolved silently or
dropped. The project dashboard MUST show when it last synced.

#### Scenario: Concurrent hosted edits

- **WHEN** two members screen concurrently through the instance
- **THEN** both members' decisions are committed and pushed, with no conflict

#### Scenario: Remote unreachable

- **WHEN** a push fails because the remote is unreachable
- **THEN** the instance retries with backoff, the dashboard reports the failure, and no decision is lost

#### Scenario: Conflicting criterion edits

- **GIVEN** a lead edited `EXC-03` on the instance while a local collaborator pushed a different edit to `EXC-03`
- **WHEN** the instance syncs
- **THEN** pushes for the project stop and the lead is shown both definitions with keep-mine, keep-theirs, and edit options

### Requirement: Hosted and local collaborators interoperate

A collaborator running `strata` locally and syncing with a project's remote MUST
be able to work on the same review at the same time as users of the instance,
with no manual conflict resolution for screening, adjudication, or dedup
decisions.

#### Scenario: Mixed topology

- **GIVEN** `ethan` screens on the instance and `sam` screens on a laptop with `strata sync`
- **WHEN** both have synced
- **THEN** the instance and `sam`'s clone hold identical event logs containing both reviewers' decisions

### Requirement: Blinding between users

While `blind_reviewers` is set, the instance MUST NOT render, return, or expose
through any interface (including MCP) another reviewer's opinion on a record to
a user who has not yet recorded their own decision on it at that stage.

#### Scenario: Colleague decided first

- **GIVEN** `sam` has excluded a record and `ethan` has not decided it
- **WHEN** `ethan` views the record, the record list, or queries it through MCP
- **THEN** nothing indicates `sam`'s decision

### Requirement: Isolation between projects

Data from one project MUST never be returned to a user who is not a member of
that project, through any route, export, or MCP tool.

#### Scenario: Cross-project request

- **WHEN** a member of project A requests a record URL belonging to project B
- **THEN** the request is refused and no project B data is returned

### Requirement: Hosted security baseline

In hosted mode the instance MUST require TLS (it MAY accept plain HTTP only when
explicitly started for local testing), issue `Secure`, `HttpOnly`,
`SameSite=Strict` session cookies that expire, rate-limit sign-in attempts, log
every sign-in in instance state, validate `Host` and `Origin` against its
configured public URL, and keep CSRF protection on every mutating request. The
local-mode inactivity exit MUST be disabled.

#### Scenario: Password guessing

- **WHEN** a client submits many failed sign-ins for one account in a short period
- **THEN** further attempts are refused for a cooling-off period and the attempts are logged

#### Scenario: Plain HTTP

- **WHEN** a hosted instance not started in local-testing mode receives a sign-in over plain HTTP
- **THEN** no session is issued

### Requirement: Instance secrets never reach a repository

Remote credentials and identity-provider secrets MUST come from operator-supplied
secrets or be stored encrypted at rest in instance state. They MUST never be
written to a review repository, included in an export, or displayed back in the
UI.

#### Scenario: Deploy key for a project

- **WHEN** an administrator configures a project's remote with a deploy key
- **THEN** the key is usable by the sync loop and appears in no file inside the project's repository

### Requirement: Remote MCP access

The read-only MCP tools MUST be reachable over MCP's HTTP transport in hosted
mode, behind the same authentication, scoped to the caller's project
memberships, and MUST remain unable to commit a screening or criteria decision.

#### Scenario: Unauthenticated MCP client

- **WHEN** an MCP client connects over HTTP without valid credentials
- **THEN** the connection is refused
