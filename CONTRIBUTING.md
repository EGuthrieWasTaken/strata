# Contributing to strata

`strata` is specified before it is built: the requirements are in [`openspec/`](openspec/README.md), the
milestone plan in [`docs/roadmap.md`](docs/roadmap.md), and what each finished milestone did and left
partial in `docs/m*-plan.md`. Read the spec for the area you are changing; if the change alters specified
behaviour, change the spec in the same pull request.

## Set up

You need Python 3.11+, [`uv`](https://docs.astral.sh/uv/) and `git`.

```
git clone https://github.com/EGuthrieWasTaken/strata.git
cd strata
uv sync
git config user.name "Your Name" && git config user.email you@example.org   # the tests make commits
```

## The checks a pull request must pass

```
uv run ruff format --check
uv run ruff check
uv run mypy src
uv run pytest -n auto                         # the whole suite on every core (pytest-xdist); `-k` or a path while you work
uv run python scripts/check_docs.py           # links, anchors and `openspec:` references resolve
npx --yes @fission-ai/openspec@1.13.2 validate --all --strict --no-interactive
```

CI runs the suite on Linux, macOS and Windows on Python 3.11 to 3.13 and requires coverage floors
(`openspec:test-suite#test-levels-and-coverage-floors`). Statistics modules are held to 100% branch coverage.
The pull-request template asks the questions that matter: is there a test that fails without the change, is
the requirement linked to its test, does the spec change, and does the user-facing documentation change.

## How the tests are laid out

| Directory | What it is |
|---|---|
| `tests/unit/` | one module at a time, pure functions first; shared builders are the `_m*.py` files |
| `tests/integration/` | the CLI through `typer`'s `CliRunner`, the web app through `TestClient`, real repositories in `tmp_path` |
| `tests/e2e/` | the numbered scenarios of `openspec:test-suite` (E2E-01 …), marked `@pytest.mark.req("E2E-0x")` |
| `tests/property/` | `hypothesis` properties (P1 … P13) for ids, normalisation, folding, staleness, counts |
| `tests/statistical/` | estimators against committed `metafor` output (`generate.R` regenerates it) |
| `tests/golden/` | parsers and plots against committed expected files (`STRATA_UPDATE_GOLDEN=1` rewrites them; read the diff) |
| `tests/fuzz/` | mutation fuzzing of every parser, run nightly |
| `tests/benchmark/` | performance targets; timing-sensitive, so run them alone |

## Conventions

- **Everything recorded is an event or a derived view.** Events are appended to per-actor NDJSON files and
  never edited; derived files are regenerated, never hand-written. A change that writes elsewhere needs a reason.
- **Statistics, the fold and the parsers know nothing of the repository** (`openspec:architecture`): plain
  values in, plain values out. `cli`, `web` and `mcpserver` are thin; domain logic belongs in `core`,
  `protocol`, `ingest`, `extract`, `stats`, `analysis` or `report`.
- **A rationale, not just a change.** Commands that change a review take `--why`; in this repository a commit
  message says why, not only what.
- **Errors are specific and say what to do.** Never `NaN`, never a stack trace for something a user can fix.
- **Do not tick what is not done.** A task in an OpenSpec change is checked only when the specified behaviour
  is fully built and tested; partial work gets a Notes section in `tasks.md` and a line in the milestone's
  plan.

## Adding an import parser

Import formats live in `src/strata/ingest/parsers/`; `openspec:literature-import` is the contract.

1. **Write `parse(text: str) -> ParseResult`.** The input is already decoded and newline-normalised. Return
   CSL-JSON-shaped records (without the `strata` extension; the pipeline adds it). A record that cannot be
   parsed, or has no title (`has_title`), becomes a `RejectedRow(line, raw, error)`; **never raise for one bad
   record** and never let it swallow its neighbours (split the file into records first, then parse each in
   isolation: see `ris.py` and `endnote_xml.py`). A format that is not text (a workbook) is converted to text
   in `pipeline.import_file` first, as `.xlsx` is to TSV, with every size cap you can name.
2. **Treat the file as hostile.** Cap sizes, refuse DOCTYPE and entity declarations in XML, never evaluate
   anything. If the parser has to *infer* fields (a formatted reference list), return
   `ParseResult(best_effort=True)`: the pipeline then flags the records `best-effort-parse` and deduplication
   leaves them for a person.
3. **Register it** in `ingest/pipeline.py`: `_PARSERS`, `_EXTENSION_FORMATS`, the `.txt` sniffing in
   `detect_format` if the extension is ambiguous, and the `--format` help in `cli/main.py`.
4. **Fixtures**: `tests/fixtures/exports/<format>/clean.<ext>` and `malformed.<ext>` with `*.expected.json`
   next to them, recorded in `tests/fixtures/SOURCES.md`. Fixtures are synthetic or bibliographic facts only
   (abstracts are always invented), because every fixture must be redistributable.
5. **Tests**: add the fixtures to `tests/golden/test_golden_parsers.py`, write `tests/unit/test_parsers_<format>.py`
   for the malformations real exports have, add the parser to `tests/fuzz/test_fuzz_parsers.py` (it must never
   raise on mutated input; fix what it finds), and import a file through `strata import` in
   `tests/integration/test_cli_import_formats.py`.
6. **Spec and docs**: update the format table in `literature-import` through an OpenSpec change, and the
   README/CHANGELOG lines that list formats.

## Changing the specification

```
openspec new change <name>        # proposal, design, tasks, delta specs under openspec/changes/<name>/
openspec validate <name> --strict
openspec archive <name> --yes     # when it has shipped; folds the deltas into openspec/specs/
```

A new capability needs a `design.md` as well as a `spec.md` (`scripts/check_docs.py` enforces it).
Requirements are cited from code and docs as `openspec:<capability>#<requirement-slug>`; renaming one means
updating its references in the same pull request.

## Documentation

User-facing documentation is kept in step with the feature: the README for what exists, `docs/` for the
references (`statistics.md`, `container.md`, the formats in `openspec/specs/repository-format`), and the
`docs/m*-plan.md` notes for what a milestone built and left partial.
