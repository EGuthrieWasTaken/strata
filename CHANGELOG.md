# Changelog

All notable changes to `strata` are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- **Searches and imports in the web interface** (OpenSpec change `add-web-ui-write-surfaces`). `/searches`
  lists the recorded searches with their dates, hits, whether their query is missing and what has been
  imported from each; `/searches/new` records one (the date defaults to today; blank query is recorded as
  missing and flagged; "re-run" makes a superseding search); a search takes its export files by file chooser
  or drag and drop and `/import` takes records found by other methods. Every upload goes through a review
  that runs the import pipeline's own dry run per file (new, matched, rejected rows with reasons, already
  imported, a sheet chooser for workbooks, a column mapping for CSVs) and imports only on confirmation, each
  file as its own commit through the same `strata.core.operations` the command line uses; a test holds the
  results byte-identical to `strata search add` and `strata import`. The dashboard now names searches
  missing their query and searches with no export imported yet, each linking to the search. A real-browser
  smoke test (`tests/browser`, optional) drives the whole flow.
- **Correcting a record, adding a criterion and assigning reviewers in the web interface** (OpenSpec change
  `add-web-ui-write-surfaces`). `/records/<id>` has a form that corrects a field with a rationale, `/criteria/new`
  adds a criterion (stating that it is recorded as tightened, and always asking for a rationale), and
  `/assign/<stage>` assigns reviewers, with a count of what a filter matches before anything is saved and the
  parser's message when it does not parse. `strata fix`, `strata criteria add` and `strata assign` now call the
  same operations in `strata.core.operations` (as `search add` and `import` already did), so a screen and its
  command record the same commit; tests hold the two to the same files, message and trailers, and the same
  stale decisions after a criterion is added. The command line is unchanged except as listed under Changed
  and Fixed.
- **Full-text retrieval and study grouping in the web interface** (OpenSpec change
  `add-web-ui-write-surfaces`). `/retrieve` lists the reports sought and `/retrieve/<report>` records an outcome
  (retrieved with a source and version, interlibrary loan requested, not retrievable with a reason, or put back
  in the queue) with a rationale; it has no file or path field. `/studies` shows the included reports as
  studies with the suggestions and their evidence and forms to group or split reports, each requiring a
  rationale; viewing it records nothing. `strata retrieve --report --outcome` and `strata studies --group` /
  `--split` call the same operations, held to identical commits by tests. Keeping a suggestion separate is
  still command line only.
- **Upload handling for the web interface** (`strata.web.uploads`; capability `web-uploads`, OpenSpec change
  `add-web-ui-write-surfaces`). `strata serve` refuses a form post larger than its declared limit before reading
  it (100 MB for a file upload, `--max-upload-mb N` to change; 1 MB for any other form), refuses one that
  declares no size, more than 20 files, and a text field over 1 MB, and does all of that only after the session,
  `Host` and `Origin` checks. Browser file names are never paths (`sanitise_filename`). Uploads wait in
  `.strata/tmp/uploads/<id>/` under an unguessable id until confirmed, and are deleted on confirm, discard,
  start-up and after an hour. Only bibliographic exports are accepted, by the detection `strata import` uses; a
  PDF is refused with the reason. A new review's `.gitignore` now ignores `/.strata/tmp/` and `/.strata/lock`;
  for existing reviews the staging area is excluded locally (`.git/info/exclude`), which needs no commit. No
  upload screen uses this yet (searches and imports in the browser come next in the same change).
- **The repository lock is the operating system's** (`strata.core.lockfile`; OpenSpec change
  `add-web-ui-write-surfaces`). It was a file whose existence meant "held", so a `strata` killed mid-write left
  it behind and every later write failed after 30 seconds until someone deleted `.strata/lock`; and nothing
  actually took it. It is now a `flock` (a byte-range lock on Windows), so a holder that dies, however it dies,
  holds nothing. A command that finds a lock its holder died holding takes it over and says so. `strata search
  add` and `strata import` now take it for the length of their write and commit, so a terminal and `strata
  serve` cannot interleave; a command that cannot get it in 30 seconds names the process that has it. The
  Windows branch is written but has only been exercised on Linux so far.

- **The wiki** (`wiki/`, 40 pages; the `project-documentation` spec). A home page with Installation,
  Quickstart (a whole single-reviewer review run on invented example data), Git for reviewers and a practical
  guide for every stage (setting up, searching and importing, duplicates, screening, adjudication and
  agreement, changing criteria mid-review, full texts, study grouping, extraction, risk of bias, analysis,
  reporting, working with others, the web interface), concept pages (staleness, criteria versions and
  direction, deduplication, blinding, the review folder, a glossary), configuration, the filter language,
  recovery and troubleshooting, known limitations, and the methods and statistics references. The command
  reference is generated from the program's help text (`scripts/build_wiki_reference.py`); `scripts/check_wiki.py`
  checks links, headings, the sidebar and that every `strata ...` example names a real command and option (it
  runs in the docs workflow and in the tests). `.github/workflows/wiki.yml` copies `wiki/` to the GitHub wiki
  when it changes on `main`.
- Fixed while writing it: `strata verify` reported every character of an absorbed record's id as an unknown
  record after any automatic merge (so `strata sync` and `strata clone` of a review with a merge failed); the
  help example for `strata studies` put `--why` after the command; and the web interface's header said
  "signed in as" with nothing after it on the criteria pages and "signed in as None" on the history page.

- **M6: more import formats** (task 2.4 of OpenSpec change `add-distribution-and-adoption`). `strata
  import` reads EndNote XML (`.xml`; unescaped `&` and HTML entities repaired, one bad record set aside
  rather than losing the file, DOCTYPE and entity declarations refused), Excel workbooks (`.xlsx`, first
  sheet or `--sheet NAME|N`, read with the standard library only, never evaluating a formula, with caps on
  file size, unpacked size, rows, columns and cell length) and plain-text citation lists (`.txt`;
  Vancouver and APA layouts, best effort: records are flagged `best-effort-parse` and deduplication leaves
  them for a person). Golden fixtures, unit, integration and fuzz tests; the fuzzing found four ways a
  corrupt workbook could escape as the wrong exception, all fixed. Not built: the Covidence, Rayyan and
  EPPI-Reviewer migration imports.
- **M5.1: container image** (OpenSpec change `add-container-image`, in flight). A multi-stage `Dockerfile`
  (locked dependencies, `git`, non-root uid 10001, `safe.directory = *` in the system git config, a
  `/healthz` health check), `.dockerignore`, an entrypoint that makes `serve` container-ready (all
  interfaces, a generated token, a localhost public URL, no browser), `compose.yaml`, CI `container` jobs
  on amd64 and arm64 with hadolint, a smoke test (`scripts/container_smoke.sh`) and a native-versus-image
  determinism comparison, GHCR publishing with an SBOM and provenance on release tags, and a nightly
  from-scratch build. `strata serve` gained `--public-url` / `STRATA_PUBLIC_URL` (Host and Origin are
  validated against it; DNS-rebinding protection stays), `STRATA_TOKEN`, and an unauthenticated
  `GET /healthz`; `strata --version` now exists. **The image has not been built or run** (no container
  runtime in the build environment; CI built and smoke-tested it on amd64 and arm64 on the first run), the
  base image is pinned by digest, and cosign signing is not done. `.github/workflows/container.yml` builds both architectures, publishes them to GHCR and smoke-tests
  what was published. See `docs/container.md`.
- **M6: CI for review repositories** (OpenSpec change `add-review-repository-ci`, in flight). `strata
  init --ci [--ci-ref REF] [--methodologist LOGIN]` installs a workflow that, on pull requests, runs `strata
  verify`, comments what the change does to the review (records entering and leaving, decisions invalidated,
  conflicts opened) and labels a change to the criteria `protocol-amendment` with a review request to the
  methodologist. It calls the reusable workflow `.github/workflows/review-ci.yml`; `actions/verify` is a
  composite action that installs `strata` from its own checkout and runs `strata verify`. New helper
  commands `strata ci amendment` and `strata ci comment`; `strata status --json` gained `included` and
  `stale_included` per stage. Written and tested locally (the workflow's shell steps run against a fake
  `gh`); not yet run on GitHub and no release tag exists yet. See `docs/m6-plan.md`.
- **M5.1: `strata sync`** (capability `collaboration-sync`). One command to share a review through
  a git remote: it refuses a dirty tree, fetches with the 2/4/8/16-second retry, fast-forwards or
  merges, puts merged event files back in canonical order and re-links their hash chains (writing
  a `relink` event), regenerates the derived views, verifies, and restores the repository
  untouched with nothing pushed if verification fails; then it pushes (up to three rounds when
  someone pushed meanwhile) and says what changed in terms of people and decisions. Dual
  screening never conflicts; a criterion reworded by two people is shown as `mine` and `theirs`
  and settled with `--resolve mine|theirs`, a prompt or an editor. `strata merge-regenerate` and
  `strata merge-records` are the git merge drivers `init` and `doctor --fix` install; the records
  driver merges field by field and its decisions become `record-amend` events. A clone without
  the drivers still syncs. E2E-02 now runs two CLI-driven collaborators through repeated syncs.
  Partial: the rebase strategy and the editor option are lightly tested; see `docs/m5-1-plan.md`.
- **M5: reporting** (OpenSpec change `add-prisma-reporting`, in flight until its two open
  items close). `derived/counts.json` holds every PRISMA 2020 count, derived from the
  import manifests, records, decisions, retrievals and study grouping and partitioned by
  where each record was found, with the reconciliation identities asserted
  (`E_COUNT_RECONCILE` in `strata verify` and before any report). `strata prisma` draws
  the flow diagram (SVG, PDF, PNG, JSON with the `PRISMA2020` R package input; one or two
  columns; reasons beyond six collapsed with the full table beside it; a DRAFT watermark
  and `--allow-stale` while decisions are stale) and `/prisma` shows it live. `strata
  report checklist [--status]` writes the 27-item checklist as auto-filled, auto-located
  or author, with item 24c generated from the criteria-change events (what each
  amendment invalidated and what became of it) and funding and competing-interest
  statements read from new `[project.funding]` and `[project.competing_interests]`
  tables. `strata report methods|results|characteristics|amendments|rob|manuscript`
  drafts those sections (and a risk-of-bias table and traffic-light plot) under the
  rules for generated prose, with pandoc export to docx, LaTeX and HTML; a Discussion or
  Conclusion is refused. `strata export bibliography --set included|excluded-at-fulltext|
  all-screened|not-retrieved` (BibTeX, CSL-JSON, RIS) and `strata export package` (no
  full text, a required data licence, deterministic bytes). New tests: P11 over random
  review histories, E2E-03 through to the package, E2E-01's generated amendment and
  reconciled counts, golden flow diagrams. The checklist wording is Table 1 of the
  PRISMA 2020 statement word for word, pinned by a fixture parsed from the article. Open:
  the generated Methods have not had a methodologist's review. See `docs/m5-plan.md`.
- **M4: analysis** (OpenSpec change `add-meta-analysis`, in flight until its last
  test-suite item closes). `strata analyze [<id>] [--all] [--check]` runs the
  versioned `analysis/<id>.yaml` specifications and writes
  `analysis/results/<id>/` (`estimates.json`, `studies.tsv`, `summary.md`, plots,
  and `run.json` with an `input_digest` that distinguishes stale data from a
  changed tool). The native `stats` package computes effect sizes with
  conversions from t, F, r, chi-square and p; common-effect and random-effects
  models with eight `tau^2` estimators, Knapp–Hartung with `metafor`'s ad hoc
  truncation, Q / I² / H² with a Q-profile interval, prediction intervals and
  meta-regression; aggregation, a multilevel working model and CR2 cluster-robust
  inference for dependent effects; Egger, Peters, Harbord, Begg, trim-and-fill
  and PET-PEESE; and leave-one-out, influence diagnostics and cumulative
  analyses. All of it is compared with committed `metafor` / `clubSandwich`
  fixtures (`tests/statistical`, 1e-8 relative), the Borenstein, BCG, Raudenbush
  and Niel-Weise examples, property tests (P12 among them) and every numerical
  edge case. Plots (forest, funnel, Baujat, bubble) are deterministic SVG and
  PDF drawn without a plotting library and compared byte for byte with committed
  files. Fourteen named guardrails are recorded in `run.json`; the underpowered
  bias-test guardrail blocks (exit code 8) unless `--force` is given. New:
  `strata diff <ref>..<ref>` (criteria, records, pools, included studies and each
  committed pooled estimate), analyses in `strata status` and `strata verify`,
  the `/analysis` and `/analysis/<id>` web screens, a `single-group-proportion`
  extraction design, and a nightly `metafor-live` job that installs R and fails
  when a regenerated number drifts. Open: the Hedges & Olkin worked example;
  macOS and Windows byte-identity and the nightly job have not yet run on
  GitHub. See `docs/m4-plan.md`.
- **M3: full text and extraction** (archived OpenSpec change
  `add-full-text-and-extraction`; four new capability specs —
  `full-text-retrieval`, `study-grouping`, `data-extraction`, `risk-of-bias`).
  `strata retrieve` works the retrieval queue and writes `retrieval` events and
  the committed `fulltext/manifest.ndjson` (documents identified by identifier
  and version, never by file hash; a fixed vocabulary of not-retrieved reasons;
  opt-in Unpaywall links, never a download). `strata studies` groups reports into
  studies and splits multi-study reports, with suggestions from shared
  registrations, authors and samples, follow-up wording and mutual citation.
  `strata extract` (`init`, forms with `value @ source` locators, `--missing`,
  scripted `--set` / `--effect`, `--reconcile`) with unit conversion (time, mass,
  length, dose, project extensions, `E_UNIT`), effect entry for every reported
  form (means with SD/SE/CI, 2x2 tables, correlations, test statistics,
  p-value only, pre-post, pre-computed) following `metafor`'s conventions with
  the size shown as you type, six data-quality guards with auditable
  acknowledgements, and dual extraction with field-by-field reconciliation.
  `strata rob` with RoB 2 algorithmic suggestions and recorded overrides,
  ROBINS-I, Newcastle-Ottawa, and custom instruments; judgements are available as
  `rob_overall` / `rob.<domain>` in filters and exports. `strata export effects`
  (csv, tsv, json, xlsx, rds) and `strata export provenance`. `strata verify`
  enforces `E_ORPHAN_EXTRACTION`, `E_MISSING_EXTRACTION`, `E_UNIT` and
  `E_EFFECT_INPUTS`; `strata status` lists studies with missing values. Web
  screens `/extract`, `/extract/<study>`, `/extract/<study>/reconcile`, `/rob/<study>`.
  New tests include E2E-03 (to the analysis step), the extraction half of E2E-06,
  and loading the export into real `metafor`. See `docs/m3-plan.md` and
  `docs/rob-instruments.md` for what is partial (RoB 2 has not been compared with
  Cochrane's own tables; no official question wording is bundled).
- A study excluded at an earlier screening stage is no longer an included study,
  so a title/abstract reversal leaves its extraction as an orphan rather than live.
- Domain commands no longer fail on an empty commit when nothing changed.

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

### Changed

- **`strata fix` corrects authors and years, keeps a record's identity in step, and skips no-ops.** It could
  only edit plain-text fields; it now also takes `--field author` (`Family, Given; Family, Given`, a name with
  no comma kept whole), `--field year` (four digits; the month and day are kept) and `--field issued` (`YYYY`,
  `YYYY-MM` or `YYYY-MM-DD`), and the web form offers the same. A DOI, PMID, PMCID or ISBN is stored as an
  import stores it (`https://doi.org/10.1000/ABC.` becomes `10.1000/abc`), an empty value removes the field
  (a title cannot be removed), and a value the record already has records nothing, commits nothing and needs
  no reason. A field that is not metadata is refused with the list of those that are. The record keeps its
  id, as the specification has always said, and when a correction changes how it is identified (a DOI, or the
  year of a record with none) the id the corrected identity gives becomes an alias of it: an export carrying
  the corrected value, or still carrying the old one, is now matched to the record instead of being added as
  a second record, and a correction that gives a record another record's identity names that record so
  `strata dedup` can merge them. `strata why` and the record page show authors and dates as text.
- **`strata assign` refuses a handle that is not an active actor of the review.** It used to record an
  assignment to any handle, including a typo, which left records in a queue nobody could work. It now refuses
  (exit 2, nothing written, with or without `--no-commit`) a handle that was never added or has been
  deactivated, names each one, and lists the actors who can be assigned:
  `error: cannot assign 'ghost' (not an actor of this review); eligible actors are ['ethan', 'sam']`. The web
  form was already limited to these actors and now gives the same message.
- Commands that change what the derived files show now regenerate all of them, not just the counts: a commit by
  `strata import`, `dedup`, `fix`, `assign`, `retrieve` or `studies` can include changes to `derived/pool.tsv`,
  `conflicts.tsv`, `stale.tsv` and `irr.json` as well as `counts.json`.

### Fixed

- **`strata verify` did not notice a derived file that was out of date.** It checked only that the counts the
  events would produce close, never that `derived/counts.json` (or `pool.tsv`, `conflicts.tsv`, `stale.tsv`,
  `irr.json`) says what regenerating it would write, though the specification has always required it
  (`E_DERIVED_DRIFT`). It now reports the file by name and fails. Making it check showed that four commands
  left derived files wrong, each now fixed: `strata init` wrote `{}` for `irr.json` and `counts.json` (so a
  brand-new review would have failed), `strata import` left `pool.tsv` without the new records, and `strata
  dedup` and `strata fix` left it listing a merged-away record and the old title. Reviews made before this
  version can show the same drift; `strata verify --fix` repairs it.
- **`strata verify --fix` did nothing.** The flag was accepted and ignored, so it reported success whatever was
  wrong. It now regenerates the derived files that drifted (leaving them uncommitted) and says which. It does
  not yet re-link broken hash chains or truncate half-written lines; those problems are still reported and not
  repaired. `strata verify --fast` and the pre-commit hook do not check drift yet, since regenerating the views
  does not fit the two seconds that mode is allowed.
- **Every form in the web interface was refused by a real browser.** The server sent `Referrer-Policy:
  no-referrer`, under which browsers send `Origin: null` on every form post, even to the same site, and the
  `Origin` check rejected it with `invalid Origin header`. Screening decisions, adjudication, criteria edits,
  duplicate merges, extraction and risk-of-bias forms all failed in Chromium (the tests use an in-process
  client that sends no `Origin`, so none could see it). The policy is now `same-origin`, which still sends
  nothing to other sites.
- After a duplicate merge in the web interface, the committed `derived/counts.json` still showed the old
  number of duplicates removed (the command line regenerated it; the web route did not).
- The dashboard's stage table scrolled sideways at a phone's width (320 px), which the accessibility
  requirement forbids; it, and the tables on the new pages, now stack as labelled cards on a narrow screen.
- `strata import` of a file with a long name (more than about 25 characters, such as
  `medline-export-2026-10-01-final-v2.ris`) and `strata search add` for a database with a long name (such as
  the Cochrane Central Register of Controlled Trials) failed with a `ValueError` traceback *after* writing and
  staging their files, because the commit subject is limited to 72 characters and included the name. The
  subject is now shortened to fit and the full id or file name stays in the commit trailers, the import
  manifest and the stored file. Found while moving the two commands onto `strata.core.operations` (OpenSpec
  change `add-web-ui-write-surfaces`), where every uploaded file name and database name is the user's.
- Started by a path that is not on `PATH` (`/opt/venv/bin/strata ...`, or an environment that is not
  activated), `strata` made every commit fail: the hooks it triggers run `strata` by name and died with
  `exec: strata: not found`, and `strata init` left a repository with nothing committed and every file
  staged. Git is now run with the directory of the running `strata` on the end of `PATH` when `strata`
  does not already resolve, which also repairs existing repositories. The hook scripts of a new
  repository check for `strata` first: `pre-commit` and `commit-msg` block with a message naming
  `STRATA_SKIP_HOOKS=1`, as `openspec:git-integration#versioned-hooks` requires, and `post-merge` and
  `post-checkout` warn and succeed. Existing repositories keep their hook scripts
  (OpenSpec change `make-hooks-find-strata`).
- A mutating command run non-interactively without `--why` or `--why-file` exited with code 7 only
  after it had written its files, leaving the working tree dirty with nothing committed (`strata actor
  add` left `strata.toml` modified; `strata dedup` left its merges in `records/`, `events/dedup/` and
  `derived/counts.json`), which then made `strata sync` refuse. Every mutating command now checks
  first and exits with code 7 before it writes anything; a `--why` that would be rejected (stop-listed,
  too short) or an unreadable `--why-file` is refused at the same point, with a message rather than a
  traceback. Interactive runs still prompt after the work and `--no-commit` still needs no rationale.
  `strata dedup` and `strata import` skip the refusal when they have nothing to commit, so a rerun
  needs no `--why`; a usage error in another command (an unknown actor or stage) now needs one to be
  reached (OpenSpec change `refuse-missing-rationale-before-writing`).
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
