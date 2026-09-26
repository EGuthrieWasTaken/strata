# Design: architecture

*Informative.* The requirements are in [spec.md](spec.md).

## Stack decision: Python 3.11+

Decided, with the reasoning recorded so it is not re-litigated:

| Candidate | For | Against | Verdict |
|---|---|---|---|
| **Python** | Best-in-class bibliographic parsing (`rispy`, `bibtexparser`), mature numerics (`numpy`, `scipy`), excellent CLI and web tooling, the language most quantitative researchers can already read and patch | Meta-analysis libraries are weak compared with R; packaging has historically been painful (now solved by `uv`/`pipx`) | **Chosen** |
| R | `metafor` is the gold standard | Poor fit for a long-running local web server, CLI ergonomics, file-format work, and cross-platform packaging; a reviewer who cannot install R cannot screen | Rejected as the core; retained as an optional analysis engine |
| Rust / Go | Single-binary distribution, fast | Statistical ecosystem is thin; contributions from the target community would be near zero | Rejected |
| TypeScript | Best UI story | Numerics and parsing ecosystems are weakest; Node toolchains age badly | Rejected |

The decisive argument is contribution: the people motivated to fix a parser for
a weird PsycINFO export are research assistants and methodologists, and they
know Python or R. Python loses on statistics, which is recoverable by validating
against `metafor`; R loses on everything else, which is not.

## Why the seams

- **The fold is pure** so it can be tested exhaustively (it is one of the five
  100%-branch-coverage modules) and cached safely.
- **Only `gitio` invokes git**, which keeps the tool usable on a non-git
  directory for testing and makes the git dependency swappable.
- **Presentation layers hold no domain logic**, which is what guarantees the
  CLI, web UI, and MCP server cannot diverge in behaviour — and what makes a
  hosted deployment a new adapter rather than a rewrite.
- **`stats` knows nothing of the repository**, so it is testable against
  `metafor` fixtures in isolation and reusable as a library.
- **Parsers never write events**, so they can be fuzzed.

## The cache

`.strata/cache/` holds the fold result keyed by the digest of the event-log
inputs. Because events are append-only and the fold is last-write-wins,
appending N events to a cached state needs only those N events — except an
`adjudicate` or `criteria-change` event, which can change many records and
forces recomputation of the affected slice. The fold must be fast enough without
the cache that a corrupt cache is never a blocker.

## Why the Prioritiser can only reorder

The `Prioritiser` interface is where machine-assisted screening (active learning
à la ASReview) would land. It is deliberately shaped as reordering only: a
prioritiser can change the order in which a human sees records and can never
make or withhold a decision. That constraint is what keeps auditability intact.

## The `metafor` engine

Its purpose is twofold: an escape hatch for models the native engine does not
implement and, more importantly, the validation oracle in CI.

## Dependencies

Every dependency is a future maintenance liability for a project that must run
unchanged for a decade.

| Purpose | Choice |
|---|---|
| CLI | `typer` |
| Config/validation | `pydantic` v2, `tomllib` / `tomlkit` |
| YAML | `ruamel.yaml` (round-trips comments, which hand-edited protocol files need) |
| Web | `fastapi`, `uvicorn`, `jinja2` |
| Numerics | `numpy`, `scipy` |
| Bibliographic parsing | `rispy`, `bibtexparser`; hand-written MEDLINE and EndNote parsers |
| Plotting | Hand-written SVG emission — **decided** |
| Terminal UI | `rich` |
| MCP | `mcp` |
| Testing | `pytest`, `hypothesis`, `pytest-benchmark` |

**On plotting:** matplotlib is the obvious choice and is rejected for
determinism. Its SVG output embeds version metadata and non-deterministic
element ids, and byte-identical output across versions and platforms is not
something it promises. Forest and funnel plots are rectangles, lines, circles,
and text; a hand-written emitter is perhaps 800 lines, fully deterministic, and
removes a 30 MB dependency.
