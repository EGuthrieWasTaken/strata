# Design: Distribution and adoption

## Context

`strata` currently runs from a checkout with `uv`. The second screener in a
review — often at another institution, contributing twenty hours — will not
install Python. Adoption also depends on a migration path off the paid tools
teams already use.

## Goals / Non-Goals

**Goals:**

- Nothing to a screening session in under five minutes on macOS, Windows, and
  Linux.
- An explicit migration path from Covidence, Rayyan, and EPPI-Reviewer.

**Non-Goals:**

- The container image, which is its own change (`add-container-image`) because
  it is also the unit of the hosted deployment and can land earlier.

## Decisions

| Channel | Notes |
|---|---|
| PyPI | `pipx install strata-review` / `uv tool install strata-review` — the primary path; the `strata` name is being claimed via PEP 541 |
| Homebrew | macOS and Linux formula |
| Standalone binaries | PyInstaller builds for macOS (universal), Windows (x64), Linux (x64, musl) attached to each release |
| Conda-forge | Follow-on; the academic audience uses it heavily |

- **The first-run time is a tested release criterion**, not an aspiration: the
  nightly `cold-install` job installs each published artefact from scratch and
  runs the quickstart.
- **Imported decisions are marked `imported: true`**, because their
  independence cannot be verified, so IRR and Methods text stay honest.

## Risks / Trade-offs

- PyInstaller binaries are large and occasionally flagged by antivirus
  software; signing and publishing checksums mitigates the latter.
