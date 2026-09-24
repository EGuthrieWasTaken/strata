# Changelog

All notable changes to `strata` are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- The deduplication engine's pure blocking and scoring functions
  (`strata.dedup.blocking`, `strata.dedup.scoring`): all six
  `docs/spec/05-workflow-import.md` §3.2 block keys (including a genuine
  128-permutation MinHash/LSH over title 3-grams), and the §3.3 pairwise
  scoring formula with its DOI veto. Property-tested for symmetry (P8).
  Thresholds, actions, the review queue, and merge semantics are not built
  yet.
- `strata import`: copies a bibliographic export unmodified, parses it,
  normalises and assigns record ids, appends to an existing record's sources
  on an exact-id match instead of duplicating it, and commits — idempotent by
  file digest, one commit per file. Adds `records/records.ndjson` read/write
  (`core.records`), the `record` and `import-manifest` JSON schemas, and a
  `strata verify` check for every record's schema.
- Bibliographic export parsers for CSL-JSON, RIS, BibTeX, PubMed/MEDLINE, and
  CSV/TSV (`strata.ingest.parsers`), tolerant of the malformations
  `docs/spec/05-workflow-import.md` §2.1 requires (BOM, CRLF/CR, non-UTF-8
  encodings, missing RIS `ER` lines, HTML entities), with a golden fixture
  corpus under `tests/fixtures/exports/`. CSV/TSV column mapping
  (`strata import --map field=Column,...`) and detection profiles for six
  platforms (Scopus, Web of Science, EBSCOhost, ProQuest, Dimensions, Google
  Scholar via Publish or Perish) under `strata.ingest.profiles`.
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
