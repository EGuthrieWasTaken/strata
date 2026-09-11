# Changelog

All notable changes to `strata` are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- The pull-request gate: tiered CI (`lint`, `test-fast`, `test` across a 3 OS
  x 3 Python matrix, `statistical`, `determinism`, `coverage`, `docs`,
  advisory `benchmark`/`codeql`), the always-running `gate` check, and the
  specification integrity checks in `scripts/check_docs.py`.
- M0 substrate: canonical serialisation (`core.canon`), identity and
  normalisation (`core.ids`), the event log and hash chain (`core.events`),
  the pure fold (`core.fold`), repository discovery and locking (`core.repo`).
- `strata init`, `clone`, `doctor`, `config`, `actor add|list|deactivate`,
  `verify`, `status`, `log`.
- `.gitattributes`, merge driver installation, and versioned git hooks
  (`pre-commit`, `commit-msg`, `post-merge`, `post-checkout`).
