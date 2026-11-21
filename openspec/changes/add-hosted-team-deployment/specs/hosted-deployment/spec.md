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
accounts, memberships, sessions, the sign-in log, the audit log, and secrets —
MUST be stored separately from every review repository and MUST never be
committed to one. State made by an earlier version MUST be brought up to date in
place, keeping what it holds apart from the API tokens that name no project,
which it expires.

#### Scenario: Two projects on one instance

- **WHEN** an administrator adds two projects to an instance
- **THEN** each has its own working copy and neither repository contains any account, session, or credential data

#### Scenario: Upgrading

- **GIVEN** an instance whose state was made by an earlier version, with accounts, memberships and an API token
- **WHEN** the new version starts on it
- **THEN** the state is brought up to date, the accounts and memberships are kept, and the token is expired, which the log and the audit log say

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

### Requirement: Self-service password change

A signed-in person MUST be able to change their own password by giving their
current one. The change MUST end every other session of theirs and keep the one
making it. A wrong current password MUST count against the same limit as a wrong
password at sign-in. An account that has no password (it signs in through a
provider) has none to change.

#### Scenario: Changing it

- **GIVEN** `sam` is signed in on two devices
- **WHEN** they change their password on one, giving the current one
- **THEN** that session stays signed in, the other is ended, and only the new password signs in

#### Scenario: Wrong current password

- **WHEN** the current password given is wrong
- **THEN** nothing is changed, other sessions stay signed in, and the attempt is logged

#### Scenario: Guessing from a stolen session

- **WHEN** a signed-in session gives wrong current passwords until the sign-in limit is reached
- **THEN** further attempts are refused for the cooling-off period, even with the right password

#### Scenario: Account with no password

- **WHEN** an account that signs in only through a provider asks to change its password
- **THEN** the request is refused and says to ask an administrator for an invitation

### Requirement: Invitations with a sign-in provider

A person who accepts an invitation by signing in with a provider has that
provider identity linked to the invited account. The invitation MUST be used up
only in the same step that links the identity, and not at all when the identity
is already linked to a different account, so the person can try another identity
with the same invitation.

#### Scenario: Identity linked elsewhere

- **GIVEN** a provider identity linked to `sam` and an unused invitation for `priya`
- **WHEN** `priya` presents that identity with the invitation
- **THEN** sign-in is refused, nothing is linked, and the invitation is still valid

#### Scenario: The person's own identity

- **GIVEN** a provider identity linked to `sam` and an unused invitation for `sam`
- **WHEN** `sam` presents that identity with the invitation
- **THEN** it is accepted and the invitation is used up

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

### Requirement: Forwarded addresses are believed only from trusted proxies

The instance MUST believe `X-Forwarded-For` and `X-Forwarded-Proto` only from
the addresses configured as trusted proxies. When a request carries
`X-Forwarded-For` from any other address, the instance MUST ignore the header
and warn once in its log, naming the address and the option that trusts it.

#### Scenario: Untrusted address

- **GIVEN** an instance whose only trusted proxy is `10.0.0.2`
- **WHEN** requests from `203.0.113.7` carry `X-Forwarded-For`
- **THEN** the header is ignored, and the log warns once, naming `203.0.113.7` and `--trusted-proxy`

#### Scenario: Trusted proxy

- **WHEN** a request from a trusted proxy carries `X-Forwarded-For`
- **THEN** the client address it names is used for the sign-in limit, and nothing is warned about

### Requirement: Instance secrets never reach a repository

Remote credentials and identity-provider secrets MUST come from operator-supplied
secrets or be stored encrypted at rest in instance state. They MUST never be
written to a review repository, included in an export, or displayed back in the
UI.

#### Scenario: Deploy key for a project

- **WHEN** an administrator configures a project's remote with a deploy key
- **THEN** the key is usable by the sync loop and appears in no file inside the project's repository

### Requirement: SSH host keys

For a project reached over SSH, the instance MUST by default trust the git
host's key on first use, refuse a different key afterwards, and print the
fingerprint of the key it accepted when the project is first cloned. An operator
MAY pin the project's host key (one or more `known_hosts` lines) when adding the
project or later; the instance MUST then believe only the pinned keys. A pin
applies to SSH remotes only.

#### Scenario: Trust on first use

- **GIVEN** a project added with a deploy key and no pinned key
- **WHEN** its first clone succeeds
- **THEN** the command prints the accepted key's type and fingerprint, and a different key from that host later is refused

#### Scenario: Pinned key

- **GIVEN** a project added with its host's key pinned
- **WHEN** the instance clones or syncs it
- **THEN** ssh believes only the pinned key, and nothing is trusted on first use for that project

#### Scenario: A host shows another key

- **GIVEN** a pinned key, or a key accepted on first use
- **WHEN** the host shows a different key
- **THEN** the connection is refused, nothing is cloned or synced, and the message names the project and host, says the key is not the expected one, and says how to pin a new key after checking its fingerprint

#### Scenario: A pin that cannot match

- **WHEN** a key is given for another host, is malformed, or is given for a remote that is not SSH
- **THEN** it is refused, nothing is stored, and the message says what a usable key looks like

### Requirement: Remote MCP access

The read-only MCP tools MUST be reachable over MCP's HTTP transport in hosted
mode, behind the same authentication, scoped to the caller's project
memberships, and MUST remain unable to commit a screening or criteria decision.

#### Scenario: Unauthenticated MCP client

- **WHEN** an MCP client connects over HTTP without valid credentials
- **THEN** the connection is refused

### Requirement: API tokens name one project and expire

An API token MUST name one project of which its owner is a member and MUST
expire: after 90 days unless the operator chooses another number of days, and
after no more than 365. It MUST be refused outside its project and after its
expiry. A token made before tokens named a project MUST be expired when the
instance's state is first brought up to date, so that it no longer reads every
project its owner belongs to.

#### Scenario: Own project

- **GIVEN** a token for `spacing`
- **WHEN** an MCP client uses it against `spacing`
- **THEN** the read-only tools answer

#### Scenario: Another project its owner belongs to

- **GIVEN** an owner who is a member of `spacing` and `secret-trial`, and a token for `spacing`
- **WHEN** it is used against `secret-trial`
- **THEN** it is refused, and the answer names both projects and how to get a token for `secret-trial`

#### Scenario: Expired token

- **WHEN** a token is used after its expiry
- **THEN** it is refused with the date it ended, naming neither the account nor the project

#### Scenario: Owner is not a member

- **WHEN** an operator makes a token for a user who is not a member of the project
- **THEN** it is refused, no token is made, and the message says how to make them a member

#### Scenario: Longer than a year

- **WHEN** an operator asks for a token to last more than 365 days
- **THEN** it is refused, no token is made, and the message gives the longest allowed and says to make a new token when it expires

#### Scenario: Tokens from before

- **GIVEN** a token made before tokens named a project
- **WHEN** the instance is upgraded, and the token is then used
- **THEN** it is refused as expired, with the day of the upgrade, and reads no project; it stays until revoked, and the log says how many were expired

### Requirement: Audit log of access changes

The instance MUST record membership grants, role changes and removals, and API
token creation, revocation and expiry by an upgrade, in instance state beside the
sign-in log, with who did each and when. An entry MUST be written in the same
transaction as the change, and MUST NOT contain a token. Who did it is the user
name when a person did it in the browser, the operating-system login when an
administrator did it with `strata host`, and the instance itself for an upgrade.

#### Scenario: Role change in the browser

- **GIVEN** a lead signed in as `ethan.g`
- **WHEN** they change `sam.okonkwo`'s role
- **THEN** the log has an entry naming `ethan.g`, the project, `sam.okonkwo`, and the old and new role

#### Scenario: At the command line

- **WHEN** an administrator makes a token with `strata host token add`
- **THEN** the log has an entry naming their operating-system login, the token's label, project and expiry, and not the token

#### Scenario: No change, no entry

- **WHEN** a membership is saved with the actor and role it already has
- **THEN** nothing is logged

### Requirement: A project with a symbolic link is refused alone

If a project's working copy contains a symbolic link, the instance MUST refuse
that project alone: it MUST start and serve its other projects, MUST show the
project as unavailable to its members only, naming the link and how to remove
it, and MUST NOT fetch, commit or push in its working copy. It MUST look at the
project again on each request, so that removing the link brings it back.

#### Scenario: Other projects carry on

- **GIVEN** two projects, one with a symbolic link
- **WHEN** the instance starts
- **THEN** it starts, logs which project it refused and the link's path, and serves the other project

#### Scenario: A non-member

- **WHEN** someone who is not a member of the refused project asks for it
- **THEN** the answer is the same as for a project that does not exist

#### Scenario: Link removed

- **GIVEN** a refused project
- **WHEN** the link is removed and its page is next opened
- **THEN** the project is served again without a restart

### Requirement: Refusals say what, why and how to fix it

A refusal about an SSH host key, an API token, a password change, a provider
identity or an unavailable project MUST say, in plain language, what was refused,
why, and what fixes it, to the person refused and, when the running instance made
it, in its log (a `strata host` command prints it to the operator). It MUST NOT
reveal to a non-member that a project exists.

#### Scenario: Expired token

- **WHEN** an MCP client presents an expired token
- **THEN** the answer and the log say the token expired, on what date, and how to get another

#### Scenario: Unavailable project seen by a non-member

- **GIVEN** a project refused because of a symbolic link
- **WHEN** someone who is not a member asks for it
- **THEN** the answer says nothing of the link or of the project

#### Scenario: Answers that stay vague on purpose

- **WHEN** a wrong password is given at sign-in, or a non-member asks for a project
- **THEN** the answer is as it was: it does not say which part of the sign-in was wrong, or whether the project exists
