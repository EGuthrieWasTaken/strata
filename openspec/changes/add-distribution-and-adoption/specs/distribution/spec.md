# distribution Specification

## Purpose

Getting `strata` onto every reviewer's machine — including collaborators who
will not install Python — through standard package channels and standalone
binaries, with a tested five-minute first run.

## ADDED Requirements

### Requirement: Release channels

Each release MUST be published to PyPI (as `strata-review` until the `strata`
name is obtained), with standalone binaries for macOS (universal), Windows
(x64), and Linux (x64, musl) attached, and SHOULD also be published as a
Homebrew formula and a conda-forge package. (The container image is
specified separately in the `add-container-image` change.) Release artefacts
MUST be signed and accompanied by an SBOM.

#### Scenario: Collaborator without Python

- **WHEN** a second screener downloads the Windows binary from a release
- **THEN** they can run `strata` without installing Python

### Requirement: Five-minute first run

A first-time user MUST be able to go from nothing to a screening session in
under five minutes on each of the three major platforms. This MUST be tested on
all three as a release criterion.

#### Scenario: Release candidate check

- **WHEN** a release candidate is tested on macOS, Windows, and Linux
- **THEN** a fresh user reaches a screening session in under five minutes on each
