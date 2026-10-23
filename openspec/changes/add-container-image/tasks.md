# Tasks

## 1. Image

- [x] 1.1 Add a multi-stage `Dockerfile` (`python:3.12-slim` pinned by digest, `uv sync --frozen`, `git` installed, non-root uid 10001, writable `HOME`, `WORKDIR /review`, entrypoint `strata`) and a `.dockerignore`
- [x] 1.2 Set `safe.directory = *` in the container's system git config and document why
- [ ] 1.3 Add a `HEALTHCHECK` using `/healthz`
- [ ] 1.4 Add an example `compose.yaml` for the local web UI (loopback-published port, repository bind mount, token from an environment variable)

## 2. Web UI changes

- [x] 2.1 Add `strata serve --public-url` (and `STRATA_PUBLIC_URL`); derive allowed `Host`/`Origin` values from it when given
- [x] 2.2 Make the image's entrypoint generate a token for `serve` when none is supplied and print the tokenised public URL (the native CLI keeps refusing a non-loopback bind without `--token`)
- [x] 2.3 Add the unauthenticated `/healthz` route returning no repository data

## 3. CI and release

- [x] 3.1 Add a `container` job to `ci.yml`, path-filtered to `Dockerfile`, `.dockerignore`, `pyproject.toml`, `uv.lock`, and `src/`, that builds both architectures and smoke-tests `--version`, `init`, `verify`, and `serve` + `/healthz`; wire it into `gate`
- [x] 3.2 Lint the `Dockerfile` (hadolint, pinned by SHA)
- [x] 3.3 Run `scripts/determinism_check.py` inside the image and compare with a native run
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

The first run on GitHub built the image on amd64 and arm64 and passed the smoke test; open items are the ones
that run has not covered.

- 1.1, 1.2, 3.1 and 3.3 are done and were seen working on GitHub: the image built on amd64 and arm64, the smoke
  test (init, verify and status as the host user and as another uid, so `safe.directory` works; serve with its
  token; `/healthz`) passed, and the determinism fixture was byte-identical natively and in the image. The base
  image is pinned by digest (the index digest of `python:3.12-slim`, taken from a registry lookup in CI).
- 1.3 / 1.4: the `HEALTHCHECK` is declared and the smoke test now waits for Docker to report the container
  healthy (tick 1.3 once that has been seen on a run); `compose.yaml`'s structure is tested but it has not been run.
- 3.4: GHCR publishing with BuildKit SBOM and provenance is in `release.yml`; **cosign signing is not
  done** (same reason as the Sigstore note in `release.yml`); the release-tag publish has not run, while the
  `container.yml` publish for pull requests has.
- 3.5: `cold-install-container` is in `nightly.yml`; not yet run.
- 4.1: written as `docs/container.md` in the repository, not as a wiki page; open until the wiki page exists.
- 3.4 (addendum): `.github/workflows/container.yml` publishes the image to GHCR on pull requests that touch it and
  on `main` (tags `sha-<commit>`, `pr-<n>`, `edge`), then pulls it back and smoke-tests it on both architectures;
  it passed on the first run (PR 48).
