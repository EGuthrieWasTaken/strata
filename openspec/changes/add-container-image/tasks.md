# Tasks

## 1. Image

- [ ] 1.1 Add a multi-stage `Dockerfile` (`python:3.12-slim` pinned by digest, `uv sync --frozen`, `git` installed, non-root uid 10001, writable `HOME`, `WORKDIR /review`, entrypoint `strata`) and a `.dockerignore`
- [ ] 1.2 Set `safe.directory = *` in the container's system git config and document why
- [ ] 1.3 Add a `HEALTHCHECK` using `/healthz`
- [ ] 1.4 Add an example `compose.yaml` for the local web UI (loopback-published port, repository bind mount, token from an environment variable)

## 2. Web UI changes

- [ ] 2.1 Add `strata serve --public-url` (and `STRATA_PUBLIC_URL`); derive allowed `Host`/`Origin` values from it when given
- [ ] 2.2 Make the image's entrypoint generate a token for `serve` when none is supplied and print the tokenised public URL (the native CLI keeps refusing a non-loopback bind without `--token`)
- [ ] 2.3 Add the unauthenticated `/healthz` route returning no repository data

## 3. CI and release

- [ ] 3.1 Add a `container` job to `ci.yml`, path-filtered to `Dockerfile`, `.dockerignore`, `pyproject.toml`, `uv.lock`, and `src/`, that builds both architectures and smoke-tests `--version`, `init`, `verify`, and `serve` + `/healthz`; wire it into `gate`
- [ ] 3.2 Lint the `Dockerfile` (hadolint, pinned by SHA)
- [ ] 3.3 Run `scripts/determinism_check.py` inside the image and compare with a native run
- [ ] 3.4 Publish to GHCR on release tags with cosign signing and an attached SBOM
- [ ] 3.5 Add the image to the nightly `cold-install` job

## 4. Documentation

- [ ] 4.1 Wiki page: running `strata` in Docker (one-off commands, web UI, sync with SSH agent, file ownership, Windows/macOS notes)
- [ ] 4.2 README install section: add the container option
- [ ] 4.3 Remove Docker from `add-distribution-and-adoption`'s scope (done in this change's proposal) and cross-reference

## 5. Tests

- [ ] 5.1 Unit tests for public-URL-derived `Host`/`Origin` validation, including DNS-rebinding rejection
- [ ] 5.2 Integration test for `/healthz` (200, no repository data, no session required)
- [ ] 5.3 CLI test for `--public-url` parsing and its exit code on an invalid URL
