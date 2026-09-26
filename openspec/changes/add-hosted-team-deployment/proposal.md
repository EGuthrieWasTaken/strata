# Proposal: Hosted team instance (M5.1)

## Why

Collaboration should not require every collaborator to know git. The model is
Overleaf: a web service that collaborators open in a browser and sign in to with
their own credentials, backed by a git repository that git-literate people can
still clone and push to. For `strata`, git is always the backend — the question
is only whether the whole `strata` stack runs remotely, or just the git
repository:

| Topology | `strata` runs | Repository | How collaborators share |
|---|---|---|---|
| Solo | Locally | Local (optionally pushed for backup) | — |
| Local stacks, shared remote | On each collaborator's machine (native or the container image) | A shared git remote | `strata sync` |
| Hosted instance | On a server the team runs, from the container image | The instance's working copy, synced with a shared git remote | Sign in with per-user credentials in a browser; git users can keep syncing from local stacks against the same remote |

The first two already work at the format level: event files are per-actor and
append-only, so merges are conflict-free by construction. This change adds the
third, and makes the three interoperate on one review.

This is a decision by the project lead (open question Q11, now decided): `strata`
remains self-hostable software, not a service the project operates.

Roadmap milestone: M5.1 ([docs/roadmap.md](../../../docs/roadmap.md)). It does not
block M3–M5 and depends on `strata sync` (specified in `collaboration-sync`, not
yet implemented) and the `add-container-image` change.

## What Changes

- A hosted mode, `strata host`, serving many projects (one review repository
  each) to many users from one instance, run from the container image with a
  persistent data volume.
- Per-user accounts: built-in local accounts (the default, so an instance needs
  no external identity provider) and optional OpenID Connect sign-in (GitHub,
  institutional SSO). Each user is mapped, per project, to a `strata` actor
  handle and role.
- Project membership and roles, reusing `strata.toml`'s roles; instance
  administration is separate from review roles.
- A git sync loop per project: pull before serving repository state, push after
  each commit, retry with backoff, and conflicts surfaced in-app — never
  resolved silently or lost. Hosted and local collaborators can work on the same
  remote at the same time.
- Commit attribution: the author is the actor who acted; the committer is the
  instance.
- Server-side enforcement of blinding between users of the same instance.
- A hosted security baseline: TLS, `Secure` session cookies, rate-limited sign
  in, session expiry, validation against the instance's public URL, and no
  inactivity exit.
- Instance-held secrets (remote credentials, password hashes) kept outside every
  review repository.
- The read-only MCP tools exposed over MCP's HTTP transport behind the same
  authentication.

## Capabilities

### New Capabilities

- `hosted-deployment`: the hosted instance — projects, accounts, membership,
  the sync loop, attribution, blinding between users, the hosted security
  baseline, secrets handling, data portability, and remote MCP access.

### Modified Capabilities

- `web-ui`: "Strictly local" becomes the default mode rather than the only one;
  hosted mode is the explicit exception, specified in `hosted-deployment`.
- `privacy-and-security`: "Offline by default" and "No stored credentials"
  gain the hosted instance as an operator-configured exception.
- `cli`: adds the `strata host` command group.

## Impact

- `web/`: an authentication layer and a hosted mode alongside the unchanged
  local mode; no domain logic moves into it.
- `gitio`: a per-project background sync loop built on `strata sync`.
- `mcpserver/`: an HTTP transport.
- New instance state (accounts, memberships, sessions, sign-in audit log,
  secrets) under the instance's data volume, never in a review repository.
- No change to the review repository format; no schema-version bump.
- This is the first mode reachable beyond localhost by design, so it gets a
  security review before release.
