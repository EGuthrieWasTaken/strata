"""A hosted `strata` instance: openspec:hosted-deployment.

The service layer behind `strata host`. A team runs one instance from the container image; it
serves several projects (each an ordinary review repository under `<data>/projects/<id>/`) to
several people, each signed in with their own account, and keeps every project in step with its
git remote.

Everything the instance itself knows (accounts, memberships, sessions, the sign-in log, sync
status and secrets) is *instance state*, kept under `<data>/instance/` and never in a review
repository (openspec:hosted-deployment#projects-and-instance-state). The review repositories stay
exactly the format a local install uses, so a project can always be cloned out
(openspec:hosted-deployment#git-is-always-the-backend).

Modules:

- `store`: the instance-state database (SQLite, in `<data>/instance/instance.db`).
- `instance`: the data directory, the instance's settings, and its projects.
- `accounts`: local accounts (Argon2id), invitations, sessions, API tokens, rate-limited and
  logged sign-in.
- `members`: memberships (user, project, actor, role) and what each role may do.
- `secrets`: operator-supplied or encrypted-at-rest secrets, and the git environment that uses a
  project's remote credential.
- `syncloop`: pull before reading, push after committing, conflicts held for a lead.
- `oidc`: optional OpenID Connect (and GitHub) sign-in.

The web adapter is `strata.web.hosted`; the command line is `strata host` in `strata.cli.main`.
"""
