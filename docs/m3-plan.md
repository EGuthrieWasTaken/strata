# M3 ("Full text and extraction") — implementation notes

A working note for whoever picks up the work after M3, modelled on
[`m2-plan.md`](m2-plan.md). The normative text is the archived OpenSpec change
`add-full-text-and-extraction` and the specs it merged into:
[`full-text-retrieval`](../openspec/specs/full-text-retrieval/spec.md),
[`study-grouping`](../openspec/specs/study-grouping/spec.md),
[`data-extraction`](../openspec/specs/data-extraction/spec.md),
[`risk-of-bias`](../openspec/specs/risk-of-bias/spec.md), plus additions to `cli`, `web-ui`, and
`data-schemas`. This file records what was built, the conventions that emerged, and what is
deliberately partial.

## Status

| Group | What | Status |
|---|---|---|
| 1 | `strata retrieve`, the `retrieval` event, `fulltext/manifest.ndjson`, not-retrieved reasons, opt-in Unpaywall links | done |
| 2 | `strata studies`, `study-group` / `study-split`, grouping and splitting suggestions | done |
| 3 | Extraction: schema, `strata extract` (init, forms, `--missing`, scripted entry, `--reconcile`), units, effect entry with live size, quality guards and acknowledgements, verify codes, `strata export effects` and `strata export provenance` | done |
| 4 | Risk of bias: five instruments, RoB 2 suggestions with recorded overrides, `strata rob`, moderators | done, with the caveat below |
| 5 | CLI `--json` output; `/extract`, `/extract/<study>`, `/extract/<study>/reconcile`, `/rob/<study>` web screens | done |
| 6 | Unit-conversion round trips, one test per guard, RoB 2 oracle, reconciliation events, `metafor::rma()` load test, E2E-03 up to the analysis step, E2E-06 extension | done |

### Partial or deliberately left for later

- **RoB 2 against the primary tables.** The algorithms match two independent open-source
  transcriptions on every one of 82,125 answer combinations, but could not be compared with the
  Cochrane document itself. [`rob-instruments.md`](rob-instruments.md) lists what to check before
  a release. No official question wording is bundled (licence); a project may add it.
- **`strata report` extras.** The spec asks `strata report` to emit a per-value provenance table,
  the extraction agreement rate, and robvis-compatible RoB plots. `strata report` is M5. The data
  is ready: `export.provenance_table`, `reconcile.agreement_rate`, and the `rob_overall` /
  `rob.<domain>` moderators.
- **Analysis.** E2E-03 is asserted up to the analysis step; M4 extends it.
- **Cluster and crossover RoB 2** variants, ROBINS-E, QUADAS-2: define as custom instruments.
- **R tests need R.** The `metafor` load test and the RDS reader test skip when `Rscript` /
  `metafor` are absent. They were run against R 4.3 and `metafor` 4.4 while writing this.

## Conventions established

Everything in [`m1-plan.md`](m1-plan.md) and [`m2-plan.md`](m2-plan.md) still applies. Additions:

- **Identity.** A report is `rpt_<16>` (the same 16 characters as the record it was promoted
  from); a study is `std_<16>`. An ungrouped report is a study of one whose id is *derived*
  (`singleton_study_id`), so no event has to create it; `study-group` mints fresh ids. Effects are
  `eff_<study>_<4 digits>`, assigned at entry in single mode and at reconciliation in dual mode.
- **Included studies.** `studies.included_reports` is the reports that resolved to `include` at the
  last stage and were not excluded at an earlier one, so a title/abstract reversal takes a study out
  of the review and leaves its extraction as an `E_ORPHAN_EXTRACTION` (kept, never deleted).
- **Pure core, thin edges.** `core/fold.py` gained the retrieval and study folds (pure, covered by
  the property tests P1/P2/P9). `stats/effect_sizes.py` is pure numbers. `extract/*` does file IO
  and event writing; `cli/main.py` and `web/extraction_routes.py` only marshal arguments.
- **Event bodies are validated twice**: by the event schema (`allOf` per event type) and by the
  function that writes them, before anything touches disk.
- **Files are authoritative; the log is the audit trail.** Extraction records and assessments are
  YAML a human can read; every change also appends an `extract` / `rob` / `reconcile` event naming
  what changed and a digest of the file.
- **Dual mode** (`[extraction] mode = "dual"`, set with `strata config extraction.mode dual`) puts
  each reviewer's work in `by-reviewer/<handle>/` and the agreed result in `consensus/`; risk-of-bias
  assessments follow the same mode. Reconciliation writes both a `reconcile` event and the
  consensus file, and the web screen calls the same function as the CLI.
- **Quality guards warn, never block**, and an acknowledgement is a `note` event with subject
  `quality-ack`, so it does not recur and stays in the log.
- **Domain commits are skipped when nothing changed** (`gitio.has_changes`), so re-running an
  idempotent command does not fail on an empty commit.
- **Subcommand-like arguments.** `strata extract init` and `strata rob init` are the first positional
  argument of a single command (a study id never looks like `init`), not Typer sub-commands, so
  `strata extract <study>` keeps its documented shape.
