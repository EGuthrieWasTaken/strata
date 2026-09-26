# container-image Specification

## Purpose

An official container image that runs every `strata` command and the web UI
identically to a native install, for solo use, for collaborators sharing a git
remote, for CI, and as the deployable unit of a hosted instance.

## ADDED Requirements

### Requirement: Published multi-architecture image

The project MUST publish an OCI image built from the repository's `Dockerfile`
for `linux/amd64` and `linux/arm64` on every release, tagged with the release
version. The image MUST be built from a base image pinned by digest and from the
locked dependency set in `uv.lock`, MUST include git 2.23 or newer, MUST NOT
contain build toolchains or credentials, and MUST be signed and accompanied by an
SBOM like every other release artefact.

#### Scenario: Pulling a release

- **WHEN** a user pulls the image for release `0.2.0` on an arm64 laptop
- **THEN** they receive a native arm64 image whose signature verifies and whose `strata --version` reports `0.2.0`

#### Scenario: No baked-in secrets

- **WHEN** the published image's filesystem and history are inspected
- **THEN** no git credential, token, or SSH key is present

### Requirement: Runs against a mounted repository

The image's entrypoint MUST be `strata` with `/review` as the working directory,
so `docker run -v <repo>:/review <image> <command>` runs `<command>` against the
mounted repository. The container MUST run as a non-root user by default, MUST
work under an arbitrary `--user` uid/gid so files it writes are owned by the host
user, and MUST configure git so it operates on mounted repositories owned by a
different uid. It MUST NOT modify files outside the mounted repository.

#### Scenario: Status from the container

- **GIVEN** a review repository in the current directory
- **WHEN** `docker run --rm --user "$(id -u):$(id -g)" -v "$PWD":/review <image> status` runs
- **THEN** it prints the same status as a native `strata status`

#### Scenario: File ownership

- **WHEN** a screening decision is recorded through the container run with `--user "$(id -u):$(id -g)"`
- **THEN** the appended event file on the host is owned by the host user

#### Scenario: Different owner

- **GIVEN** a mounted repository owned by a uid different from the container user
- **WHEN** a command that invokes git runs
- **THEN** git does not refuse the repository for dubious ownership

### Requirement: Credentials come from the host at runtime

Git identity MUST be taken from the standard git environment variables or a
mounted git configuration, and remote credentials from a forwarded SSH agent, a
mounted credential helper, or a runtime-supplied token. The image MUST NOT
require credentials at build time, and `strata` MUST NOT write any credential
into the repository or the image.

#### Scenario: Sync with a forwarded SSH agent

- **GIVEN** the host's SSH agent socket is mounted and `SSH_AUTH_SOCK` points to it
- **WHEN** `strata sync` runs in the container
- **THEN** it authenticates to the remote with the host's keys and nothing credential-related is written to disk

### Requirement: Web UI from the container

`strata serve` in the container MUST listen on all container interfaces so a
published port works, MUST always require a session token, and MUST print the
full URL (including the token) to open. When no token is supplied it MUST
generate one. Documentation MUST publish the port to the host's loopback
interface by default.

#### Scenario: Starting the local web UI

- **WHEN** `docker run -p 127.0.0.1:8765:8765 <image> serve --port 8765 --public-url http://localhost:8765` starts
- **THEN** the logs show `http://localhost:8765/?token=...` and requests without the session are refused

### Requirement: Health check

The image MUST declare a health check that probes `/healthz`, and `/healthz`
MUST respond without requiring a session and without returning any repository
data.

#### Scenario: Orchestrator probe

- **WHEN** a container orchestrator requests `/healthz` on a running server
- **THEN** it receives HTTP 200 with no record, criterion, or actor information

### Requirement: Deterministic inside and outside the container

Every generated file MUST be byte-identical whether produced by the container or
by a native install from the same repository state and `strata` version.

#### Scenario: Determinism check in CI

- **WHEN** the determinism check runs once natively and once in the image
- **THEN** every generated file is byte-identical

### Requirement: Image CI

Pull requests that change the `Dockerfile`, dependencies, or source MUST build the
image for both architectures and smoke-test `--version`, `init`, `verify`, and
`serve` with `/healthz`; this job MUST feed the `gate` check. The `Dockerfile`
MUST be linted, and third-party actions used MUST be pinned by commit SHA.

#### Scenario: Broken image

- **WHEN** a pull request removes git from the image
- **THEN** the container smoke test fails and `gate` blocks the merge
