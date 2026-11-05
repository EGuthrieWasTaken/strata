# Running a hosted instance

A *hosted instance* is `strata` running on a server your team controls, so collaborators can screen in a
browser with their own sign-in, without installing anything or knowing git. It is like Overleaf for a
review: every project is still an ordinary `strata` review repository, kept in step with a shared git remote
(GitHub, GitLab, Gitea or a bare repository), so anyone can still clone it and work locally, and the team can
leave the instance at any time.

`strata` is software you run, not a service the project operates: whoever runs the instance is responsible
for it (backups, upgrades, who has an account).

> **Status.** `strata host` is built and tested in-process: sign-in, roles, the sync loop with two members on
> the instance and a third collaborator on a laptop, conflicts, an unreachable remote, isolation between
> projects, blinding between reviewers, and remote MCP. It has been run for real on one machine with
> `--insecure-local-testing` (sign-in, the dashboard, a refused write, signing out). **Not yet tried:** the
> example `docker/hosted/compose.yaml` with Caddy and a real certificate (its structure is tested; it has not
> been run), and a real OpenID Connect provider (tested against a fake one). The security review that is a
> release gate for this mode has not been done yet. See [Known limitations](Known-Limitations).

## What you need

- A server reachable by your collaborators, with Docker and a DNS name (say `strata.example.org`).
- A git remote for each review, and a credential the instance can push with: a **deploy key** with write
  access (GitHub, GitLab, Gitea all offer them per repository) or an HTTPS token.

## Start it with Docker Compose

The repository's `docker/hosted/` folder has a `compose.yaml` and a `Caddyfile`: the instance, and Caddy in
front of it obtaining the TLS certificate. Copy the folder to the server, then:

```
mkdir -p secrets
python3 -c 'import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())' > secrets/strata_instance_key
chmod 600 secrets/strata_instance_key
export STRATA_DOMAIN=strata.example.org
docker compose run --rm strata host init --admin you --admin-name "Your Name" --invite
docker compose up -d
```

`strata_instance_key` encrypts the secrets the instance stores (it is kept out of the data volume on
purpose). `host init` creates the instance and its first administrator, and with `--invite` prints a link you
open to choose your password:

```
initialised instance at /data; administrator you
invitation (valid for 7 days): https://strata.example.org/invite/iqtAhwUlocsz8glZohQIpZis5mBHmnFFLw4xQWCaYW8
```

Only Caddy is reachable from outside (ports 80 and 443); the instance's own port is not published.

### Without Docker

```
strata host init --data /srv/strata --public-url https://strata.example.org --admin you
strata host --data /srv/strata --bind 127.0.0.1 --port 8765
```

and put a TLS-terminating reverse proxy in front of `127.0.0.1:8765` that passes the `Host` header and sets
`X-Forwarded-Proto`. If the proxy is not on the same machine, tell the instance its address with
`--trusted-proxy`.

## Add a project

A project is a review repository. To put an existing review on the instance, clone it from its remote with a
credential:

```
docker compose run --rm strata host project add spacing \
  --remote git@github.com:lab/spacing-review.git --credential ssh-key:spacing-deploy-key
```

`ssh-key:spacing-deploy-key` names a *secret*, not a file: the private key is the container secret
`secrets/spacing-deploy-key` in `compose.yaml` (or an environment variable `STRATA_SECRET_SPACING_DEPLOY_KEY`,
or stored encrypted with `strata host secret set spacing-deploy-key < id_ed25519`). For HTTPS use
`--credential token:<name>`. A remote URL with a password or token written into it is refused, because it would
be stored in plain text.

To start a brand-new review on the instance instead, leave out `--remote` and name its first actor:

```
strata host project add pilot --title "Pilot review" --actor you --actor-name "Your Name"
```

Then see who is where:

```
strata host project list
spacing Spacing review  2 member(s)     git@github.com:lab/spacing-review.git  last synced never
```

Next: [Inviting collaborators](Inviting-Collaborators).

## Settings

`instance.toml` in the data volume's `instance/` folder:

```toml
public_url = "https://strata.example.org"

[committer]                 # who git records as the committer of the instance's commits
name = "Spacing lab strata"
email = "strata@lab.example.org"

[sync]
interval_seconds = 30       # how stale a project may be before a page pulls first

[sessions]
idle_minutes = 120          # signed out after this long without a request
hours = 12                  # and after this long regardless
```

Sign-in providers (`[[oidc]]`) are described in [Inviting collaborators](Inviting-Collaborators#signing-in-with-github-or-your-institution).

## What the instance protects

- **HTTPS only.** A plain-HTTP request is redirected to HTTPS (a form post is refused), so no session is ever
  issued over plain HTTP. `--insecure-local-testing` turns this off for trying an instance on your own machine;
  never use it for one other people reach.
- **Session cookies** are `Secure`, `HttpOnly`, `SameSite=Strict` and expire; every form carries a CSRF token.
- **Sign-in is rate limited**: five failures for an account (or twenty from one address) within 15 minutes
  lock it for 15 minutes. Every sign-in, refused or not, is logged: `strata host signins`.
- **`Host` and `Origin`** must match the public URL.
- **No inactivity exit.** Unlike `strata serve`, the instance keeps running.
- **Secrets stay in the instance.** Passwords are Argon2id hashes; remote credentials and provider secrets come
  from the operator or are stored encrypted; none is ever written to a review repository or shown in a page.

`GET /healthz` answers `{"status":"ok"}` without a session; the image's health check uses it.

## Backups and restoring

**The git remotes are the backup of record.** Everything anyone decided is in a project's repository, and the
instance pushes after every commit. What the remotes do not hold is the instance's own state: accounts,
memberships, sessions, the sign-in log, and any commit not yet pushed (the dashboard says when a push is
waiting). Back up the `strata-data` volume as well, and keep `secrets/strata_instance_key` somewhere safe:
without it, stored secrets cannot be decrypted.

To restore from the remotes alone (the volume is lost): start a new instance with `host init`, add each
project again with `host project add <id> --remote <url>`, recreate the accounts (`host user add --invite`)
and memberships (`host member add`). Every decision comes back with the repositories.

## Upgrading

```
docker compose pull      # or rebuild: docker compose build
docker compose up -d
```

Review repositories need no migration (the instance does not change their format). Sessions survive an
upgrade; a screening batch that was not yet committed is safe on disk and is committed at the next sync.
