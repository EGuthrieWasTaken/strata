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
- [x] 4.7 Host keys: keep trust on first use as the default, let the operator pin a project's SSH host key when adding it, and print the accepted key's fingerprint at the first clone
- [x] 4.8 API tokens name one project and expire (`strata host token add --project --days`, at most 365 days); existing tokens are expired by the upgrade *(decided as "keep working until revoked"; the maintainer then asked for them to be expired on upgrade and `--days` to be capped, which is what is built)*
- [x] 4.9 A signed-in person can change their own password with their current one; their other sessions end
- [x] 4.10 Warn once when `X-Forwarded-For` arrives from an address not in `--trusted-proxy`
- [x] 4.11 Log membership grants, role changes, removals and token creation and revocation, with who did each, beside the sign-in log
- [x] 4.12 An OpenID Connect invitation is used only once the identity is known not to be linked to another account
- [x] 4.13 A project with a symbolic link is refused on its own (shown as unavailable, naming the link); the instance and its other projects start
- [x] 4.14 Every refusal added by 4.7 to 4.13 says, in plain language, in the log and to the person refused, what was refused, why, and what fixes it (for example: the project, the link's path, and how to remove it and push), without revealing to a non-member that a project exists

## 5. Remote MCP

- [x] 5.1 Expose the read-only MCP tools over MCP's HTTP transport behind the same authentication and project membership

## 6. Operations

- [x] 6.1 Example `compose.yaml` for a hosted instance (image, data volume, secrets, reverse proxy with TLS) *(run on 20 November 2026 with Docker 29.9 and `STRATA_DOMAIN=localhost`, so Caddy used its own certificate rather than Let's Encrypt: only Caddy's ports published, plain HTTP redirected, an invitation accepted over HTTPS with a `__Host-` `Secure` session cookie, and used only once. Running it found that compose keeps a secret file's owner, so the `chmod 600` the walk-through gave left the key unreadable to the instance; the instructions now give the files to uid 10001)*
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
  A second pass (`docs/security-review-hosted.md`, 20 November 2026) fixed six more, each with a test: a
  symbolic link pushed to a project's remote was checked out as one, letting the screens reach files outside
  the project (now `core.symlinks=false` from the first checkout, and a project with a link is refused); an
  invitation could be used twice by concurrent requests; a new password did not end old sessions; the
  members form could demote the only lead; an `ssh://` URL with a password was accepted; and the
  pre-sign-in CSRF token was compared in variable time. It lists seven choices for the maintainer
  (host-key pinning, per-project and expiring API tokens, self-service password change, a warning for
  an untrusted proxy, invitation use with OpenID Connect, an audit log of grants, failing closed on a
  symbolic link). The maintainer decided them on 20 November 2026 (4.7 to 4.13). Still by the same kind
  of reviewer that wrote the code, so 4.6 stays open for the maintainer's decision on an independent review.
- 4.7 to 4.14 are built, each with tests written first (the maintainer's decisions of 20 November 2026,
  `docs/security-review-hosted.md`). Choices the decisions left open: a new token lasts 90 days unless
  `--days` says otherwise (`--project` is required), and the instance's state is brought up to
  date in place the first time the new version runs (`Store.upgrade`, schema version 2). Two changes the
  maintainer asked for afterwards, once the suite was green: that upgrade **expires** the tokens made before,
  which name no project and never lapsed (they are kept so they can be revoked and so a holder is told the
  token expired and when; the log says how many and the audit log names each), and `--days` is capped at
  365 (`accounts.MAX_TOKEN_DAYS`, a number chosen here because none was given). So an MCP client that used
  an old token stops working until it is given a new one. A token row that names no project or has no
  expiry is also refused as expired wherever it is found. The audit log
  (`strata host audit`, beside `signins`) records an administrator at a shell as `command line (<login>)`.
  Disabling an account ends its tokens but is not logged as a revocation, since the decision lists token
  revocation, not account changes. A project with a symbolic link is refused on its own: its members get a 503
  page naming the link and the `git rm` that removes it, a non-member the usual 404, the sync loop never
  touches its working copy, and it is looked at again on each request, so removing the link brings it back
  without a restart. The `X-Forwarded-For` warning is given once per process by a watcher outside uvicorn's
  own proxy-header handling (uvicorn now runs with `proxy_headers=False` and `create_served_app` does that
  work); the option is spelled `--trusted-proxy`, as the code always had it, not `--trusted-proxies` as the
  review writes it (4.10 now has it right). Beyond the tasks: `strata host audit` (to read the log) and `strata host project
  host-key` (4.14 asks every refusal to say what fixes it, and a changed host key could not be fixed without
  a way to change the pin). The refusals to a command-line operator are printed where they run; there is no
  separate log for the command line. **SSH host-key behaviour was tested against a stand-in `ssh` put first
  on `PATH`** (the options the instance gives it, the known_hosts file it sees, the accepted key read back,
  the fingerprint, which is checked against GitHub's published one, and the messages): there is no SSH client
  in the environment these were built in, so OpenSSH itself has not been run against it. The decisions are
  requirements in the delta specs (`hosted-deployment`: SSH host keys, API tokens name one project and
  expire, Self-service password change, Invitations with a sign-in provider, Forwarded addresses are believed
  only from trusted proxies, Audit log of access changes, A project with a symbolic link is refused alone,
  Refusals say what, why and how to fix it; `cli`: the host commands), and their rationale is in `design.md`.
- 6.1: `docker/hosted/compose.yaml` and `Caddyfile` were written and structure-tested, then run with Docker
  (see the task). Not exercised: Let's Encrypt (it needs a public DNS name) and a deploy key reaching a real
  git host.
- `strata host` itself was run for real on one machine with `--insecure-local-testing`: init, project add from
  a bare remote, user and member add, sign-in, the project dashboard, a refused write, sign-out.
