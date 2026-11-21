# Security review of the hosted instance (`strata host`)

For task 4.6 of `add-hosted-team-deployment`, done on 20 November 2026 by reading the code. It is a
second pass after the one done while the hosted mode was built (listed in that change's `tasks.md`).
**It is not an independent review:** the same kind of reviewer wrote the code. The task stays open
until the maintainer decides whether this suffices or a review by someone else is wanted before a
release.

## Scope

`src/strata/hosted/` (accounts, sessions, invitations, API tokens, memberships, OpenID Connect,
secrets, the sync loop, project setup) and `src/strata/web/hosted.py` (the gate, sign-in, the
project dispatcher, the remote MCP endpoint). Not covered: the review's own screens beyond how the
dispatcher authorises them, the Caddy and compose files, and anything outside the repository (the
host, the reverse proxy's configuration, the identity providers).

The attackers considered: a stranger on the network; a member with a low role (observer, screener);
a lead of one project acting against another project or the instance; anyone who can push to a
project's git remote; and someone with a copy of the instance's database.

## Fixed in this pass

Each has a test that fails without the fix.

| # | Finding | Who could do it | Fix | Test |
|---|---|---|---|---|
| 1 | **A symbolic link in a project's remote was checked out as a link.** The screens read and write a review's files by path, so a link (say `protocol/question.md -> ../../instance/...`) would let them read or overwrite files outside the project: the instance's state, its key, its hooks (code that git runs), or another project | Anyone who can push to a project's remote | Projects are cloned with `core.symlinks=false` from the first checkout, and every project gets it in `secure_project`; a link arrives as a small file holding the link's text. An existing project that has a link in its working tree is refused at start-up, naming it | `test_hosted_hardening.py`: a link pushed to the remote is checked out as a plain file; an instance refuses a project that already has one |
| 2 | **An invitation could be used twice** by two requests at once: it was checked, then marked used, in two statements | Whoever holds the invitation link (it is a bearer token) | Marking it used is now the check: `UPDATE ... WHERE used = 0 AND expires >= now`, and no row changed means refused | `test_hosted_accounts.py::test_an_invitation_checked_by_two_requests_at_once_is_used_only_once` |
| 3 | **A new password left the old sessions alive**, so resetting a password (`strata host user`, or a new invitation) did not sign out whoever had it | Someone with a stolen session | `set_password` ends the account's sessions in the same transaction | `test_a_new_password_ends_the_sessions_signed_in_with_the_old_one` |
| 4 | **The members form could demote the project's only lead**, leaving no one able to manage members or resolve conflicts (the remove button already refused this) | A lead, by mistake | `add_member` refuses to change the only lead's role | `test_the_only_lead_cannot_be_demoted_by_the_members_form` |
| 5 | **A credential in an `ssh://` URL was accepted** and stored in plain text in instance state (only `http(s)` URLs were checked) | An administrator, by mistake | Any URL with a password is refused, as an `http(s)` URL with a user name already was | `test_a_remote_url_with_a_credential_in_it_is_refused` |
| 6 | The pre-sign-in CSRF token was compared with `==` | Timing, in principle | `hmac.compare_digest`, as the session's own token already was | (no behavioural change to test) |

Also hardened: `gitio.clone` now passes `--` before the URL, so no URL can be read as an option
(`check_remote_url` already refused one that starts with `-`).

## Checked and found sound

- **Passwords and sign-in:** Argon2id with the library's defaults; a missing account takes as long
  to refuse as a wrong password and gets the same message; per-account and per-client lockout;
  every attempt logged; the hash is upgraded when the parameters change.
- **Sessions:** 256-bit random tokens, only their SHA-256 stored; idle and absolute expiry; ended by
  sign-out and by disabling the account; a new session at every sign-in (no fixation); a separate
  CSRF token per session; cookies `Secure`, `HttpOnly`, `SameSite=Strict` and `__Host-` prefixed.
- **The gate:** `Host` and `Origin` checked against the public URL; plain HTTP redirected or
  refused; a body without a length or over 1 MiB refused before sign-in; CSP, `nosniff`,
  `X-Frame-Options: DENY`, `no-store` and HSTS on every response; no access log (invitation tokens
  are in paths); `X-Forwarded-*` believed only from `--trusted-proxies`.
- **Authorisation:** every request inside a project needs a membership; a non-member gets the same
  404 whether the project exists or not; writes are denied unless a role is listed for them
  (anything unlisted needs `lead`); CSRF on every mutating form; the MCP endpoint needs an API token
  whose account is a member and serves read tools only.
- **OpenID Connect:** authorization code with PKCE (S256), `state` and `nonce`; the state is bound
  to the browser by a cookie (login CSRF); ID tokens verified (asymmetric algorithms only,
  signature, issuer, audience, expiry, nonce); the discovery document's issuer must match; an
  identity signs in only an account it was linked to by an invitation; GitHub's numeric id, not the
  login, is the subject.
- **Secrets:** Fernet at rest with a key the instance creates `0600`, or one supplied by file or
  environment; deploy keys written to a `0700` directory and removed after use; HTTPS tokens passed
  through `GIT_ASKPASS`, never in a URL or on a command line; git never prompts.
- **The repository cannot run code on the instance:** hooks come from the instance's own directory
  (`core.hooksPath`), merge drivers and filters only from the instance's git configuration.

## For the maintainer to decide

None of these is a defect in what the specification asks for; each is a choice the specification
does not make.

**Decided on 20 November 2026** (tasks 4.7 to 4.13 of `add-hosted-team-deployment`):

| # | Decision |
|---|---|
| 1 | Optional pinning: trust on first use stays the default, the operator can supply a project's host key, and the first clone prints the accepted key's fingerprint |
| 2 | Tokens name one project and expire; existing tokens work until revoked |
| 3 | Self-service password change, with the current password; other sessions end |
| 4 | Warn once on `X-Forwarded-For` from an untrusted address |
| 5 | Check the identity is not linked elsewhere before using the invitation |
| 6 | Log grants, role changes, removals and token creation and revocation |
| 7 | Refuse the project with a link on its own; the instance starts |

For all seven, every refusal says in plain language, in the log and to the person refused, what was
refused, why, and how to fix it (task 4.14). Messages to someone who is not a member still do not
reveal whether a project exists.

**Built** (tasks 4.7 to 4.14, each with tests that failed first). The option the review calls
`--trusted-proxies` is `--trusted-proxy` in the code. The host-key behaviour was tested against a
stand-in for `ssh` (there is no SSH client where it was built), not against OpenSSH; see the notes in
the change's `tasks.md`. This is still a reading of the code by the kind of reviewer that wrote it:
task 4.6 stays open.

**Changed afterwards, at the maintainer's request** (once the full suite was green on the build above):
decision 2 said existing tokens work until revoked. They are now **expired by the upgrade** (kept, so they
can be revoked and the holder is told the token expired; the log and the audit log say which), and
`--days` is **capped at 365**, a number picked when none was given. An MCP client that used an old token
needs a new one.

The choices as they were put:

1. **Host keys are trusted on first use** (`StrictHostKeyChecking=accept-new`). An attacker in the
   network path at the first clone could pose as the git host. Pinning would need the operator to
   supply the host key (`known_hosts` in instance state) when adding a project.
2. **An API token is for every project its account belongs to, and never expires.** A token for an
   MCP client in one project reads every project its owner is in. Per-project tokens and an expiry
   (with `strata host token add --project --days`) would narrow what a leaked token gives.
3. **People cannot change their own password**; only an administrator can, by setting one or
   sending a new invitation. A self-service change (with the current password) is the usual
   expectation.
4. **The per-client sign-in limit depends on `--trusted-proxies` being right.** Behind a proxy that
   is not listed, every request comes from the proxy's address: 20 failures from anyone lock out
   everyone using passwords for 15 minutes. `strata host` could warn when it sees `X-Forwarded-For`
   from an address it does not trust.
5. **An OpenID Connect invitation is used up before the identity is linked**, so if that provider
   identity is already linked to another account, the invitation is spent and the person needs a
   new one. Harmless, but confusing.
6. **Membership changes and token creation are not logged** the way sign-ins are. An instance log
   of who granted what would help after an incident.
7. **A project with a symbolic link stops the instance from starting** (finding 1). That fails
   closed; the alternative is to start and refuse that project alone.
