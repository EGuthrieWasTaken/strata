# Changelog

All notable changes to `strata` are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- The specification now lives entirely in [OpenSpec](openspec/README.md):
  29 capability specs under `openspec/specs/` (M0–M2.1), each with a
  `spec.md` of requirements and WHEN/THEN scenarios and a `design.md` of
  rationale and worked examples, and the unbuilt milestones as change
  proposals under `openspec/changes/`. The long-form `docs/spec/` documents
  were converted and then retired (archived OpenSpec change
  `retire-docs-spec`): the overview, roadmap, and open questions moved to
  `docs/`, and every reference in code, tests, scripts, workflows, templates,
  and JSON Schemas now cites `openspec:<capability>#<requirement>`.
  `scripts/check_docs.py` was rewritten (links, anchors, config blocks, a
  capability index, resolution of every `openspec:` reference, and a guard
  against references to the retired directory) with unit tests, and the
  `docs` CI job also runs `openspec validate --all --strict` (OpenSpec 1.13.2,
  telemetry disabled). The OpenSpec Claude Code skills and `/opsx:*`
  commands are installed under `.claude/`.
- Planned (OpenSpec changes, not yet implemented): a container image
  (`add-container-image`) and a self-hosted team instance with per-user
  accounts and an automatic git sync loop (`add-hosted-team-deployment`),
  following the decision to support hosted collaboration with git as the
  backend (`docs/open-questions.md`, Q11).

- A fuzz corpus for `ingest.parsers` (`tests/fuzz/`, `hypothesis`-driven
  mutation of the real fixture corpus, wired into the nightly `fuzz` job)
  and a requirement-traceability report (`scripts/traceability_report.py`,
  an advisory CI job uploading it as a build artefact) per
  `docs/spec/14-testing.md` §6/§10.5. New property tests close the M0 gap
  for **P3** (serialisation round-trip) and **P7** (alias acyclicity);
  P1/P2/P4/P5/P6/P9/P13 and four `strata verify` error-code tests were
  retrofitted with the `@pytest.mark.req(...)` marker the report reads.
  New `tests/e2e/test_e2e_07_...` and `tests/benchmark/test_import_performance.py`
  close two previously-untested M1 acceptance-checklist items.
- `strata records list [--filter EXPR] [--format tsv|json|csl] [--all]`,
  `strata records show <id>`, `strata why <id>`, and
  `strata fix <id> --field <f> --value <v> --by <actor>`
  (`docs/spec/10-cli.md` §2), plus the filter expression language §3
  requires (`strata.core.filters`: a hand-written recursive-descent parser
  and AST interpreter, no `eval`/`exec`, with a static nested-quantifier
  guard against catastrophic regex backtracking in `matches`). `strata why`
  walks the event log for a record's full search → import → dedup
  provenance chain, satisfying that part of the M1 acceptance bar. Record
  ids may be abbreviated to any unambiguous prefix, as in git, for these
  three commands. All new modules at 100% line+branch coverage.
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

### Fixed

- `decode_bytes` crashed with an uncaught `UnicodeDecodeError` on a file that
  has a valid UTF-8 byte-order mark but corrupted/truncated bytes after it,
  instead of falling through to cp1252/latin-1 like the no-BOM path already
  did — found by the new fuzz corpus within minutes of it existing.
- `strata.core.events.append_new_event`, called once per item in a loop
  (`strata import`'s one `record-add` event per row; `strata dedup`'s one
  `dedup-merge` event and `aliases.append_alias` call per auto-merge), read
  and re-parsed its entire target file on every single call, making an
  O(n)-item operation O(n^2). A 50,000-record import that used to still be
  running after five-plus minutes now completes in ~20s; 50,000-record dedup
  dropped from over 240s to ~126s. New `append_new_events` batches a run's
  worth of appends into one read plus one write per event.
