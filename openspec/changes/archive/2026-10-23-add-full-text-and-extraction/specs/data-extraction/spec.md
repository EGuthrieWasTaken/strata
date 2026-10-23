# data-extraction Specification

## Purpose

Extracting study-level fields and effect data from included studies into an
analysis-ready dataset: the versioned coding form, per-value source locators,
units, dual extraction with reconciliation, effect entry in whatever form a
paper reports, data-quality guards, and export for analysis elsewhere.

## ADDED Requirements

### Requirement: Extraction schema

`extraction/schema.yaml` MUST define a versioned coding form with `fields`
(each with `name`, `label`, `type`, `required`, and type-specific constraints
such as `min`, `levels`, `unit`, `accepts_units`, `help`) and an `effects`
section declaring the outcome field, outcomes, and effect designs with the
inputs each requires. Field types MUST include `integer`, `number`, `quantity`,
`categorical`, `multi-categorical`, `boolean`, `text`, `date`, and `citation`.
`strata extract init` MUST generate a draft schema from the protocol's declared
moderators and outcomes.

#### Scenario: Draft form from the protocol

- **GIVEN** moderators `mean_age` and `design` in `protocol/moderators.yaml`
- **WHEN** `strata extract init` runs
- **THEN** `extraction/schema.yaml` is created with fields for both moderators

### Requirement: Schema changes make extractions incomplete, not stale

Schema changes MUST bump `version`. Adding a required field MUST mark existing
extractions incomplete for that field, not invalid: `strata status` lists
studies with missing values and `strata extract --missing` queues exactly those.

#### Scenario: New required field mid-extraction

- **GIVEN** 31 completed extractions
- **WHEN** a required field is added to the schema
- **THEN** the 31 studies are reported as missing that field and queued by `--missing`, and no prior value is invalidated

### Requirement: Extraction records and source locators

Consensus extraction records (`extraction/consensus/<study>.yaml`) and
per-reviewer records (`extraction/by-reviewer/<handle>/<study>.yaml`) MUST carry
the study, its reports, the schema version, who extracted and reconciled, each
field's value with its source locator, and the study's effects with their
inputs, source, and moderators. Every extracted value SHOULD carry a source
locator; the UI MUST make entering one a single keystroke, and `strata report`
MUST be able to emit a per-value provenance table.

#### Scenario: Provenance table

- **WHEN** a per-value provenance table is requested
- **THEN** every extracted value is listed with its study and source locator

### Requirement: Units

A `quantity` field MUST store the entered value and unit and the normalised
value. Unit conversion tables MUST ship for time, mass, length, and dose and be
extensible per project. An unconvertible unit is `E_UNIT` and blocks analysis.

#### Scenario: Retention interval in weeks

- **GIVEN** a field with `unit: hours` accepting `weeks`
- **WHEN** "1 week" is entered
- **THEN** the record stores value 168, unit `hours`, and entered `1 week`

#### Scenario: Unit outside accepts_units

- **WHEN** a value in `fortnights` is entered for a field that does not accept it
- **THEN** `strata verify` reports `E_UNIT`

### Requirement: Dual extraction and reconciliation

With `extraction.mode = "dual"`, two reviewers MUST extract independently into
`extraction/by-reviewer/<handle>/` and reconcile into `extraction/consensus/`.
`strata extract --reconcile [<study>]` MUST present agreements and
disagreements field by field with each reviewer's value and source, and every
reconciliation MUST write a `reconcile` event with the chosen value, its source,
and a rationale. `strata report` MUST be able to state the extraction agreement
rate.

#### Scenario: Disagreement on a retention interval

- **GIVEN** `ethan` extracted 168 h and `sam` 24 h
- **WHEN** the reconciler chooses `ethan`'s value with a rationale
- **THEN** a `reconcile` event records the chosen value, both candidates, the source, and the rationale

### Requirement: Effect data entry in any reported form

`strata` MUST accept effect inputs as group means (with SD, SE, or CI), 2x2
tables, correlations, test statistics (`t, df`; `F, df1, df2`; `chi2, n`),
p-value only (`p, n1, n2, direction`), pre-computed (`yi, vi, measure`), and
pre-post (`n, m_pre, sd_pre, m_post, sd_post, r`), and MUST show the computed
effect size immediately as the user types. An effect lacking the fields its
declared design requires is `E_EFFECT_INPUTS`.

#### Scenario: SD entered as SE

- **WHEN** a reviewer enters group means and SDs
- **THEN** the computed effect size is displayed as they type, before saving

#### Scenario: Missing inputs

- **WHEN** a `two-group-means` effect lacks `sd2`
- **THEN** `strata verify` reports `E_EFFECT_INPUTS`

### Requirement: Data-quality guards

`strata` MUST warn — not block — on: an SD more than 3x or less than 1/3 of the
median SD for that outcome; a computed standardised effect with `|g| > 3`; a 2x2
table with a zero cell (explaining the correction that will be applied); `n`
inconsistent between `n_total` and the sum of arm `n`s; a p-value-derived effect
size; and a reported statistic inconsistent with its p-value (GRIM/statcheck
style, for t and F tests). Every warning MUST be recordable as acknowledged,
with a note, so it does not recur and the acknowledgement is auditable.

#### Scenario: Implausibly large effect

- **WHEN** an entered effect yields `g = 4.2`
- **THEN** a warning is shown and the value can still be saved

#### Scenario: Acknowledged warning

- **GIVEN** a warning acknowledged with a note
- **WHEN** extraction is revisited
- **THEN** the warning does not reappear and the acknowledgement is in the event log

### Requirement: Exporting effects for outside analysis

`strata export effects --format csv|tsv|xlsx|rds|json` MUST emit one row per
effect with all study-level and effect-level moderators joined, including
`study_id` and `effect_id`, directly loadable by `metafor::rma()`.

#### Scenario: Export to R

- **WHEN** `strata export effects --format csv` output is read into R
- **THEN** `metafor::rma()` accepts it and each row carries its `study_id` and `effect_id`

### Requirement: Orphaned and missing extractions are verified

`strata verify` MUST report `E_ORPHAN_EXTRACTION` for an extraction whose study
is not included (retaining the extraction), and `E_MISSING_EXTRACTION` for an
included study with no consensus extraction (a warning until analysis).

#### Scenario: Study excluded after extraction

- **WHEN** a study's record is excluded after its extraction was reconciled
- **THEN** `strata verify` reports `E_ORPHAN_EXTRACTION` and the extraction file still exists
