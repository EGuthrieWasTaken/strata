# Proposal: Full text, study grouping, and data extraction (M3)

## Why

After M2, a team can screen in `strata` but must leave it to obtain full texts,
group reports into studies, and extract data — exactly where provenance usually
goes to die (a parallel folder of PDFs, a spreadsheet of numbers with no
source). M3 carries the provenance chain from "included at full text" through to
an analysis-ready dataset, so a complete review can be conducted up to the
statistics.

Roadmap milestone: M3 ([docs/roadmap.md](../../../docs/roadmap.md)). Design detail: [design.md](design.md).

## What Changes

- A retrieval queue (`strata retrieve`) and the committed
  `fulltext/manifest.ndjson`, identifying documents by DOI or equivalent and by
  version, never by file hash.
- Study grouping and splitting (`strata studies`) with suggested groupings and
  required rationales.
- The extraction schema (`extraction/schema.yaml`), coding forms with source
  locators, unit handling, dual extraction with reconciliation, effect data
  entry in any reported form, and data-quality guards (`strata extract ...`).
- Risk-of-bias instruments (RoB 2, ROBINS-I, Newcastle-Ottawa shipped; custom
  allowed), per-reviewer assessment, algorithmic suggestions with recorded
  overrides (`strata rob`).
- `strata export effects` for analysis outside `strata`.
- New CLI commands and web screens for the above.

## Capabilities

### New Capabilities

- `full-text-retrieval`: the retrieval queue, the full-text manifest, version
  identification by identifier, and not-retrieved reasons.
- `study-grouping`: grouping reports into studies and splitting multi-study
  reports, with suggestions and rationales.
- `data-extraction`: the extraction schema and record, coding forms, source
  locators, units, dual extraction and reconciliation, effect entry and
  conversion display, data-quality guards, and the effects export.
- `risk-of-bias`: instrument definitions, assessments, algorithmic suggestions,
  reconciliation, and RoB as an analysis moderator.

### Modified Capabilities

- `cli`: adds the full-text and extraction command group.
- `web-ui`: adds the coding form, reconciliation, and risk-of-bias screens.

## Impact

- New modules: `strata/extract/` (schema, validation, units, reconciliation);
  retrieval and study-grouping services in `core`/`protocol`; new JSON Schemas
  for the extraction schema, extraction record, RoB instrument, and manifest
  entry; new event types already catalogued in `event-log` (`retrieval`,
  `study-group`, `study-split`, `extract`, `reconcile`, `rob`) get schemas and
  fold cases.
- `strata verify` begins enforcing `E_ORPHAN_EXTRACTION`,
  `E_MISSING_EXTRACTION`, `E_UNIT`, and `E_EFFECT_INPUTS` on real data.
- No schema-version bump is expected: the new files and event types are
  additive.
