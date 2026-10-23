# Running strata in a container

The image (`Dockerfile`; openspec change `add-container-image`) runs every `strata` command, and the
local web UI, against a review repository mounted at `/review`. Nothing in it is specific to a
platform: it is `strata` and `git` on a slim Debian base, as an unprivileged user.

> **Status.** Built and smoke-tested by CI on amd64 and arm64 (the `container` jobs in `ci.yml`, and
> `.github/workflows/container.yml`, which publishes the image to `ghcr.io/eguthriewastaken/strata` tagged
> `sha-<commit>`, plus `pr-<n>` or `edge`, and pulls it back from the registry): `--version`, `git`, `init`,
> `verify` and `status` against a mounted repository as the host user and as a different uid, then `serve`
> with its generated token, the `/healthz` probe, Docker's health status and the Host checks. Not yet tried by
> hand: Docker Desktop on macOS or Windows, an SSH agent for `strata sync`, and `compose.yaml` (its structure
> is tested; it has not been run). Until a release is tagged, use one of those tags (a package created by a
> workflow starts private; make it public in the repository's package settings to pull it without logging
> in), or build it yourself: `docker build -t strata .`

## One-off commands

```
docker run --rm --user "$(id -u):$(id -g)" -v "$PWD":/review \
  -e GIT_AUTHOR_NAME -e GIT_AUTHOR_EMAIL -e GIT_COMMITTER_NAME -e GIT_COMMITTER_EMAIL \
  strata status
```

- `--user "$(id -u):$(id -g)"` makes the files strata writes belong to you. Without it the container
  runs as uid 10001 and, on Linux, the new files belong to that uid.
- Git needs an identity for the commits strata makes: pass the standard variables above, or mount a
  `.gitconfig` read-only (`-v ~/.gitconfig:/home-strata/.gitconfig:ro`).
- Git refuses a repository owned by another uid ("dubious ownership"). The image sets
  `safe.directory = *` in its *system* git configuration, which only ever applies to repositories you
  mount into the container.

## The web UI

```
docker run --rm --user "$(id -u):$(id -g)" -v "$PWD":/review \
  -p 127.0.0.1:8765:8765 strata serve --actor you
```

It prints `http://localhost:8765/?token=...`; open that. Inside the container `serve` listens on all
interfaces (so the published port works), always has a session token (yours in `STRATA_TOKEN` or
`--token`, otherwise a new one every start) and checks `Host` and `Origin` against the URL a browser
uses (`STRATA_PUBLIC_URL` or `--public-url`, default `http://localhost:<port>`). Publish the port to
your loopback (`127.0.0.1:`) unless you mean to share it; if you publish on a different host port,
say so: `-p 127.0.0.1:9000:8765 ... serve --public-url http://localhost:9000`.

`compose.yaml` does the same: `STRATA_ACTOR=you docker compose up`.

`GET /healthz` answers without a session and says only `{"status":"ok"}` (or 503 and
`{"status":"unavailable"}` when the repository cannot be read). The image's `HEALTHCHECK` uses it.

## Syncing

`strata sync` needs your remote's credentials, which the image never contains. Forward your SSH agent:

```
docker run --rm --user "$(id -u):$(id -g)" -v "$PWD":/review \
  -v "$SSH_AUTH_SOCK":/ssh-agent -e SSH_AUTH_SOCK=/ssh-agent \
  -e GIT_AUTHOR_NAME -e GIT_AUTHOR_EMAIL strata sync
```

(The agent socket's permissions must allow the `--user` you run as; on macOS and Windows the Docker
Desktop documentation describes agent forwarding for your setup.) The container's `known_hosts` is
empty: the first connection to a host fails unless you mount yours (`-v ~/.ssh/known_hosts:/home-strata/.ssh/known_hosts:ro`).

## Notes and limits

- **Platforms.** Linux is what the smoke test covers. Docker Desktop on macOS and Windows remaps file
  ownership, so `--user` matters less there; keep long screening sessions on a native filesystem
  (WSL2's, not `/mnt/c`), because some Docker Desktop file-sharing backends have weaker `fsync`.
- **Determinism.** The same repository state and strata version produce byte-identical generated
  files natively and in the image; CI compares the determinism fixture across the two.
- **No R.** The default image has no R, so `analysis.engine = "metafor"` cross-checks are not
  available in it; the native engine is.
- **Hosted use.** The image is the unit that `add-hosted-team-deployment` builds on; accounts,
  multi-tenancy and a sync loop are not part of it.
