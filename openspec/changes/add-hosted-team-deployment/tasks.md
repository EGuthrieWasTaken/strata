# Tasks

## 0. Prerequisites

- [x] 0.1 Implement `strata sync` (`collaboration-sync`, currently a known gap)
- [x] 0.2 Land `add-container-image` (image, `--public-url`, `/healthz`)

## 1. Instance and projects

- [x] 1.1 `strata host` serving projects from `/data/projects/<id>/` with instance state under `/data/instance/`
- [x] 1.2 `strata host init`, `strata host project add --remote URL` (clone or initialise), `strata host project list`
- [x] 1.3 Instance-level dashboard listing the projects a user belongs to

## 2. Accounts and membership

- [x] 2.1 Local accounts with Argon2id password hashing, admin-created or invited; `strata host user add|disable`
- [x] 2.2 Optional OpenID Connect sign-in (GitHub, institutional SSO)
- [x] 2.3 Memberships mapping user → project → actor handle → role; the project lead manages them
- [x] 2.4 Enforce roles on every route (observer is read-only; only adjudicators adjudicate)

## 3. Sync loop and attribution

- [x] 3.1 Pull-before-read with a short interval, push-after-commit with exponential backoff
- [x] 3.2 Surface conflicts in human-authored files to leads in domain terms; block pushes for that project until resolved
- [x] 3.3 Author commits as the actor, commit as the instance; keep `Strata-` trailers
- [x] 3.4 Show last-sync time and remote status on each project's dashboard

## 4. Security and privacy

- [x] 4.1 Require TLS (refuse to issue sessions over plain HTTP unless explicitly started for local testing)
- [x] 4.2 `Secure`/`HttpOnly`/`SameSite=Strict` expiring session cookies; rate-limited sign-in; sign-in audit log
- [x] 4.3 Validate `Host`/`Origin` against the public URL; disable the inactivity exit in hosted mode
- [x] 4.4 Server-side blinding between users on the same instance, including MCP responses
- [x] 4.5 Remote credentials and OIDC secrets from operator-supplied secrets or encrypted at rest; never in a review repository or echoed in the UI
- [ ] 4.6 Security review before release

## 5. Remote MCP

- [x] 5.1 Expose the read-only MCP tools over MCP's HTTP transport behind the same authentication and project membership

## 6. Operations

- [ ] 6.1 Example `compose.yaml` for a hosted instance (image, data volume, secrets, reverse proxy with TLS)
- [x] 6.2 Wiki pages: running an instance, backups and restore from remotes, upgrading, inviting collaborators, mixing hosted and local collaborators

## 7. Tests (suite additions, docs/roadmap.md M5.1)

- [x] 7.1 Sync-loop E2E: two members editing concurrently through the hosted UI, plus a third syncing from a local clone; every decision survives, human-authored conflicts are surfaced
- [x] 7.2 Authentication tests for local accounts and OIDC mapping to actor handles
- [x] 7.3 Multi-tenancy isolation: no route, including MCP, returns another project's data to a non-member
- [x] 7.4 Blinding between users: a screener never receives another screener's undecided-record opinion
- [x] 7.5 A test that no secret is ever written into a review repository

## Notes

- 0.1: `strata sync` is built (`strata.core.sync`, `docs/m5-1-plan.md`). 0.2: the three pieces this change
  needs from `add-container-image` (the image, `--public-url`, `/healthz`) are on `main`; that change's own open
  items (running its `compose.yaml` by hand, cosign signing) do not block this one.
- Where things live: `strata.hosted` (instance state in SQLite under `<data>/instance/`, accounts, memberships
  and roles, secrets, the sync loop, OIDC), `strata.protocol.blinding`, `strata.web.hosted` (the ASGI app: the
  local server's own screens mounted per project under `/p/<id>/`, plus sign-in, members, sync and MCP), and
  `strata host` in `strata.cli.host`. `strata serve` is unchanged apart from rendering its links under the
  request's root path (empty locally) and reading its state per request.
- Beyond the CLI table in the delta spec, `strata host` also has `user invite|enable|list`, `member
  remove|list`, `token add|revoke` (the API tokens an MCP client authenticates with, task 5.1), `secret
  set|list|delete` (secrets stored encrypted at rest, task 4.5) and `signins` (the sign-in audit log, task 4.2).
- 2.2: tested against a stand-in OpenID Connect provider and a stand-in for GitHub's OAuth (signature,
  issuer, audience, expiry, nonce, PKCE, state bound to the browser); **not yet tried with a real provider**.
  A provider identity reaches an account only through the account's invitation (no linking by email).
- 3.1: pull-before-read makes one attempt (`strata.core.sync.sync(..., backoff=())`) so a page never waits out
  a retry schedule; pushes are retried by the background worker after 30 s doubling to 15 min.
- 3.2: the lead resolves as mine, theirs, or edited text (`strata.core.sync.Edited`); pulls stop with pushes,
  since a pull would meet the same conflict.
- Screening batches on the instance are committed with a generated summary and no rationale prompt, also when
  a batch re-decides a previously resolved record (`openspec:git-integration#batched-screening-commits` asks
  for a prompt then). The browser has no place for that prompt yet; the decision's note is the place to say
  why. Listed in the wiki's Known limitations.
- Blinding (4.4): a reviewer is blinded to a record at a stage while it is in their own screening queue there
  (assigned and undecided). The local screens already show no colleague's opinion before adjudication; on the
  instance the adjudication queue and the criteria-impact previews (web and MCP) also leave out records the
  member is blinded to, and the adjudication queue needs the adjudicator or lead role.
- 4.6 is open. A first pass over the hosted mode, done while building it, found and fixed: hooks run from the
  repository (`.strata/hooks` is versioned, so anyone able to push to a project's remote could have run code on
  the instance; the instance now points `core.hooksPath` at its own copy), unbounded bodies on the
  pre-sign-in forms (now refused over 1 MiB or without a length), login CSRF through the OIDC callback (the
  state is now bound to the browser with a cookie), and invitation tokens in the access log (now off). That
  pass is not the independent review this task asks for before a release.
- 6.1: `docker/hosted/compose.yaml` and `Caddyfile` are written and their structure is tested (only the proxy
  is published, the options are ones `strata host` takes, `/data` in the image is writable); **they have not
  been run** (no container runtime was available), so 6.1 stays open, as `add-container-image`'s 1.4 did.
- `strata host` itself was run for real on one machine with `--insecure-local-testing`: init, project add from
  a bare remote, user and member add, sign-in, the project dashboard, a refused write, sign-out.
