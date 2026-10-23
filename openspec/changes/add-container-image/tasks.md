# Tasks

## 1. Image

- [ ] 1.1 Add a multi-stage `Dockerfile` (`python:3.12-slim` pinned by digest, `uv sync --frozen`, `git` installed, non-root uid 10001, writable `HOME`, `WORKDIR /review`, entrypoint `strata`) and a `.dockerignore`
- [ ] 1.2 Set `safe.directory = *` in the container's system git config and document why
- [ ] 1.3 Add a `HEALTHCHECK` using `/healthz`
- [ ] 1.4 Add an example `compose.yaml` for the local web UI (loopback-published port, repository bind mount, token from an environment variable)

## 2. Web UI changes

- [x] 2.1 Add `strata serve --public-url` (and `STRATA_PUBLIC_URL`); derive allowed `Host`/`Origin` values from it when given
- [x] 2.2 Make the image's entrypoint generate a token for `serve` when none is supplied and print the tokenised public URL (the native CLI keeps refusing a non-loopback bind without `--token`)
- [x] 2.3 Add the unauthenticated `/healthz` route returning no repository data

## 3. CI and release

- [ ] 3.1 Add a `container` job to `ci.yml`, path-filtered to `Dockerfile`, `.dockerignore`, `pyproject.toml`, `uv.lock`, and `src/`, that builds both architectures and smoke-tests `--version`, `init`, `verify`, and `serve` + `/healthz`; wire it into `gate`
- [x] 3.2 Lint the `Dockerfile` (hadolint, pinned by SHA)
- [ ] 3.3 Run `scripts/determinism_check.py` inside the image and compare with a native run
- [ ] 3.4 Publish to GHCR on release tags with cosign signing and an attached SBOM
- [ ] 3.5 Add the image to the nightly `cold-install` job

## 4. Documentation

- [ ] 4.1 Wiki page: running `strata` in Docker (one-off commands, web UI, sync with SSH agent, file ownership, Windows/macOS notes)
- [x] 4.2 README install section: add the container option
- [x] 4.3 Remove Docker from `add-distribution-and-adoption`'s scope (done in this change's proposal) and cross-reference

## 5. Tests

- [x] 5.1 Unit tests for public-URL-derived `Host`/`Origin` validation, including DNS-rebinding rejection
- [x] 5.2 Integration test for `/healthz` (200, no repository data, no session required)
- [x] 5.3 CLI test for `--public-url` parsing and its exit code on an invalid URL

## Notes

Written and checked without a container runtime: hadolint accepts the `Dockerfile`, actionlint accepts
every workflow, the entrypoint and the web changes are tested; **no image has been built or run**.

- 1.1: the `Dockerfile` and `.dockerignore` exist and are multi-stage, `uv sync --frozen`, non-root uid
  10001, `WORKDIR /review`, but the base image is `python:3.12-slim` by tag, not by digest (Docker Hub
  rate-limited the lookup); dependabot's docker ecosystem is configured to maintain a pin once one is added.
  Left open for the digest and for a first real build.
- 1.2 / 1.3 / 1.4: `safe.directory = *`, the `HEALTHCHECK` on `/healthz` and `compose.yaml` are written (the
  probe's endpoint and the compose structure are tested); left open until they have been seen working in
  a built image.
- 3.1: the `container` job (both architectures natively, hadolint, smoke test, determinism comparison) is
  in `ci.yml` and wired into `gate`; it has not run on GitHub.
- 3.3: the determinism comparison is a step of that job; not yet run.
- 3.4: GHCR publishing with BuildKit SBOM and provenance is in `release.yml`; **cosign signing is not
  done** (same reason as the Sigstore note in `release.yml`), and nothing has been published.
- 3.5: `cold-install-container` is in `nightly.yml`; not yet run.
- 4.1: written as `docs/container.md` in the repository, not as a wiki page; open until the wiki page exists.

