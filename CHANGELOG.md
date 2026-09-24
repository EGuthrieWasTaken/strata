# Changelog

All notable changes to `strata` are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- `strata dedup [--by ACTOR] [--review] [--strict] [--undo CANONICAL ABSORBED]`:
  thresholds and actions (`docs/spec/05-workflow-import.md` §3.4), field-wise
  merge semantics with `strata.field_provenance` and an `aliases.ndjson`
  entry per merge (§3.5, nothing ever deleted), an interactive `--review`
  queue (`[m]erge`/`[k]eep both`/`[s]kip`/`[o]pen both`/`[?]help`, §3.6),
  sticky judged-pair tracking so a merged, kept, or undone pair is never
  re-raised, and `--undo` to reverse a wrong merge. `strata.dedup.merge` and
  `strata.dedup.engine` are the new pure-merge and repo-orchestration
  modules; both at 100% line+branch coverage.
- A labelled dedup benchmark (`tests/fixtures/dedup-benchmark/`, 55
  synthesised records — not a real ASySD/`revtools` export, see that
  directory's `README.md`) enforced by
  `tests/integration/test_dedup_benchmark.py` and published at
  [`docs/dedup-benchmark-results.md`](docs/dedup-benchmark-results.md)
  (§3.8: recall 1.000, false-merge rate 0.0000 against the v1 targets of
  >= 0.95 / <= 0.001). `strata.dedup.benchmark` holds the metric
  definitions; `scripts/dedup_benchmark.py` regenerates the report from the
  same function the test asserts against, so they cannot drift apart.
- A 50,000-record dedup performance check (`tests/benchmark/`, advisory CI
  tier per §3.7's normative time/memory budget — not part of the blocking
  merge gate, per this file's own sub-objective 6 notes below).
- The deduplication engine's pure blocking and scoring functions
  (`strata.dedup.blocking`, `strata.dedup.scoring`): all six
  `docs/spec/05-workflow-import.md` §3.2 block keys (including a genuine
  128-permutation MinHash/LSH over title 3-grams), and the §3.3 pairwise
  scoring formula with its DOI veto. Property-tested for symmetry (P8).
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
