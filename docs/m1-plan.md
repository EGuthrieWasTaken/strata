# M1 ("Literature in") — sub-objective plan

> **Historical record.** This plan cites the long-form specification that
> lived under `docs/spec/` when it was written (for example
> `docs/spec/05-workflow-import.md §3.7`). That directory has since been
> retired in favour of [OpenSpec](../openspec/README.md); the cited text is
> preserved at
> [commit 69eec94](https://github.com/EGuthrieWasTaken/strata/tree/69eec94dae31794925b6bf25dce7c9659f57a310/docs/spec).

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
| 3 | Parsers: PubMed/MEDLINE, EndNote XML, CSV/TSV, Excel, PRISMA-text; CSV mapping profiles; golden fixture corpus | **partial** (MEDLINE, CSV/TSV + 6 detection profiles done; EndNote XML/Excel/PRISMA-text remain) |
| 4 | `strata import` pipeline | **done** |
| 5 | Dedup engine: blocking + scoring + P8 | **done** |
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

### 3. Parsers: PubMed/MEDLINE, EndNote XML, CSV/TSV, Excel, PRISMA-text; CSV mapping profiles — partial

Spec: `docs/spec/05-workflow-import.md` §2.1 (tolerances: BOM, CRLF/CR,
non-UTF-8 encodings tried in the specified order, HTML entities, missing
`ER  -`), §2.2 (CSV column mapping and detection profiles).

**Delivered**: the hand-rolled PubMed/MEDLINE (`.nbib`) parser,
`src/strata/ingest/parsers/medline.py` — `PMID- `/`TI  - `-style four-char
tags, six-space continuation lines, `FAU` preferred over `AU` for author
names with a distinct `CN` tag for corporate/collective authors, DOI pulled
out of `LID`/`AID`'s `[doi]`-suffixed values, MeSH headings (`MH`) folded
into `keyword`. `.txt` files are dispatched to this parser or to RIS by
sniffing the first non-blank line's tag (`strata.ingest.pipeline.
detect_format`), since the format table maps `.txt` to RIS, MEDLINE, *and*
PRISMA-text ambiguously.

Also delivered: the CSV/TSV parser (`src/strata/ingest/parsers/csv_tsv.py`)
and the detection-profile registry (`src/strata/ingest/profiles/`, six
profiles: Scopus, Web of Science, EBSCOhost, ProQuest, Dimensions, Google
Scholar via Publish or Perish). Unlike the other parsers, `csv_tsv.parse`
takes an explicit `mapping` (target field -> source column) rather than
resolving one itself — `strata.ingest.pipeline._resolve_csv_mapping` does
that, from an explicit `--map` (strict: a named column absent from the
header is an error) or by matching the header row against a profile
(lenient: only the columns *this* export actually has are used, since a
profile lists every column a platform *might* emit, not what one particular
export was configured to include — a real early bug this sitting hit and
fixed). `strata import`'s `--map field=Column,field2=Column2` CLI option is
wired up (`strata.cli.main._parse_map_option`). Every new module is at 100%
line+branch coverage (`tests/unit/test_parsers_csv_tsv.py`,
`tests/unit/test_profiles.py`, golden fixtures in
`tests/fixtures/exports/csv/`).

**Known limitation, disclosed in code**: the six CSV profiles' column names
are compiled from public export documentation and community references, not
verified against a live export from every platform — see the caveat in
`strata/ingest/profiles/__init__.py`'s docstring and in
`tests/fixtures/SOURCES.md`. Scopus and Web of Science are the two most
likely to be exactly right (their export formats are the most stable and
widely documented); EBSCOhost/ProQuest/Dimensions/Google-Scholar-PoP have no
golden fixture and haven't been checked against a real file. Worst case a
wrong signature just fails to match (falls through to the `--map` error
message, which is always correct regardless of profile accuracy) rather than
silently mismapping a column — but if a real export from any of these six
platforms turns up, diff its header against the profile in
`strata/ingest/profiles/__init__.py` and fix whichever is wrong, per the
project's own `parser.yml` issue-template philosophy.

**Not yet started**: EndNote XML, Excel (`.xlsx`), and PRISMA-style
plain-text citation lists. A `.xml`/`.xlsx` file currently hits
`detect_format`'s "unsupported file extension" branch, not a wrong-parser
bug. Extend `tests/fixtures/SOURCES.md`'s malformation-coverage table as each
format lands.

### 4. `strata import` pipeline — done

Spec: `docs/spec/05-workflow-import.md` §2.3 (what import does, idempotency
by file digest), §2.4 (`--via` tagging); `docs/spec/02-repository-format.md`
event types `import`/`record-add`.

Delivered: `src/strata/ingest/pipeline.py` (`import_file`, `detect_format`,
`list_import_manifests`/`find_import_by_digest`), `src/strata/core/records.py`
(read/write/index `records/records.ndjson`, validated + sorted-by-id per
§5.2), two new schemas (`record.schema.json`, `import-manifest.schema.json`),
`strata verify`'s new `_verify_records` check, and the `strata import
<file>... --by <actor> (--search <id> | --via <tag>) [--format <fmt>]
[--map ...] [--dry-run]` CLI command. `tests/unit/test_pipeline.py` (28
cases, 100% line+branch) and `tests/integration/test_cli_import.py` (12
cases) cover it, including a full round trip re-verified with `strata
verify`.

What it does, per file: copies the raw bytes unmodified to
`imports/<id>/raw/`; decodes/newline-normalises and dispatches to the right
parser from #2/#3 by extension, or by content-sniffing for `.txt`; normalises
`DOI`/`PMID`/`PMCID`/`ISBN` for storage via the `strata.core.ids` functions
(a value that fails to normalise is left as parsed, never dropped); assigns
each record's id via `assign_record_id`; on an id already present in
`records/records.ndjson` (whether from an earlier import *or* a second row
in the same file), appends a `sources` entry instead of duplicating the
record; emits one `record-add` event per genuinely new record plus one
`import` event, all under `events/import/<actor>.ndjson` (added to `strata
init`'s directory scaffold alongside the other event domains); writes
`imports/<id>/manifest.yaml` and, if any rows failed to parse,
`imports/<id>/rejected.txt`. Idempotent by file digest: a second import of
byte-identical content changes nothing and reports `already_imported` rather
than silently repeating. Each file in a multi-file invocation is its own
`imports/<id>/` and its own commit, so a failure partway through a batch
leaves every earlier file's import already committed instead of the tree
half-written and dirty.

**Decisions/simplifications worth knowing about**:
- `record-add`'s `raw_row_digest` is `sha256` of the canonical JSON of the
  record *as the parser returned it* (before identifier normalisation/id
  assignment), not a digest of the original file bytes for that row — no
  parser currently threads per-record source-text spans back out, and this
  is a legitimate, cheap, deterministic stand-in for "did this row's content
  change between imports" that `strata why` (sub-objective 7) can build on.
- No event is emitted for the "append to an existing record's `sources`"
  case (only for genuinely new records) — the spec's `record-add` body shape
  (`record`, `import_id`, `raw_row_digest`) reads as one-event-per-created-
  record, and the append is itself visible in `records.ndjson`'s committed
  diff. Revisit if provenance review in sub-objective 7 turns out to need a
  dedicated event for it.
- A search's `protocol/searches/<id>.yaml` `export_files` list is **not**
  auto-updated by import (that would need a new "update a search" function
  in `strata.protocol.searches`, which didn't exist and felt like scope
  creep for this sitting). A reviewer wanting that link records it via
  `strata search add --export-file` at search-recording time, or a future
  session could wire it up.
- `derived/pool.tsv` regeneration is **deliberately not touched here** — the
  original scope note for this sub-objective flagged it as a "check whether
  this needs to land here or can wait for #6" question; since `tiab`/
  `fulltext` columns need screening state (M2) and "one row per canonical
  record" needs dedup (#5/#6) to mean anything, generating it now would mean
  reworking it twice. `E_DERIVED_DRIFT` in `strata verify` is therefore still
  unimplemented, same as at the end of sub-objective 1.
- `strata.core.ids` gained `normalise_pmid`/`normalise_pmcid`/`normalise_isbn`
  as standalone functions (previously inlined in `canonical_key`), reused by
  both the pipeline's storage-normalisation step and `canonical_key` itself.
  `ids.py` is one of the five 100%-branch-coverage modules; the refactor
  stayed at 100% (`tests/unit/test_ids.py`).

**Update from sub-objective 3's CSV work**: `--map`/CSV column mapping
*is* now on the CLI (`strata import ... --map title=Column,author=Column`),
landed alongside `csv_tsv.py`/`profiles/` since the two were natural to build
together — see sub-objective 3's write-up above for what it does.

### 5. Dedup engine: blocking + scoring + P8 — done

Spec: `docs/spec/05-workflow-import.md` §3.1–§3.3 (blocking keys including
the MinHash/LSH title band, scoring formula, the DOI veto).

Delivered: `src/strata/dedup/blocking.py` and `src/strata/dedup/scoring.py`,
both pure functions (no I/O), 100% line+branch coverage
(`tests/unit/test_blocking.py`, `tests/unit/test_scoring.py`), plus
`tests/property/test_dedup_properties.py` (P8, `@pytest.mark.req("P8")`,
`hypothesis`-generated records).

`blocking.compute_block_keys` implements all six §3.2 block keys: `doi`,
`pmid`, `title-prefix` (first 12 normalised chars + year), `author-year-vol`,
`first-page`, and `title-lsh` (a genuine 128-permutation MinHash over
character 3-grams, banded 32×4 per the spec's own tuning). `find_candidate_pairs`
groups a `{id: record}` map into blocks, unions same-block pairs, and applies
the 2,000-member cap + split-by-year + warning §3.2 requires.

`scoring.score_pair` implements the §3.3 formula exactly (title/author/year/
journal/locator sub-scores at their specified weights, the hard DOI veto),
plus `PairScore.non_doi_score` so a *caller* (sub-objective 6) can apply the
`doi-conflict` rule ("route DOI-mismatched pairs scoring high on everything
else into review, don't discard them") against its own `review_threshold` —
that threshold and the resulting action belong to §3.4, out of this
sub-objective's pure-function scope.

**Decisions worth knowing about**:
- Every similarity function returns **0.0**, never 1.0, when the relevant
  field is missing on **both** sides (e.g. neither record has a journal). The
  spec doesn't address this case explicitly; the choice favours the
  false-merge-rate priority §3.8 states outright ("a false merge destroys
  data... weighted most heavily") over crediting missing data as agreement.
  Applied uniformly across `title_sim`/`author_sim`/`year_sim`/
  `journal_sim`/`locator_sim`.
- MinHash's universal-hash coefficients come from `random.Random(FIXED_SEED)`
  at module load — a fixed seed, not a random one, and unrelated to Python's
  per-process-randomised `hash()`/`PYTHONHASHSEED` (verified: the same
  signature comes out under `PYTHONHASHSEED=1` and `PYTHONHASHSEED=42`).
  Per-shingle hashing uses `zlib.crc32`, also `PYTHONHASHSEED`-independent.
  This matters because two collaborators must compute the *same* blocks from
  the same records regardless of platform or process, or dedup silently
  becomes non-reproducible between machines.
- `locator_sim`'s and `author-year-vol`'s volume comparison reuses
  `core.ids.normalise_pages` (documented in-code as intentional: "first
  integer run of a value" is exactly the transformation a volume number
  needs too, despite the function's page-oriented name).
- Levenshtein distance is a plain O(n·m) pure-Python DP (no
  `rapidfuzz`/`python-Levenshtein` dependency added) — fine at title/journal
  string lengths; revisit only if the sub-objective 6/8 benchmark work finds
  it's a bottleneck at 50k-record scale.
- Not built here (explicitly sub-objective 6's scope, per the split in this
  file): thresholds/actions, `doi-conflict` labelling's actual call site, the
  review queue, merge semantics, `dedup-merge`/`dedup-distinct`/
  `dedup-unmerge` events, the labelled benchmark, and performance validation
  at 50k records.

### 6. Dedup CLI, review queue, merge semantics, labelled benchmark — done

Spec: `docs/spec/05-workflow-import.md` §3.4–§3.8.

Delivered: `src/strata/dedup/merge.py` (pure field-wise merge/canonical
selection, 100% coverage, `tests/unit/test_merge.py`), `src/strata/dedup/
engine.py` (repo orchestration: thresholds, blocking → scoring → auto-merge/
review-queue routing, event/alias side effects, undo; 100% coverage,
`tests/unit/test_engine.py`), and `strata dedup` in `src/strata/cli/main.py`
(`--by`, `--review`, `--strict`, `--undo CANONICAL ABSORBED`, `--json`,
`--no-commit`; `tests/integration/test_cli_dedup.py`).

- **Thresholds/actions** (§3.4): `engine.thresholds()` reads
  `[dedup].auto_merge_threshold`/`review_threshold` from `strata.toml`
  (defaults 0.95/0.80). `--strict` is **not** literally "both thresholds set
  to 1.0" as the spec text puts it — see the decision note below.
- **Merge semantics** (§3.5): `merge.choose_canonical` picks the surviving
  record by completeness (populated high-value fields) → `source_trust`
  config order → lowest record id; `merge.merge_fields` merges field-by-field
  (keyword union, longest-abstract-wins, everything else canonical-wins) and
  records `strata.field_provenance`. The absorbed record is kept with
  `strata.canonical: false` and an `aliases.ndjson` entry — nothing is ever
  deleted, matching M0's append-only invariant.
- **Events + stickiness** (§3.1, §3.6): `dedup-merge`/`dedup-distinct`/
  `dedup-unmerge` events; `engine.judged_pairs` folds them into a set no
  future run re-raises (an undone merge counts as judged too — reversing a
  wrong auto-merge shouldn't make the very next run immediately re-propose
  it; a user wanting it reconsidered records a fresh decision explicitly).
- **Review queue** (§3.6): `strata dedup --review` renders one pair per
  screen with the score breakdown and `[m]erge`/`[k]eep both`/`[s]kip`/
  `[o]pen both`/`[?]help`; `strata dedup` with no `--review` is the
  non-interactive form (auto-merge only, queue left for later).
- **Labelled benchmark** (§3.8): `tests/fixtures/dedup-benchmark/` (55
  records: 21 ground-truth duplicate pairs across cross-database formatting
  variations, 4 deliberately adversarial "confusable" hard negatives, 8
  unrelated singletons — see that directory's `README.md`),
  `src/strata/dedup/benchmark.py` (pure metric computation, 100% coverage,
  `tests/unit/test_benchmark.py`), `scripts/dedup_benchmark.py` (runs the
  fixture through `run_dedup` and writes
  [`docs/dedup-benchmark-results.md`](../dedup-benchmark-results.md)), and
  `tests/integration/test_dedup_benchmark.py` (the CI-enforced assertion,
  calling the exact same `run_benchmark()` the script uses so the two can't
  drift apart). Current result: **recall 1.000, false-merge rate 0.0000**
  against the v1 targets of ≥ 0.95 / ≤ 0.001.
- **Performance** (§3.7): `tests/benchmark/test_dedup_performance.py`, a real
  50,000-record run (5,000 near-duplicate pairs + 40,000 singletons,
  deterministically generated with random letter-sequence titles — see that
  file's module docstring for why real/templated vocabulary caused a
  self-inflicted LSH-blocking blowup during development), advisory CI tier
  only (`.github/workflows/ci.yml`'s existing `benchmark` job,
  `continue-on-error: true`) — excluded from `pyproject.toml`'s pytest
  `testpaths` so a bare `pytest`/`pytest -q` (the blocking `test`/`coverage`
  jobs) never collects it.

  **Update (sub-objective 8): measured at 126.0s** — just over §3.7's strict
  120s, comfortably inside the M1 acceptance bar's looser 300s
  (docs/spec/15-roadmap.md). At the time this note was first written, the
  measurement was ">240s, and climbing" (i.e. this same test, killed before
  it finished) — that was overwhelmingly an O(n^2) event/alias-append bug in
  `strata.core.events.append_new_event`/`aliases.append_alias` (both re-read
  their whole file on every call, turning ~5,000 merges' worth of appends
  into ~12.5 million file reads), not a blocking/scoring problem; sub-
  objective 8 found and fixed it (see that section below). What remains,
  dominating the 126s: blocking alone (`find_candidate_pairs`, per-record
  MinHash: 128 permutations × ~60 title 3-grams × 50,000 records) takes
  ~77s. Memory stayed well under the 2GB budget throughout. Left as a known
  gap rather than fixed here, since closing the remaining ~6s over budget
  would mean touching sub-objective 5's already-tested, locked-in
  `blocking.py`/`scoring.py` — out of scope for a different sub-objective,
  and exactly why the check lives in the advisory tier and not the blocking
  gate. Follow-up ideas for whoever picks this up: vectorise MinHash with
  `numpy` instead of a pure-Python permutation loop; short-circuit
  `title_sim`'s Levenshtein call when the cheap Jaccard score alone already
  clears the threshold; investigate whether `rapidfuzz` (C-accelerated
  Levenshtein) is worth the new dependency the sub-objective 5 write-up
  deliberately avoided.

**Decisions worth knowing about**:
- **`--strict` is implemented as `(auto_merge_threshold=1.0,
  review_threshold=0.0)`, not the spec text's literal "both thresholds to
  1.0."** §3.4 says `--strict` "sets both thresholds to 1.0, so every
  non-exact pair is reviewed" — but a review band is `[review_threshold,
  auto_merge_threshold)`, and `[1.0, 1.0)` is empty. Taken literally, every
  non-exact pair would fall to *distinct* (silently discarded) instead of
  being reviewed — the opposite of the stated intent. `engine.thresholds()`
  implements the intent (only an exact/DOI match auto-merges; everything
  else blocking proposes is queued for review) rather than the literal
  numbers; see that function's docstring. Caught by a CLI-level test
  (`test_dedup_strict_routes_near_duplicate_to_review_not_auto_merge`) that
  a purely unit-level test of `thresholds()` alone would have missed, since
  `(1.0, 1.0)` "looks right" in isolation.
- No real ASySD/`revtools` dataset is used for the labelled benchmark: this
  environment has no live internet access to fetch either or verify its
  licence before redistributing a derived copy here. The synthesised
  fixture follows the same hand-authored, metadata-may-match-a-real-paper
  provenance convention as `tests/fixtures/exports/`
  (`tests/fixtures/SOURCES.md`), documented in full in
  `tests/fixtures/dedup-benchmark/README.md`.
- `doi-conflict` labelling (§3.3's carve-out: a DOI-vetoed pair scoring high
  on everything else is queued for review, not silently discarded) lives in
  `engine._is_doi_conflict`, using `PairScore.non_doi_score` against
  `review_threshold` exactly as sub-objective 5's write-up anticipated.
- `apply_review_decision`'s `"distinct"` branch and `undo_merge` are the only
  two entry points that don't route through `run_dedup`'s per-run
  `by_id`/`absorbed_records` bookkeeping — both re-read `records.ndjson`
  fresh, since a review decision or an undo can happen well after (and
  independently of) the auto-merge pass that produced the queue.
- Commit-message subject lines for dedup operations stay under the 72-char
  `StructuredCommit` limit by moving the second record id into a trailer
  (`_commit_dedup_op`'s `extra_trailers` param) rather than the summary text
  — the same class of bug the `strata import` commit subject hit earlier;
  worth checking for on any future command whose summary embeds a full
  `rec_`/`imp_`/`ev_` id.

### 7. `strata records`/`why`/`fix` + filter expression language — done

Spec: `docs/spec/10-cli.md` §2 (Literature commands), §3 (filter expression
grammar — shared by CLI, web UI, and analysis specs; must not use
`eval`/`exec`).

Delivered: `src/strata/core/filters.py` (the grammar: hand-written
recursive-descent parser + AST + interpreter, 100% coverage,
`tests/unit/test_filters.py`), `src/strata/core/records.py`'s new
`record_field_resolver`/`resolve_id_prefix`/`amend_field`/
`EDITABLE_STRING_FIELDS` (100% coverage, additions to
`tests/unit/test_records.py`), `src/strata/core/provenance.py` (`strata
why`'s event-log walk, 100% coverage, `tests/unit/test_provenance.py`), and
`strata records list|show`, `strata why`, `strata fix` in
`src/strata/cli/main.py` (`tests/integration/test_cli_records.py`).

- **Grammar** (§3): every rule in the spec's grammar block — `or_expr`/
  `and_expr`/`not_expr`/`primary`/`comparison`, all nine operators including
  the two-word `not in`, string/number/boolean/null/list literals with
  string-escape handling. No `eval`/`exec` anywhere; `filters.py` is
  domain-agnostic (it knows nothing about what fields exist) so the same
  module can serve the web UI and analysis specs later without a rewrite.
- **`--filter` fields** (§3's table): only the M1 subset with real data --
  `id`, `doi`, `pmid`, `title`, `abstract`, `journal`, `year`, `authors`,
  `via`, `search` (`record_field_resolver`). Every other field the table
  lists (`tiab`, `fulltext`, `stale`, `criteria`, `actor_decision.<handle>`,
  `rob_overall`, `rob.<domain>`, extraction/moderator fields,
  `derived_from_pvalue`, `assumed_correlation`) needs screening (M2),
  extraction (M3), or analysis (M4) data that doesn't exist yet; referencing
  one raises a clear "not available yet" error naming the milestone gap,
  rather than either crashing unhelpfully or silently matching nothing.
- **`strata records list`**: `--filter EXPR`, `--format tsv|json|csl`
  (default `tsv`), `--all` to include absorbed duplicates (excluded by
  default). `strata records show <id>` and `strata why`/`strata fix <id>`
  all accept an unambiguous id *prefix*, per §1's "as in git"
  (`records.resolve_id_prefix`), not just a full id.
- **`strata why <id>`**: walks every event file for `record-add`, `import`,
  `record-amend`, and `dedup-merge`/`dedup-distinct`/`dedup-unmerge` events
  touching the given record, resolves the `import` event's `search_id`
  against `protocol/searches/`, and renders the chain search → import →
  record-add → amendments/dedup (the latter two chronological, since a
  record can be corrected or merged/undone more than once). Satisfies the M1
  acceptance bar ("`strata why` shows the full import and dedup provenance
  chain") — verified in `test_why_includes_dedup_provenance`.
- **`strata fix <id> --field <f> --value <v> --by <actor>`**: emits
  `record-amend` (`record`, `field`, `old`, `new`, `source`) exactly per the
  event catalog (docs/spec/02-repository-format.md §4.4), `source` always
  `"manual"` to distinguish a human correction from `strata sync`'s
  automatic three-way-merge resolution (§4.3 of `04-git-integration.md`),
  which the spec says emits the same event type. Commits like every other
  mutating command (`_commit_domain_op`, generalised from dedup's
  `_commit_dedup_op` since the logic was never dedup-specific).

**Decisions worth knowing about**:
- **`matches`'s safety guard is a static nested-quantifier check, not a
  runtime timeout, and this was not the original plan.** §3 allows either "a
  linear-time regex engine or enforce a timeout." A background-thread-plus-
  `join(timeout)` approach was tried first and **empirically failed**: fed a
  genuinely catastrophic pattern (`(a+)+b` against a long run of `a`s), the
  main thread's `join(1.0)` never returned within a live test run (it was
  killed after minutes, still spinning). The reason is structural, not a bug
  in that attempt: CPython's `re` engine holds the GIL for the entire
  duration of one `search()` call, with no bytecode-level safe point for
  another thread to run at — so the "timing out" thread can't even reacquire
  the GIL to notice the timeout until the match finishes on its own, which
  for a catastrophic pattern is effectively never. `multiprocessing` is the
  only mechanism that can actually kill a runaway match, and spawning a
  process per `matches` evaluation is far too slow across e.g. `strata
  records list --filter` on a real repository. The shipped mitigation
  instead parses the pattern with `re._parser` (private but stable since
  3.11) and statically rejects an unbounded repeat nested inside another —
  `(a+)+`, `(a*)+`, `(a+)*`, and the alternation form `(a+|b)+` — the
  textbook ReDoS shape, before any regex ever runs. This is not exhaustive
  (some catastrophic patterns use a different shape, e.g. overlapping
  alternation without a literal nested repeat node) but needs no OS-specific
  mechanism and has no runtime cost. See `strata.core.filters._is_catastrophic`'s
  docstring for the full reasoning.
- `via`/`search` are typed `string` in §3's field table, but a merged
  record's `strata.sources` can hold several entries (one per absorbed
  duplicate) with different values. `record_field_resolver` resolves both to
  the record's *first* source (the one that originally established it) --
  "how was this first found" is the most natural single-value reading, but a
  query needing *any* source's via/search isn't expressible this way. A
  known, documented limitation rather than inventing multi-valued comparison
  semantics the spec doesn't describe.
- `strata fix` only edits `EDITABLE_STRING_FIELDS` — every record-schema
  field except `id`/`type` (identity, not metadata) and `author`/`issued`/
  `strata` (structured, not a flat string). Correcting an author's name or a
  publication year isn't expressible via `strata fix` yet; the CLI reference
  in §2 doesn't specify field-level constraints, so this is this
  implementation's own boundary, chosen because a single string value can't
  represent a structured field without inventing an ad hoc sub-syntax the
  spec doesn't define.
- `resolve_id_prefix`'s "as in git" abbreviation support (§1) was added for
  the three new record-id-consuming commands (`records show`, `why`, `fix`)
  but not retrofitted onto `dedup --undo`, which still requires full ids —
  out of scope for this sub-objective, noted for whoever touches that
  command next.

### 8. Fuzz corpus + requirement-traceability report + M1 acceptance polish — done

Spec: `docs/spec/14-testing.md` §1 (fuzz, nightly), §10.5 (traceability).

Delivered:

- **Fuzz corpus** (§6): `tests/fuzz/test_fuzz_parsers.py`, `hypothesis`-driven
  mutation (bit flip/insert/delete/truncate) seeded from every real fixture
  under `tests/fixtures/exports/`, one test per format
  (csl-json/ris/bibtex/medline/csv), asserting `parse()` always returns a
  `ParseResult` and never raises. Not `atheris` (§6 names either): it needs a
  native libFuzzer-linked CPython build, fragile across this project's
  three-OS CI matrix, and `hypothesis` is already a dependency. Lives in
  `tests/fuzz/`, excluded from `pyproject.toml`'s pytest `testpaths` (fuzzing
  is nightly-only per §1's levels table, not a per-commit gate) but already
  picked up by `nightly.yml`'s existing `fuzz` job, which only needed the
  directory to exist.
- **Requirement traceability** (§10.5): `scripts/traceability_report.py`
  collects every `@pytest.mark.req(...)` marker via a `pytest --collect-only`
  plugin and reports which of P1-P13/E2E-01-E2E-12/`E_*` (the exact set
  `docs/spec/03-schemas.md` §10's table names) have no test, writing
  `build/traceability-report.md` (a build artefact, not committed — unlike
  the dedup benchmark's result this changes with every test added and would
  go stale). Wired into `ci.yml` as a new advisory `traceability` job
  (`continue-on-error: true`, matching `benchmark`'s pattern), since not
  every requirement is coverable yet (§10.5: uncovered is a gate failure only
  "once every current requirement is covered"). Retrofitted `@pytest.mark.req`
  onto the property tests that already existed without it (P1/P2/P4/P5/P6/P9/
  P13) and onto four `strata verify` tests that already demonstrated
  `E_SCHEMA`/`E_DANGLING_REF`/`E_ALIAS_CYCLE`/`E_CHAIN` detection but weren't
  marked. Added real `hypothesis` property tests for **P3** (serialisation
  round-trip, `tests/property/test_canon_properties.py`, both generic JSON
  and a record-shaped document) and **P7** (alias acyclicity,
  `tests/property/test_alias_properties.py`, generating merge sequences
  shaped like `dedup.engine`'s real invariants so the generator can't produce
  a cycle by construction — matching what real merges do) to close the M0
  gap. Also added `tests/e2e/test_e2e_07_late_import_dedup_stickiness.py`
  (a manual "keep both" decision survives a later, unrelated import) and
  `tests/benchmark/test_import_performance.py` (E2E-11's 50k-import
  performance target), both fully buildable at M1 and previously untested.
  P10/P11/P12 (staleness/count-reconciliation/effect-size, all M2+M4) and
  most `E2E-*`/`E_*` ids needing screening, extraction, RoB, or analysis data
  correctly remain uncovered — reported, not hidden.
- **M1 acceptance checklist** (`docs/spec/15-roadmap.md`), run end to end,
  found two real bugs fixed along the way (below) plus confirmed: all golden
  parser fixtures pass; dedup benchmark recall 1.000/false-merge rate 0.0000;
  `strata why` shows the full chain; a dedup re-run never re-raises an
  already-judged pair (`test_e2e_07...` above, plus the existing sticky-pair
  tests). 50,000-record import now measures **20.1s** (well inside the
  roadmap's 60s bar) at 412MB peak RSS; 50,000-record dedup measures **126.0s**
  (comfortably inside the roadmap's 300s bar, just over §3.7's own stricter
  120s — see sub-objective 6's updated performance note above for why).

**Bugs found and fixed by this pass** (not just documented — these were
cheap, safe, and high-value once found):

- **`decode_bytes` crashed on a BOM followed by invalid UTF-8**, found within
  minutes by the new fuzz suite mutating a real BOM fixture (`ef bb bf` +
  a byte that isn't a valid UTF-8 continuation byte). The docstring already
  promised the encoding chain "always terminates" via a Latin-1 last resort,
  but the BOM branch decoded with a bare, unguarded `.decode("utf-8")`
  instead of falling through the same cp1252/latin-1 chain as the no-BOM
  path — a corrupted or truncated file with an intact BOM would crash the
  whole import instead of degrading gracefully. Fixed in
  `strata/ingest/parsers/__init__.py`; two new unit tests
  (`tests/unit/test_ingest_parsers_common.py`) pin the fixed behaviour so a
  regression fails fast, not just on the next nightly fuzz run.
- **`append_new_event` is O(n) per call, making any loop of n appends to the
  same file O(n^2)** — it recomputes `seq`/`prev` by re-reading and
  re-parsing the *entire* file on every single call
  (`next_seq`/`last_digest`, both via `read_events`). This is fine for a
  one-off append, which is most of its call sites, but two hot loops call it
  once per item: `strata import`'s one `record-add` event per row, and
  `dedup.engine.run_dedup`'s one `dedup-merge` event (plus one
  `aliases.append_alias` call, which has the identical read-whole-file-
  every-call shape) per auto-merge. A 1,500-row import was measured (via
  `cProfile`) spending 24 of 26 seconds inside `append_new_event` alone,
  2.25 million `json.loads` calls to append 1,500 lines — this, not parser
  or scoring cost, was the actual reason the 50k-import perf test (added by
  this same sub-objective) first measured over five minutes instead of the
  60s target, and very likely the dominant reason the sub-objective 6 dedup
  perf finding ("blocking alone ~77s, full run exceeded 240s") looked as bad
  as it did. Fixed with a new `strata.core.events.append_new_events`
  (plural): reads the file once, tracks `seq`/`prev` in memory across a
  batch of `(ev, actor, body)` entries, and still writes each event with its
  own `append_event` call (preserving the existing per-line
  `PIPE_BUF`-atomicity property `append_event`'s docstring already
  documents, rather than trading it for one large write). `strata.ingest.
  pipeline.import_file` now collects all its `record-add` entries and
  appends them in one batched call; `dedup.engine.run_dedup` does the
  analogous thing for `dedup-merge` events *and* for the alias entries
  (reading `aliases.ndjson` once, appending in memory, writing once via the
  existing `write_aliases`) after its per-pair loop, rather than during it.
  `apply_review_decision` (a single decision, never a loop) keeps calling
  the singular `append_new_event`/`append_alias` — batching only pays off
  where there's a batch. Confirmed by measurement: 50k import dropped from
  "still running after 5+ minutes" to **20.1s**; 50k dedup dropped from
  ">240s, and climbing" to **126.0s** (sub-objective 6's performance note
  above has the detail). `tests/unit/test_events.py` gained direct tests for
  `append_new_events`; all touched modules stayed at 100% line+branch
  coverage throughout.
