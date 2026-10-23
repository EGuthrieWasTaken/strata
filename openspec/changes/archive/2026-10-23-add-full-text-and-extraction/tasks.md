# Tasks

## 1. Retrieval and the full-text manifest

- [x] 1.1 Implement `strata retrieve` and the `retrieval` event (schema, fold cases, P1/P2/P9 generator inclusion)
- [x] 1.2 Write and validate `fulltext/manifest.ndjson` entries keyed by `locator`, with `version` and optional `related`
- [x] 1.3 Enforce the fixed not-retrieved reason vocabulary and feed it to the counts
- [x] 1.4 Opt-in Unpaywall link surfacing (no downloads) behind `enrichment`

## 2. Study grouping

- [x] 2.1 Implement `strata studies` with `study-group` / `study-split` events and required rationales
- [x] 2.2 Implement grouping/splitting suggestions (shared registration, author set + sample, "follow-up of" language, mutual citation)

## 3. Extraction

- [x] 3.1 Ship JSON Schemas for `extraction/schema.yaml` and extraction records
- [x] 3.2 Implement `strata extract init` (draft form from moderators and outcomes)
- [x] 3.3 Implement coding forms with one-keystroke source locators and `--missing`
- [x] 3.4 Implement unit conversion tables (time, mass, length, dose), project extensions, and `E_UNIT`
- [x] 3.5 Implement effect entry for every reported form with live effect-size display
- [x] 3.6 Implement dual extraction and `strata extract --reconcile` with `reconcile` events
- [x] 3.7 Implement the data-quality guards with recorded acknowledgements
- [x] 3.8 Enforce `E_ORPHAN_EXTRACTION`, `E_MISSING_EXTRACTION`, `E_EFFECT_INPUTS` in `strata verify`
- [x] 3.9 Implement `strata export effects --format csv|tsv|xlsx|rds|json`

## 4. Risk of bias

- [x] 4.1 Ship RoB 2, ROBINS-I, and NOS instrument definitions (licence terms checked and documented)
- [x] 4.2 Implement `strata rob` with algorithmic suggestions and recorded overrides
- [x] 4.3 Expose RoB judgements as analysis moderators

## 5. Surfaces

- [x] 5.1 Add the CLI commands and their `--json` output
- [x] 5.2 Add `/extract/<study>`, `/extract/<study>/reconcile`, and `/rob/<study>` web screens

## 6. Tests (suite additions, docs/roadmap.md M3)

- [x] 6.1 Unit-conversion round-trip tests
- [x] 6.2 A test asserting each data-quality guard fires
- [x] 6.3 RoB 2 algorithmic judgements against a published decision set (two independent open-source transcriptions of the Cochrane tables, compared on all 82,125 combinations; the primary tables themselves are unchecked, see `docs/rob-instruments.md`)
- [x] 6.4 Reconciliation event coverage
- [x] 6.5 Verify `strata export effects` output loads in `metafor::rma()`
- [x] 6.6 E2E-03 passes up to the analysis step
