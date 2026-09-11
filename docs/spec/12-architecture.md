# 12 — Architecture *(informative, except where marked)*

## 1. Stack decision

**Python 3.11+.** Decided, with the reasoning laid out because the implementer
will otherwise re-litigate it.

| Candidate | For | Against | Verdict |
|---|---|---|---|
| **Python** | Best-in-class bibliographic parsing (`rispy`, `bibtexparser`, `pybtex`), mature numerics (`numpy`, `scipy`), excellent CLI and web tooling, the language most quantitative researchers can already read and patch | Meta-analysis libraries are weak compared with R; packaging has historically been painful (now solved by `uv`/`pipx`) | **Chosen** |
| R | `metafor` is the gold standard and would be free | Poor fit for a long-running local web server, CLI ergonomics, file-format work, and cross-platform packaging; a reviewer who cannot install R cannot screen | Rejected as the core; retained as an optional analysis engine |
| Rust / Go | Single-binary distribution, fast | Statistical ecosystem is thin; contributions from the target community would be near zero | Rejected |
| TypeScript | Best UI story | Numerics and parsing ecosystems are weakest; Node toolchains age badly | Rejected |

The decisive argument is contribution: this is a small FOSS project in an
academic niche. The people motivated to fix a parser for a weird PsycINFO export
are research assistants and methodologists, and they know Python or R. Python
loses on statistics, which is recoverable by validating against `metafor`; R
loses on everything else, which is not.

**The statistics gap is closed by validation, not by reimplementing R.** See
[14 §4](14-testing.md).

## 2. Module boundaries *(normative — the seams matter)*

```
strata/
├── cli/              Typer commands; argument parsing; output formatting only
├── web/              FastAPI app, Jinja templates, static assets
├── core/
│   ├── repo.py       Repository discovery, config, locking
│   ├── events.py     Event envelope, append, chain, validation
│   ├── fold.py       Event log -> current state (pure, deterministic)
│   ├── ids.py        Identity and normalisation (01 §3)
│   ├── canon.py      Canonical serialisation (02 §5)
│   └── derive.py     Derived-view generation
├── protocol/         Criteria, searches, moderators, the staleness engine
├── ingest/
│   ├── parsers/      ris.py, nbib.py, bibtex.py, endnote.py, csv.py, csljson.py
│   ├── profiles/     Platform CSV column mappings
│   └── enrich/       Opt-in Crossref / OpenAlex / PubMed / Unpaywall clients
├── dedup/            Blocking, scoring, merge policy
├── extract/          Coding-form schema, validation, units, reconciliation
├── stats/
│   ├── escalc.py     Effect-size computation and conversion
│   ├── models.py     Pooling, tau^2 estimators, meta-regression
│   ├── robust.py     Cluster-robust / multilevel
│   ├── bias.py       Publication-bias methods
│   ├── diagnostics.py
│   └── engines/      native.py, metafor.py
├── report/           PRISMA flow, checklist, prose, exports
├── gitio/            The only module that shells out to git
└── schemas/          JSON Schema files (shipped data)
```

**Invariants**

1. `core.fold` is **pure**: events in, state out. No I/O, no clock, no
   randomness, no git. It is the most heavily tested module in the project.
2. `gitio` is the **only** module that invokes git. Everything else operates on
   the working tree. This keeps the tool usable on a non-git directory for
   testing and makes the git dependency swappable.
3. `cli` and `web` contain **no domain logic**. Both are thin adapters over the
   same service layer, which is what guarantees they cannot diverge in behaviour.
4. `stats` has **no knowledge of the repository**. It takes arrays and options
   and returns numbers, so it is testable against `metafor` fixtures in
   isolation and reusable as a library.
5. `ingest.parsers` never write events. They parse bytes to record dicts and
   report failures. Parsing and persistence are separable so parsers can be
   fuzzed.

## 3. Derived-state cache

`.strata/cache/state.sqlite` holds the fold result, keyed by the digest of the
event-log inputs. It is an optimisation only:

- Gitignored, never authoritative.
- Invalidated when any event file's digest changes, on `post-checkout`, and on
  schema version change.
- Deletable at any time with no loss.
- The fold MUST be fast enough to run without it (under 5 s for 50k records), so
  a corrupt cache is never a blocker.

Incremental folding: because events are append-only and the fold is a
last-write-wins reduction, appending N events to a cached state requires
processing only those N events, except when an `adjudicate` or `criteria-change`
event arrives, which can change many records' derived state and forces
recomputation of the affected slice.

## 4. Concurrency and locking

The web server and the CLI can run simultaneously against one repository.

- A single advisory lock file `.strata/lock` guards *mutating* operations, taken
  for the duration of the append-plus-commit, with a 30-second timeout and a
  clear message naming the holding process.
- Readers never take the lock. A reader that sees a partially written last line
  in an NDJSON file MUST skip it (it has no valid `digest`) rather than fail —
  the write will complete momentarily.
- Appends use `O_APPEND` writes of a complete line, which are atomic for writes
  under `PIPE_BUF` on POSIX; longer lines are written to a temp file and renamed.
  On Windows, appends are serialised through the lock.

## 5. Plugin boundaries

Defined in v1 so that later features do not require re-architecting. Nothing
ships behind them in v1 except the built-in implementations.

| Interface | Purpose | v1 implementations |
|---|---|---|
| `Parser` | `parse(bytes) -> Iterator[Record], Iterator[ParseError]` | RIS, NBIB, BibTeX, EndNote XML, CSV, CSL-JSON, XLSX |
| `Enricher` | `enrich(Record) -> dict[field, value]` | Crossref, OpenAlex, PubMed, Unpaywall (all opt-in) |
| `Prioritiser` | `rank(records, decisions) -> order` — reorders the screening queue | `natural` (import order), `random` (seeded) |
| `Engine` | `fit(effects, spec) -> Results` | `native`, `metafor` |
| `Instrument` | RoB instrument definition | RoB 2, ROBINS-I, NOS |
| `Renderer` | `render(Results) -> bytes` | SVG, PDF, PNG |

The `Prioritiser` interface is where machine-assisted screening would land
(active learning à la ASReview). It is deliberately shaped as *reordering only*:
a prioritiser can change the order in which a human sees records, and can never
make or withhold a decision. That constraint is what keeps auditability intact,
and it MUST hold for any future implementation.

## 6. The `metafor` engine

`engine = "metafor"` shells out to `Rscript` with a JSON contract on stdin and
stdout. It is optional, detected at runtime, and its absence is never an error
unless explicitly selected.

Its purpose is twofold: as an escape hatch for models `native` does not
implement, and — more importantly — as the validation oracle in CI
([14 §4](14-testing.md)).

## 7. Distribution

| Channel | Notes |
|---|---|
| PyPI | `pipx install strata-review` / `uv tool install strata-review` — the primary path |
| Homebrew | macOS and Linux formula |
| Standalone binaries | PyInstaller builds for macOS (universal), Windows (x64), Linux (x64, musl) attached to each release — for Sam, who will not install Python |
| Docker | For CI and reproducibility archives |
| Conda-forge | Follow-on; the academic audience uses it heavily |

A first-time user MUST be able to go from nothing to a screening session in
under five minutes on any of the three major platforms. That is a release
criterion, tested on all three ([15](15-roadmap.md)).

## 8. Dependencies

Kept deliberately small; every dependency is a future maintenance liability for a
project that must run unchanged for a decade.

| Purpose | Choice |
|---|---|
| CLI | `typer` |
| Config/validation | `pydantic` v2, `tomli`/`tomllib` |
| YAML | `ruamel.yaml` (round-trips comments, which hand-edited protocol files need) |
| Web | `fastapi`, `uvicorn`, `jinja2` |
| Numerics | `numpy`, `scipy` |
| Bibliographic parsing | `rispy`, `bibtexparser`; hand-written NBIB and EndNote parsers |
| Tabular I/O | `polars` (or `pandas`; polars preferred for import speed and lower memory) |
| Plotting | Hand-written SVG emission — **decided** |
| Terminal UI | `rich` |
| Testing | `pytest`, `hypothesis`, `pytest-benchmark` |

**On plotting:** matplotlib is the obvious choice and is rejected for the
determinism requirement ([02 §5.5](02-repository-format.md)). Its SVG output
embeds version metadata and non-deterministic element ids, and byte-identical
output across versions and platforms is not something it promises. Forest and
funnel plots are simple enough to emit directly: they are rectangles, lines,
circles, and text. A hand-written emitter is perhaps 800 lines, is fully
deterministic, and removes a 30 MB dependency. `matplotlib` MAY be offered as an
optional renderer for users who want to restyle plots, but MUST NOT be the one
whose output is committed and verified.
