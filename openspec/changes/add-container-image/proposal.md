# Proposal: Container image

## Why

`strata` should run the same way everywhere a review is worked on: on a solo
reviewer's laptop, on each collaborator's machine in a shared-remote setup, in
CI, and as a team's hosted instance. Today that requires Python 3.11+, `uv`, and
a recent git, which is exactly the setup cost that stops a second screener from
being productive in ten minutes. A container image removes it, gives CI and
reproducibility archives a pinned environment, and is the deployable unit for
the hosted instance planned in `add-hosted-team-deployment`.

Roadmap milestone: M5.1 foundation ([docs/roadmap.md](../../../docs/roadmap.md)).
It depends only on the shipped CLI and web UI, so it can land at any time,
ahead of M3–M5.

## What Changes

- An official OCI image built from a `Dockerfile` in this repository, for
  `linux/amd64` and `linux/arm64`, published to the GitHub Container Registry on
  every release, signed, and with an SBOM.
- The image runs any `strata` command against a review repository mounted at
  `/review`, writing files as the host user and taking git identity and remote
  credentials from the host rather than baking them in.
- `strata serve` works from the container: it binds inside the container,
  always requires a session token, prints the URL to open, and validates
  `Host`/`Origin` against a configurable public URL (`--public-url`) instead of
  the bind address.
- An unauthenticated `/healthz` endpoint for container health checks.
- CI builds and smoke-tests the image on pull requests that touch it, runs the
  determinism check inside it, and publishes it on release tags.
- An example `compose.yaml` for running the local web UI.

## Capabilities

### New Capabilities

- `container-image`: the published image, how it mounts a repository, handles
  file ownership and git credentials, serves the web UI, and stays
  deterministic, plus its build and release pipeline.

### Modified Capabilities

- `web-ui`: adds the configurable public URL for `Host`/`Origin` validation and
  the `/healthz` endpoint.
- `cli`: adds `strata serve --public-url`.

## Impact

- New files: `Dockerfile`, `.dockerignore`, `compose.yaml` (example), a
  `container` job in `ci.yml`, and image publishing in `release.yml`.
- `web/security.py` and `web/server.py`: allowed hosts/origins from a public URL;
  `/healthz` route.
- The `distribution` capability in `add-distribution-and-adoption` no longer
  lists Docker; it points here.
- No change to the repository format; no schema-version bump.
