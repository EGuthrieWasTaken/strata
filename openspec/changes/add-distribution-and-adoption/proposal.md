# Proposal: Distribution and adoption (M6)

## Why

A tool aimed at researchers who are not developers fails if installing it
requires Python, and a FOSS alternative to paid platforms gets its first users
by offering a migration path off them. M6 is the ongoing hardening that makes
`strata` adoptable: packaging for every platform, imports from the incumbent
tools, a published worked example, and translations.

Roadmap milestone: M6 (`docs/spec/15-roadmap.md`). Design detail:
`docs/spec/12-architecture.md` §7. Zotero and review-repository CI, also M6, are
separate changes (`add-zotero-integration`, `add-review-repository-ci`).

## What Changes

- Distribution: PyPI (`strata-review`), Homebrew, standalone binaries
  (PyInstaller: macOS universal, Windows x64, Linux x64/musl), Docker, and
  conda-forge.
- A five-minute first-run release criterion tested on all three platforms.
- Import from Covidence, Rayyan, and EPPI-Reviewer exports.
- The export formats deferred from M1: EndNote XML, Excel, and PRISMA-style
  citation lists (already specified in `literature-import`).
- A published worked example review in the repository, doubling as a
  regression test.
- Translations of the externalised user-facing strings.

## Capabilities

### New Capabilities

- `distribution`: release channels and the first-run release criterion.

### Modified Capabilities

- `literature-import`: adds migration imports from Covidence, Rayyan, and
  EPPI-Reviewer.

## Impact

- `release.yml` gains binary, Homebrew, Docker, and conda-forge publishing.
- New parsers and CSV profiles, each with golden fixtures and fuzz-corpus
  entries.
- Screening-decision import from the incumbent tools must mark decisions
  `imported: true`, since their independence cannot be verified.
