# Design: Container image

## Context

The CLI, the local web UI, and the MCP server all operate on a working tree and
shell out to git (only through `gitio`). Nothing in them assumes a particular
host, so a container is a packaging problem, not an architectural one. The
interesting parts are the edges: file ownership on bind mounts, git's
`safe.directory` check, credentials, and the web UI's localhost security model.

## Goals / Non-Goals

**Goals:**

- `docker run ... strata <command>` is a drop-in replacement for an installed
  `strata`, on Linux, macOS (Docker Desktop / Podman), and Windows (WSL2).
- The same image is the unit of deployment for a hosted instance.
- Output is byte-identical to a native run (the determinism guarantees hold).

**Non-Goals:**

- Hosted multi-user behaviour (authentication, sync loop, multi-tenancy) — that
  is `add-hosted-team-deployment`, which consumes this image.
- Shipping R in the default image. A separate `-metafor` variant MAY follow once
  the analysis engine exists.
- Kubernetes manifests or a Helm chart.

## Decisions

- **Base image: official `python:3.12-slim`, pinned by digest**, with `git`
  installed from the distribution. A slim Debian base keeps glibc (needed by
  numpy/scipy wheels) without a build toolchain. Alpine was rejected: musl
  wheels for the scientific stack are slower to install and a frequent source of
  subtle numeric differences. Distroless was rejected because git needs a shell
  environment for hooks.
- **Multi-stage build with `uv sync --frozen` from `uv.lock`**, so the image
  contains exactly the locked dependency set and no build tools.
- **Non-root by default (uid 10001), overridable with `--user`.** For bind
  mounts the documented invocation is `--user "$(id -u):$(id -g)"` so files are
  owned by the host user. `HOME` points at a writable directory so git can run
  under an arbitrary uid.
- **`safe.directory = *` in the container's system git config.** Git refuses to
  operate on repositories owned by another uid ("dubious ownership"), which is
  the normal case for bind mounts and for a hosted instance serving several
  repositories. The setting is scoped to the container filesystem, which holds
  only repositories the operator mounted; a per-path allow-list was rejected
  because hosted repositories live at paths chosen at runtime.
- **Credentials come from the host, never the image.** Git identity via the
  standard `GIT_AUTHOR_*`/`GIT_COMMITTER_*` variables or a mounted read-only
  `.gitconfig`; remotes via a forwarded SSH agent socket or a credential helper /
  token supplied at runtime (environment variable or Docker secret). The image
  build never receives a credential, and `strata` never writes one into the
  repository.
- **`strata serve` in a container binds `0.0.0.0` and always requires a
  token.** Publishing a port only works if the server listens beyond the
  container's loopback, so the existing rule ("a non-loopback bind requires
  `--token`") applies automatically; the entrypoint generates a token when none
  is given and prints the full URL. Documentation publishes the port to the
  host's loopback only (`-p 127.0.0.1:8765:8765`).
- **`--public-url` decouples header validation from the bind address.** Today
  `Host`/`Origin` are derived from the address the server bound to, which inside
  a container is `0.0.0.0` and never what the browser sends. The operator states
  the URL the browser will use (`http://localhost:8765`, or the hosted
  instance's `https://strata.example.edu`), and validation checks against it.
  This keeps the DNS-rebinding defence intact rather than disabling it.
- **`/healthz` is unauthenticated and returns no repository data**, so container
  orchestration can probe liveness without a session.
- **Published to GHCR** as `ghcr.io/eguthriewastaken/strata:<version>` plus
  `:latest`, signed with cosign (keyless, via the release workflow's OIDC
  identity) and with an SBOM attached, matching the existing release
  requirements. Consumers are told to pin by digest.

## Usage sketch

```
# One-off command against the current directory
docker run --rm --user "$(id -u):$(id -g)" -v "$PWD":/review \
  -e GIT_AUTHOR_NAME -e GIT_AUTHOR_EMAIL \
  ghcr.io/eguthriewastaken/strata:0.2.0 status

# Local web UI
docker run --rm --user "$(id -u):$(id -g)" -v "$PWD":/review \
  -p 127.0.0.1:8765:8765 \
  ghcr.io/eguthriewastaken/strata:0.2.0 serve --port 8765 --public-url http://localhost:8765

# strata sync with the host's SSH agent
docker run --rm --user "$(id -u):$(id -g)" -v "$PWD":/review \
  -v "$SSH_AUTH_SOCK":/ssh-agent -e SSH_AUTH_SOCK=/ssh-agent \
  ghcr.io/eguthriewastaken/strata:0.2.0 sync
```

## Risks / Trade-offs

- **Bind-mount ownership differs by platform.** Docker Desktop on macOS and
  Windows remaps ownership; rootless Podman maps uids differently again. The
  smoke tests cover Linux; macOS/Windows behaviour is covered by documentation
  and the cold-install job.
- **File watching and fsync semantics on some Docker Desktop file-sharing
  backends are weaker than native filesystems.** The append-then-fsync crash
  safety guarantee holds for the container's view; documentation recommends
  native filesystems (WSL2 paths on Windows) for long screening sessions.
- **Image size.** numpy and scipy dominate. The target is kept honest by
  reporting the compressed size in each release rather than by a hard limit.
