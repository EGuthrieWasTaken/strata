# M1 ("Literature in") — sub-objective plan

Not part of the specification in `docs/spec/` (which is normative/informative
design content executed once) — this is a working implementation-tracking
note for whichever agent or session picks up M1 next, kept outside
`docs/spec/` deliberately so it isn't subject to that tree's own
document-map/link integrity checks (`scripts/check_docs.py`).

## Why this file exists

Per `docs/spec/15-roadmap.md`, M1 is a 4–6 week milestone: all parsers, search
recording, `strata import` with CSV mapping profiles, the deduplication
engine and review queue, and `strata records`/`why`/`fix`, plus a golden
parser corpus, a labelled dedup benchmark, a fuzz corpus, and property test
P8. That is too large for one sitting. It is broken into the sub-objectives
below, each scoped to be completable (implemented, tested, lint/type clean,
committed) in a single sitting. Update the status table as work lands so the
next session can pick up without re-deriving context.

## M0 status (verified before M1 work started)

M0 is solid: 177 tests passed at the time of verification (205 after M1.1
landed), the CI gate (lint, test-fast, 3 OS × 3 Python matrix, statistical,
determinism, coverage, advisory benchmarks, aggregating `gate` job) matches
spec, `init`/`clone`/`doctor`/`config`/`actor`/`verify`/`status`/`log` all
work, and E2E-02 (disjoint concurrent clones merge conflict-free) passes.
Property tests P1, P2, P4, P5, P6, P9, P13 pass under `hypothesis`.

Two known gaps, carried forward into M1.8 below rather than blocking M1:

- P3 (serialisation round-trip) and P7 (alias acyclicity) are verified by
  fixed unit tests, not `hypothesis`-generated property tests.
- The requirement-traceability report from `docs/spec/14-testing.md` §10.5
  (a CI step collecting `@pytest.mark.req` markers into a coverage-of-spec
  report) was never built. Only `tests/e2e/test_e2e_02_concurrent_clones.py`
  uses the marker.

Branch-protection settings on `main` could not be verified from within a
session (no tool for it) — check via the GitHub UI/API if that matters.

## Conventions established so far (follow these, don't re-derive them)

- **Rationale flow**: `strata.cli.main._get_rationale()` implements
  `docs/spec/04-git-integration.md` §2.3 (the `--why`/`--why-file` global
  options, the stop-list/length checks in `strata.core.commit`, exit code 7
  on refusal). Reuse it for every command that commits — don't build a
  second rationale path for import/dedup.
- **Structured commits**: build the message with
  `strata.core.commit.StructuredCommit`; `Strata-Op` values in this codebase
  are not restricted to the literal list in `docs/spec/04-git-integration.md`
  §2.2 — e.g. `actor-add` and `search-add` already exist as precedent for
  domain-appropriate op names beyond that illustrative list.
- **Schema validation**: every persisted file type gets a JSON Schema under
  `src/strata/schemas/<name>.schema.json`, validated via
  `strata.core.validate.validate(name, instance)` both on write (in the
  `core`/`protocol`/`ingest` module that writes it) and in
  `strata.core.verify._verify_*` (so `strata verify` catches hand-edited
  corruption).
- **Canonical serialisation**: always go through `strata.core.canon`
  (`dump_yaml_str`/`canonical_json`/`serialise_envelope`) — never call
  `json.dumps`/`yaml.dump` directly on data destined for a committed file.
  Use `ruamel.yaml.scalarstring.LiteralScalarString` for any field the spec
  says must round-trip byte-for-byte verbatim (e.g. a search `query`).
- **CLI is a thin adapter**: per `docs/spec/12-architecture.md` §2 invariant
  3, domain logic lives in `strata.core`/`strata.protocol`/`strata.ingest`/
  `strata.dedup`, not in `strata.cli.main`. The CLI command parses args,
  calls one function, formats the result.
- **Coverage/lint bar**: keep `uv run ruff check .`, `uv run ruff format
  --check .`, `uv run mypy src`, and `uv run pytest -q --cov=strata
  --cov-report=term-missing` clean before committing. Global floor is 90%
  line coverage; new code should land close to 100% covered since diff-cover
  enforces 95%-of-changed-lines in CI. `uv run python
  scripts/determinism_check.py` and `uv run python scripts/check_docs.py`
  are cheap to run locally and both must stay green.
- **Global option ordering**: `typer` requires global options (`--why`,
  `--json`, `-C`, `--no-commit`, ...) *before* the subcommand name, e.g.
  `strata --why "..." -C repo search add ...`, not after.
- Do **not** add `Strata-` trailers to commits in *this* repository (strata's
  own source tree) — those trailers are reserved for commits inside a
  *review* repository that the built tool generates. M0's and M1.1's source
  commits mostly get this right; one commit in the M1.1 sitting mistakenly
  added `Strata-Op`/`Strata-Schema-Version` trailers to a source commit. It's
  harmless (nothing parses source-repo commit trailers), but don't repeat it.

## Sub-objectives

| # | Sub-objective | Status |
|---|---|---|
| 1 | Search recording (`strata search add`/`list`) | **done** |
| 2 | Parsers: CSL-JSON, RIS, BibTeX | **done** |
| 3 | Parsers: PubMed/MEDLINE, EndNote XML, CSV/TSV, Excel, PRISMA-text; CSV mapping profiles; golden fixture corpus | not started |
| 4 | `strata import` pipeline | not started |
| 5 | Dedup engine: blocking + scoring + P8 | not started |
| 6 | Dedup CLI, review queue, merge semantics, labelled benchmark | not started |
| 7 | `strata records`/`why`/`fix` + filter expression language | not started |
| 8 | Fuzz corpus + requirement-traceability report + M1 acceptance polish | not started |

### 1. Search recording — done

Commit: `M1: record executed searches (strata search add/list)` on
`claude/inspiring-lovelace-ua9vkx`.

Delivered: `src/strata/schemas/search.schema.json`,
`src/strata/protocol/searches.py` (`add_search`/`list_searches`/`get_search`/
`next_search_id`/`pending_search_ids`), `strata search add`/`strata search
list` CLI commands, `strata status` surfacing searches with no query string
recorded (PRISMA item 7), `strata verify` validating every
`protocol/searches/*.yaml` against the schema, and the `--why`/`--why-file`/
`--no-commit` global options + `_get_rationale()` helper (see Conventions
above) that later sub-objectives should reuse rather than reinvent.

### 2. Parsers: CSL-JSON, RIS, BibTeX — done

Delivered: `src/strata/ingest/parsers/__init__.py` (shared `ParseResult`/
`RejectedRow`, `decode_bytes` — the BOM/UTF-8/CP1252/Latin-1 fallback chain
from §2.1 — and `normalise_newlines`); `csl_json.py`, `ris.py`, `bibtex.py`,
each exposing `parse(text: str) -> ParseResult` (text already decoded and
newline-normalised by the caller). Golden fixtures under
`tests/fixtures/exports/{csl-json,ris,bibtex}/` with `*.expected.json`
snapshots, provenance and a malformation-coverage table in
`tests/fixtures/SOURCES.md`; unit tests in `tests/unit/test_parsers_*.py` and
`tests/unit/test_ingest_parsers_common.py`; golden tests in
`tests/golden/test_golden_parsers.py`. All three parser modules are at 100%
line+branch coverage.

Notable implementation decisions future sub-objectives should know about:
- `rispy` (installed: 0.9.x per `pyproject.toml`, resolved 0.10.0) is strict
  about `TY  - ` two-space tag spacing and **silently drops** a record with
  no `ER` line instead of raising — both would violate §2.1's "never lose a
  record silently" rule. `ris.py` therefore isolates each `TY...ER` block
  itself (`_split_records`), synthesises a missing `ER` line, and canonicalises
  tag-line spacing before handing one block at a time to `rispy.loads`.
- `bibtexparser` resolved to **2.0.1**, not the 1.x line the sub-objective
  description assumed — its API is unrelated to 1.x (`parse_string`,
  `Library.entries`/`.failed_blocks`, a `SplitNameParts`/`SeparateCoAuthors`
  middleware pipeline for author names, not a dict-of-strings model). Malformed
  entries land in `library.failed_blocks` with their own line/error, giving
  per-entry isolation for free from the library.
- An empty/missing title is treated as a **rejected row**, not a raised error
  and not a silently-accepted record — reconciles §2.1's "never abort the
  import" with §03-schemas.md §2's "empty title is a hard import error": the
  record just doesn't make it in, same as any other unparseable row.
- HTML-entity decoding (§2.1) is applied to title/abstract/container-title in
  `ris.py` and to every string field in `bibtex.py`'s `_clean` helper; BibTeX's
  own protective mid-value braces (`{DNA}`) are stripped the same way LaTeX
  users rely on them being invisible in rendered output.
- **Known gap, not addressed this sitting**: legacy LaTeX-escaped diacritics in
  BibTeX (`M\"uller` rather than a literal `Müller`) are not decoded — no
  `LatexDecodingMiddleware` is wired in. Low priority (modern BibTeX exports
  are UTF-8), but worth a fixture + fix whenever sub-objective 3 or 8 next
  touches this file.
- Two lines in `ris.py` (`rispy.loads` raising, and returning a record count
  other than 1) and one in `bibtex.py` (a non-list `author` field value after
  `SeparateCoAuthors`) are marked `# pragma: no cover` with inline
  justification rather than forced with contrived inputs — they're defensive
  boundaries against library-internal edge cases, not reachable through
  `_split_records`'s/`SeparateCoAuthors`'s own invariants. The nightly fuzz
  corpus (sub-objective 8) is the intended real exercise for these paths;
  revisit the pragmas if fuzzing ever hits them.

### 3. Parsers: PubMed/MEDLINE, EndNote XML, CSV/TSV, Excel, PRISMA-text; CSV mapping profiles

Spec: `docs/spec/05-workflow-import.md` §2.1 (tolerances: BOM, CRLF/CR,
non-UTF-8 encodings tried in the specified order, HTML entities, missing
`ER  -`), §2.2 (CSV column mapping and detection profiles).

Scope:
- Hand-rolled `.nbib`/MEDLINE and EndNote XML parsers (no good library
  exists for either); `openpyxl` or similar for `.xlsx` (check
  `pyproject.toml` — may need adding as a dependency); CSV/TSV via the
  stdlib `csv` module plus the encoding-detection fallback chain (UTF-8 →
  UTF-8-with-BOM → CP1252 → Latin-1, recording which was used).
- Detection profiles for EBSCOhost, Scopus, Web of Science, ProQuest,
  Dimensions, Google Scholar (Publish or Perish) under
  `src/strata/ingest/profiles/`, matched by header signature, plus the
  interactive-mapping/`--map` fallback for an unrecognised header row.
- PRISMA-style plain-text citation lists: best-effort parse, always routed to
  manual review per spec — this one can be a thin stub that flags every
  record for review rather than a real citation parser.
- Extend the golden fixture corpus from #2 to cover every platform/format
  combination in `docs/spec/14-testing.md` §3, including all the named
  malformations (BOM, CRLF, missing `ER  -`, CP1252 smart quotes, HTML
  entities in titles, multi-line abstracts with inconsistent indentation,
  diacritics in author names, corporate authors, missing years, DOIs with
  trailing punctuation, empty title).

### 4. `strata import` pipeline

Spec: `docs/spec/05-workflow-import.md` §2.3 (what import does, idempotency
by file digest), §2.4 (`--via` tagging); `docs/spec/02-repository-format.md`
event types `import`/`record-add`.

Scope:
- `src/strata/ingest/__init__.py` (or a new `pipeline.py`): copy the file
  unmodified to `imports/<id>/raw/`, sha256 it, dispatch to the right parser
  from #2/#3 (by extension/`--format`), normalise via `strata.core.ids`,
  assign record ids, emit `import` + `record-add` events, write
  `imports/<id>/manifest.yaml`, write/merge into `records/records.ndjson`
  (sorted by id per `docs/spec/02-repository-format.md` §5.2).
- Idempotency: re-importing the same file (by digest) must create no new
  records/events and say so rather than silently succeeding.
- An exact-id match on a fresh import appends to `strata.sources` rather
  than duplicating (§2.3 point 4).
- `strata import <file>... --search <id> [--via ...] [--map ...] [--dry-run]`
  CLI command, committing via the established rationale flow.
- This is also where `derived/pool.tsv` regeneration first becomes
  meaningful — check whether `strata verify`'s derived-drift check
  (`E_DERIVED_DRIFT`, not yet implemented as of M1.1) needs to land here or
  can wait for #6.

### 5. Dedup engine: blocking + scoring + P8

Spec: `docs/spec/05-workflow-import.md` §3.1–§3.3 (blocking keys including
the MinHash/LSH title band, scoring formula, the DOI veto).

Scope:
- `src/strata/dedup/blocking.py`, `src/strata/dedup/scoring.py` (pure
  functions, no I/O — keep them as fold.py-style pure modules so they're
  easy to property-test).
- All six block keys from §3.2, with the 2,000-member cap and split-by-year
  warning.
- The scoring formula from §3.3 exactly, including the DOI-veto and
  `doi-conflict` labelling for pairs that veto on DOI but score high on
  everything else.
- `tests/property/test_dedup_properties.py` — P8 (`score(a, b) ==
  score(b, a)`), generated via `hypothesis`.

### 6. Dedup CLI, review queue, merge semantics, labelled benchmark

Spec: `docs/spec/05-workflow-import.md` §3.4–§3.8.

Scope:
- Thresholds/actions (auto-merge ≥0.95, review ≥0.80, distinct below,
  `--strict` forcing both to 1.0), reading from `strata.toml [dedup]`.
- Merge semantics: canonical selection (completeness → `source_trust` →
  lowest id), field-wise merge with `strata.field_provenance`, absorbed
  record retained with `strata.canonical: false` plus an `aliases.ndjson`
  entry — nothing deleted.
- `dedup-merge`/`dedup-distinct`/`dedup-unmerge` events; stickiness (never
  re-raise a judged pair); `--undo`.
- `strata dedup [--review] [--strict]` interactive queue per §3.6 (keyboard:
  `[m]`/`[k]`/`[s]`/`[o]`/`[?]`), plus a non-interactive/scriptable form.
- A labelled dedup benchmark (ASySD or `revtools` published sets, or a
  synthesised equivalent if licensing is unclear) under
  `tests/fixtures/dedup-benchmark/`, with recall/false-merge-rate assertions
  matching the M1 acceptance bar (recall ≥ 0.95, false-merge rate ≤ 0.001).
  Publish the metrics in the repo per §3.8, not just assert them in a test.
- Performance: 50,000-record dedup under 300s, <2GB RSS — likely belongs in
  `tests/benchmark/` (advisory CI tier, per `ci.yml`'s existing
  `benchmark` job pattern) rather than the blocking gate.

### 7. `strata records`/`why`/`fix` + filter expression language

Spec: `docs/spec/10-cli.md` §2 (Literature commands), §3 (filter expression
grammar — shared by CLI, web UI, and analysis specs; must not use
`eval`/`exec`).

Scope:
- A small hand-written recursive-descent parser + AST interpreter for the
  grammar in §3, with a regex timeout/linear-time guard for `matches`.
- `strata records list [--filter EXPR] [--format tsv|json|csl]`, `strata
  records show <id>` (full record + sources + provenance).
- `strata why <id>` — walk the event log for a record's full provenance
  chain (search → import → dedup); this is also part of the M1 acceptance
  bar ("`strata why` shows the full import and dedup provenance chain").
- `strata fix <id> --field <f> --value <v>` — emits `record-amend`.

### 8. Fuzz corpus + requirement-traceability report + M1 acceptance polish

Spec: `docs/spec/14-testing.md` §1 (fuzz, nightly), §10.5 (traceability).

Scope:
- A fuzz corpus seeded from `tests/fixtures/exports/` (from #2/#3), mutating
  bytes/encoding/structure and asserting parsers never crash uncontrolled
  (they may reject a row, per §2.1, but must not raise past that boundary).
  Wire into `nightly.yml` per the existing pattern for other nightly jobs.
- The M0 traceability gap: a `conftest.py`/small script that collects every
  `@pytest.mark.req(...)` marker across the suite and reports which
  identified requirements (P1–P13, E2E-01–E2E-12, `E_*` codes) have no test,
  as a CI step publishing the report as a build artefact (per §10.5). Retrofit
  the marker onto the property tests that already exist but don't carry it
  (P1/P2/P4/P5/P6/P9/P13 in `tests/property/`), and add real `hypothesis`
  property tests for P3 and P7 to close the M0 gap noted above.
- Run the full M1 acceptance checklist from `docs/spec/15-roadmap.md`
  end-to-end (golden fixtures, dedup benchmark numbers, 50k import/dedup
  timing, `strata why` provenance, dedup re-run raising nothing already
  judged) and fix whatever it surfaces.
- Update `README.md`'s Status section once the above is genuinely green.
