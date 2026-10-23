# risk-of-bias Specification

## Purpose

Risk-of-bias assessment with standardised shipped instruments: instrument
definitions, per-reviewer assessments with support and source locators,
algorithmic suggestions with recorded overrides, reconciliation, and RoB
judgements as analysis moderators.

## ADDED Requirements

### Requirement: Instrument definitions

`rob/instrument.yaml` MUST define an instrument with `instrument`, `version`,
`applies_to`, `domains` (each with `id`, `label`, `judgements`, and signalling
questions with options), and an `overall` algorithm (`worst-domain` or
`custom`). `strata` MUST ship RoB 2, ROBINS-I, and the Newcastle-Ottawa Scale as
built-in definitions and MUST allow a custom instrument in the same shape.

#### Scenario: Custom instrument

- **WHEN** a project defines a custom instrument in the documented shape
- **THEN** it validates and can be used for assessment

### Requirement: Assessments mirror extraction

A per-study RoB assessment MUST record, per domain, a judgement, free-text
support, and a source locator, with per-reviewer assessments reconciled into a
consensus exactly as extraction is; each judgement is a `rob` event.

#### Scenario: Domain judgement

- **WHEN** a reviewer judges RoB 2 Domain 1 as low with support text
- **THEN** a `rob` event records the study, domain, judgement, and support

### Requirement: Algorithmic suggestion with recorded override

Where an instrument defines an algorithm (RoB 2 does), `strata rob` MUST compute
the algorithmic suggestion from the signalling answers and MUST allow the
reviewer to override it with a recorded justification. RoB 2 suggestions MUST
match the published decision rules.

#### Scenario: Override

- **GIVEN** the algorithm suggests LOW for a domain
- **WHEN** the reviewer judges SOME CONCERNS with a justification
- **THEN** both the suggestion and the overriding judgement with its justification are recorded

### Requirement: RoB plots and moderators

`strata report rob` MUST emit a robvis-compatible traffic-light plot and summary
bar plot. RoB judgements MUST be available as moderators (`rob_overall`,
`rob.<domain>`) in analysis and filters.

#### Scenario: Low-risk sensitivity analysis

- **WHEN** an analysis subset filter `rob_overall == 'low'` is used
- **THEN** only studies with an overall low risk of bias are included
