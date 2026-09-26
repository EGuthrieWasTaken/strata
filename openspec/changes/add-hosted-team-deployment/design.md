# Design: Hosted team instance

## Context

`strata serve` is already a real HTTP server, server-rendered, stateless with
respect to the repository, and protected by a session token, CSRF tokens, and
`Host`/`Origin` validation. What a shared, always-on instance adds is: several
people at once, knowing who each request is from, several repositories, and
keeping a git remote in step without a human running `git pull`/`push`.

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

## Risks / Trade-offs

- **Security surface.** This is the first mode exposed beyond localhost. A
  dedicated security review is a release gate for this change.
- **Governance and support.** Self-hosting shifts operating responsibility to
  teams; the documentation must cover backups (the git remote is the backup of
  record), upgrades, and restoring an instance from remotes alone.
- **Stale reads.** Pull-before-read with a short interval means a user can see
  state a few seconds old. That is acceptable because all writes append to
  per-actor files and the next sync reconciles them; it never loses work.
- **Mixed topologies surprise people.** A local collaborator's pushed decisions
  appear on the instance only after its next pull; the dashboard shows the time
  of the last sync.
