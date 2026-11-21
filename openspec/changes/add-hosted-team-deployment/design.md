# Design: Hosted team instance

## Context

`strata serve` is already a real HTTP server, server-rendered, stateless with
respect to the repository, and protected by a session token, CSRF tokens, and
`Host`/`Origin` validation. What a shared, always-on instance adds is: several
people at once, knowing who each request is from, several repositories, and
keeping a git remote in step without a human running `git pull`/`push`.

Browser imports do not belong to this change: `add-web-ui-write-surfaces` adds them to the local
`strata serve`, together with what they need: a per-request upload size limit and staging area
(`.strata/tmp/uploads`, cleaned on use, at start-up and after an hour), the operating-system repository
lock that a terminal and a server share, and `strata.core.operations`, which the command line and the web
screens both call. A hosted instance inherits all of that and adds what is its own: per-user accounts and
quotas, a staging area per project, and the sync loop. It should not grow a second import path.

The repository format already makes concurrent work safe: each actor appends
only to their own event files, so two users screening on one instance — or one
on the instance and one on a laptop — never touch the same file.

## Goals / Non-Goals

**Goals:**

- A team can run one instance and review collaboratively without anyone running
  git locally (the M5.1 acceptance bar).
- Hosted and local collaborators can work on the same review at the same time.
- Every decision and commit is attributed to the reviewer who made it.
- Leaving the instance is always possible: every project is a git repository
  that can be cloned out.

**Non-Goals:**

- A service the project operates (non-goal N6).
- Real-time co-editing of the same text (criteria definitions, `question.md`);
  concurrent edits to human-authored files are resolved as conflicts.
- The instance acting as a git server (an Overleaf-style "git bridge"). Projects
  sync with an external remote (GitHub, GitLab, Gitea, a bare repository);
  serving git over HTTPS from the instance is a possible follow-up.
- Passwordless and multi-factor authentication in the first iteration, beyond
  what an OIDC provider supplies.

## Decisions

- **One process, many projects.** `strata host` serves projects from
  `/data/projects/<project-id>/` (each a normal working copy) and keeps instance
  state — accounts, memberships, sessions, the sign-in log, and secrets — under
  `/data/instance/`. Instance state never enters a review repository.
- **Accounts: local by default, OIDC optional.** Local accounts (admin-created or
  invited, passwords hashed with Argon2id) let a lab run an instance with no
  external dependency. OpenID Connect covers GitHub and institutional SSO. An
  earlier draft of this change required GitHub sign-in; that was dropped because
  it made a GitHub account a precondition for collaborating, which is exactly the
  barrier hosting is meant to remove.
- **Users are not actors; memberships map them.** A membership links a user to
  one project, one actor handle in that project's `strata.toml`, and a role. The
  same person can be `ethan` in one review and `eguthrie` in another. The
  project's lead manages memberships; instance administrators manage accounts
  and projects but have no review role by default.
- **Attribution.** Commits made for a user have the actor's name and email from
  `strata.toml` as author and the instance's identity as committer, and carry
  the normal `Strata-Actor` trailer. Git history therefore shows who decided and
  that the instance recorded it.
- **The sync loop is `strata sync` on a timer, plus on demand.** Before serving a
  page that reads repository state the instance pulls if the last fetch is older
  than a short interval; after each commit it pushes. Event files union-merge and
  derived files regenerate, so the common case is always clean. A genuine
  conflict in a human-authored file blocks pushes for that project and is shown
  to members with the lead role in domain terms (keep mine, keep theirs, edit),
  exactly as `strata sync` presents it locally.
- **One working copy per project, serialised by the existing lock.** Each user's
  operation appends to that user's files and commits only that operation, so
  commits from different users do not interleave content. Batched screening
  commits are batched per actor.
- **Blinding is enforced by the server, per user.** On a local install blinding
  is protected by the data layout; on a shared instance the server holds every
  reviewer's files, so it must never render, return, or expose via MCP another
  reviewer's opinion to a user who has not yet decided that record while
  `blind_reviewers` is set.
- **Security baseline.** TLS is required (normally terminated by a reverse proxy
  in front of the container); session cookies are `Secure`, `HttpOnly`,
  `SameSite=Strict`, and expire; sign-in is rate-limited; `Host`/`Origin` are
  validated against the configured public URL; the 60-minute inactivity exit
  that protects a forgotten local server is disabled; every sign-in is logged in
  instance state.
- **Secrets stay in the instance.** Each project's remote credential (deploy key
  or token) and any OIDC client secret come from the operator (environment
  variables or container secrets) or are stored encrypted at rest under an
  instance key. None is ever written to a review repository or shown back in the
  UI.

### Decided after a security review of the first build

A reading of the code by its author (`docs/security-review-hosted.md`) put seven
choices to the maintainer, who decided them on 20 November 2026. Each is built.

- **SSH host keys.** The default stays trust on first use (`accept-new`):
  requiring a pin would make a first deployment depend on the operator already
  holding the host's key. The first clone prints the accepted fingerprint, so
  the operator can compare it with the one the host publishes. An operator who
  has the key pins it, when adding the project or later with `strata host project
  host-key`; ssh then believes that key only (`StrictHostKeyChecking=yes`, no
  system known_hosts), so there is no first use to be fooled at. A pin is a
  public key, stored with the project in instance state. A key that stops
  matching is refused and reported in words, on the project's sync page and in
  the log, with the command that pins a new one.
- **API tokens are narrow and expire.** A token names one project and lasts 90
  days unless the operator says otherwise, and never more than 365, so a leaked
  token gives one review for a while rather than every review its owner is in. The
  limit is a year because a token that must be made again at least that often
  cannot sit forgotten in a client for years; it is the maintainer's to move
  (`MAX_TOKEN_DAYS`). State made by an earlier version is brought up to date in
  place the first time the new version runs, and that upgrade expires the tokens
  made before, which name no project and never lapse: leaving them would keep a
  token that leaked long ago reading every project its owner is in, which is what
  the change exists to end. They are expired, not deleted, so a client holding one
  is told it expired, and on what day, rather than that the token is unknown, and
  it can still be revoked. Each is in the audit log, naming whose it was and its
  label, and the log says how many were expired. An MCP client that worked before
  stops working until its token is replaced, which the operator is told to do. As
  a second line, a token row that names no project or has no expiry is refused as
  expired wherever it is found, so correctness does not depend on the upgrade
  having seen it.
- **Changing a password.** It needs the current password, and wrong guesses share
  the sign-in limiter, so a stolen session cannot be used to guess it; the cost is
  that such guesses can cool off the account for 15 minutes. It ends the person's
  other sessions, not their API tokens, which an administrator revokes.
- **Forwarded addresses.** `X-Forwarded-For` is believed only from
  `--trusted-proxy` addresses. A header from anyone else is ignored and warned
  about once. The check sits outside uvicorn's own proxy handling, because that
  replaces a trusted proxy's address with the client's before the application
  sees it. The decision was to warn, not to refuse to start: an instance reached
  directly legitimately receives such headers from strangers.
- **Audit log.** Memberships and tokens decide who can read a review, so their
  grants, role changes, removals and token creation and revocation are recorded in
  instance state, in the same transaction as the change, beside the sign-in log.
  An entry holds a token's label, project and expiry, never the token. Who did it
  is a user name in the browser and, at the command line, the operating-system
  login of the operator, which is all the instance knows of someone at a shell.
- **Invitations and identities.** Using an invitation and linking the provider
  identity are one transaction, and the invitation is left unused when the
  identity belongs to another account, so the person can try another identity
  instead of needing a new invitation.
- **A project with a symbolic link is refused alone.** Projects are cloned with
  `core.symlinks=false`, so a link in a remote arrives as a plain file; a link
  already in a working copy would let the screens follow it out of the project.
  Stopping the whole instance would let one project's contents take every team
  offline. Instead the instance starts and serves the others, shows the project as
  unavailable to its members only (a non-member gets the answer for a project that
  does not exist), and never fetches, commits or pushes in its working copy. It
  looks at the project again on each request, so removing the link brings it back.
- **Refusals explain themselves.** A refusal about a host key, a token, a password
  change, a provider identity or an unavailable project says what was refused,
  why, and what fixes it, to the person refused and, when the running instance
  made it, in its log. Answers that are vague on purpose, a wrong password and a
  project that does not exist, stay vague.

## Risks / Trade-offs

- **Security surface.** This is the first mode exposed beyond localhost. A
  dedicated security review is a release gate for this change. The reading above
  is a second look by the kind of reviewer that wrote the code, not that review,
  which remains open (task 4.6).
- **SSH host keys are tested against a stand-in.** The environment the decisions
  were built in has no SSH client, so the options the instance gives ssh, the
  known_hosts file it sees and the messages were tested against a stand-in `ssh`;
  OpenSSH itself has not been run against them.
- **Governance and support.** Self-hosting shifts operating responsibility to
  teams; the documentation must cover backups (the git remote is the backup of
  record), upgrades, and restoring an instance from remotes alone.
- **Stale reads.** Pull-before-read with a short interval means a user can see
  state a few seconds old. That is acceptable because all writes append to
  per-actor files and the next sync reconciles them; it never loses work.
- **Mixed topologies surprise people.** A local collaborator's pushed decisions
  appear on the instance only after its next pull; the dashboard shows the time
  of the last sync.

## Coordination with `add-ai-participation`

Remote (HTTP) MCP gets the same policy as the local server, and nothing in `add-ai-participation` assumes
stdio beyond how the invoking person is named. `strata.mcpserver.server.create_mcp_server` takes the invoker
as an argument (`strata mcp --as` locally); on a hosted instance the invoker is the signed-in user, which
must be an active, non-observer person of the review (`strata.core.agents.resolve_invoker` checks exactly
that). The policy, registering a model and revoking one stay command-line and web actions by a person on the
instance; no hosted API route may reach them. The client name and version come from the MCP handshake over
either transport.
