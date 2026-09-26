# Tasks

## 0. Prerequisites

- [ ] 0.1 Implement `strata sync` (`collaboration-sync`, currently a known gap)
- [ ] 0.2 Land `add-container-image` (image, `--public-url`, `/healthz`)

## 1. Instance and projects

- [ ] 1.1 `strata host` serving projects from `/data/projects/<id>/` with instance state under `/data/instance/`
- [ ] 1.2 `strata host init`, `strata host project add --remote URL` (clone or initialise), `strata host project list`
- [ ] 1.3 Instance-level dashboard listing the projects a user belongs to

## 2. Accounts and membership

- [ ] 2.1 Local accounts with Argon2id password hashing, admin-created or invited; `strata host user add|disable`
- [ ] 2.2 Optional OpenID Connect sign-in (GitHub, institutional SSO)
- [ ] 2.3 Memberships mapping user → project → actor handle → role; the project lead manages them
- [ ] 2.4 Enforce roles on every route (observer is read-only; only adjudicators adjudicate)

## 3. Sync loop and attribution

- [ ] 3.1 Pull-before-read with a short interval, push-after-commit with exponential backoff
- [ ] 3.2 Surface conflicts in human-authored files to leads in domain terms; block pushes for that project until resolved
- [ ] 3.3 Author commits as the actor, commit as the instance; keep `Strata-` trailers
- [ ] 3.4 Show last-sync time and remote status on each project's dashboard

## 4. Security and privacy

- [ ] 4.1 Require TLS (refuse to issue sessions over plain HTTP unless explicitly started for local testing)
- [ ] 4.2 `Secure`/`HttpOnly`/`SameSite=Strict` expiring session cookies; rate-limited sign-in; sign-in audit log
- [ ] 4.3 Validate `Host`/`Origin` against the public URL; disable the inactivity exit in hosted mode
- [ ] 4.4 Server-side blinding between users on the same instance, including MCP responses
- [ ] 4.5 Remote credentials and OIDC secrets from operator-supplied secrets or encrypted at rest; never in a review repository or echoed in the UI
- [ ] 4.6 Security review before release

## 5. Remote MCP

- [ ] 5.1 Expose the read-only MCP tools over MCP's HTTP transport behind the same authentication and project membership

## 6. Operations

- [ ] 6.1 Example `compose.yaml` for a hosted instance (image, data volume, secrets, reverse proxy with TLS)
- [ ] 6.2 Wiki pages: running an instance, backups and restore from remotes, upgrading, inviting collaborators, mixing hosted and local collaborators

## 7. Tests (suite additions, docs/roadmap.md M5.1)

- [ ] 7.1 Sync-loop E2E: two members editing concurrently through the hosted UI, plus a third syncing from a local clone; every decision survives, human-authored conflicts are surfaced
- [ ] 7.2 Authentication tests for local accounts and OIDC mapping to actor handles
- [ ] 7.3 Multi-tenancy isolation: no route, including MCP, returns another project's data to a non-member
- [ ] 7.4 Blinding between users: a screener never receives another screener's undecided-record opinion
- [ ] 7.5 A test that no secret is ever written into a review repository
