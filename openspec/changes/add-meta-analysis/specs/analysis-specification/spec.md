# analysis-specification Specification

## Purpose

Declarative, versioned analysis files and the `strata analyze` run that turns
them into committed, byte-reproducible results — with the posture that every
estimator is validated or absent, named guardrails, and a reproducibility
record that distinguishes data changes from tool changes.

## ADDED Requirements

### Requirement: Validated or absent

Every estimator MUST be validated numerically against `metafor` to a relative
tolerance of 1e-8 on the fixture datasets; where `metafor` and another reference
disagree, `metafor`'s convention is authoritative and the difference MUST be
documented. Any model `strata` cannot compute correctly MUST be absent, not
approximated.

_Source: `docs/spec/08-analysis.md` §1_

#### Scenario: Unsupported model requested

- **WHEN** an analysis requests a model the native engine does not implement
- **THEN** `strata analyze` refuses with an error suggesting `strata export effects` or the `metafor` engine

### Requirement: Analysis specification file

An analysis MUST be declared in `analysis/<id>.yaml` with `id`, `title`,
`preregistered`, `effect_size` (`measure`, `correction`, `direction`), `include`
(`stage` and a filter-language `filter`), `model` (`type`, `tau2_estimator`,
`ci_method`, `level`), `dependency` (`handling`, `cluster`, `rho`,
`small_sample_correction`), `moderators`, `heterogeneity`, `publication_bias`,
`sensitivity`, `plots`, and `seed`. Analyses with `preregistered: false` MUST be
labelled exploratory in all generated output.

_Source: `docs/spec/08-analysis.md` §2_

#### Scenario: Exploratory analysis

- **GIVEN** `analysis/sensitivity-rct-only.yaml` with `preregistered: false`
- **WHEN** its results and any prose are generated
- **THEN** every output labels the analysis exploratory

### Requirement: Running analyses

`strata analyze [<id>] [--all]` MUST run analysis specifications and write
`analysis/results/<id>/` (`estimates.json`, `studies.tsv`, plots, `summary.md`,
`run.json`). `strata analyze --check` MUST validate specifications and report
guardrails without computing. Results MUST be committed only when the user runs
`strata analyze` deliberately, never as a side effect of another command.

_Source: `docs/spec/10-cli.md` §2; `docs/spec/02-repository-format.md` §2; `docs/spec/16-open-questions.md` Q4_

#### Scenario: Screening does not rerun analyses

- **WHEN** screening decisions are committed
- **THEN** `analysis/results/` is not modified, and `strata status` reports the analysis as stale

### Requirement: Guardrails

`strata analyze` MUST emit each of these as a named warning, suppressible only
with an acknowledgement, recorded in `run.json`:

| Condition | Warning |
|---|---|
| `k < 3` | Random-effects pooling is not meaningful; report studies individually |
| `k < 5` | `tau^2` is very poorly estimated; prefer Paule–Mandel or Knapp–Hartung and interpret `I2` with great caution |
| `k < 10` | Publication-bias tests are underpowered (blocked by default) |
| `k/p < 10` in meta-regression | Overfitting risk |
| Clusters `< 20` with cluster-robust SEs | Small-sample df; report the Satterthwaite df |
| Any study with `> 1` effect and `handling: none` | Dependence ignored |
| Any effect derived from a p-value | Lowest-quality conversion |
| Any effect using an assumed correlation | State the assumption in the manuscript |
| `I2 > 75%` | Consider whether pooling is appropriate at all |
| Analysis not marked `preregistered` | Will be reported as exploratory |

A blocking guardrail MUST exit with code 8 unless `--force` is given, and a
forced bypass MUST be recorded in `run.json`.

_Source: `docs/spec/08-analysis.md` §8; `docs/spec/10-cli.md` §1; `docs/spec/16-open-questions.md` Q5_

#### Scenario: Two studies

- **WHEN** a random-effects analysis runs with `k = 2`
- **THEN** the `k < 3` and `k < 5` warnings are emitted and recorded in `run.json`

#### Scenario: Forced bias test

- **WHEN** an analysis with `k = 7` requests Egger's test with `--force`
- **THEN** the test runs, its output is labelled as forced, and `run.json` records the bypass

### Requirement: Reproducibility record

`analysis/results/<id>/run.json` MUST record the analysis id, `strata` version,
engine, schema version, `input_digest`, input counts and criteria version,
seed, dependency and platform versions, warnings, conventions used, and the
commit it was generated from. `input_digest` MUST hash the canonical
serialisation of the exact effect rows and options fed to the estimator, so
`strata verify` can distinguish "stale because the data changed" from "stale
because the tool changed". Given the same repository at the same commit,
`strata analyze` MUST produce byte-identical output on any platform.

_Source: `docs/spec/08-analysis.md` §9_

#### Scenario: Data changed

- **GIVEN** committed results for `primary`
- **WHEN** an included study's extraction changes
- **THEN** the recomputed `input_digest` differs and `strata verify` reports that the analysis is stale because its data changed
