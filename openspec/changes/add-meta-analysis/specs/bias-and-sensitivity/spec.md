# bias-and-sensitivity Specification

## Purpose

Assessing small-study effects and the robustness of pooled estimates:
publication-bias methods with an underpowering guardrail and honest language,
leave-one-out and subset analyses, cumulative meta-analysis, and influence
diagnostics that flag but never remove.

## ADDED Requirements

### Requirement: Publication-bias and small-study methods

`strata` MUST provide: a funnel plot (contour-enhanced at p = .10, .05, .01 by
default); Egger's regression (with Harbord's or Peters' test for log OR);
Begg's rank correlation; Duval & Tweedie trim-and-fill (`L0` default, `R0` and
`Q0` available), presented only as a sensitivity analysis and never as a
bias-corrected estimate; and PET-PEESE (PEESE selected when PET's one-tailed
intercept test has p < .10).

_Source: `docs/spec/08-analysis.md` §6_

#### Scenario: Log odds ratio analysis

- **WHEN** a small-study test is requested for a log OR analysis
- **THEN** Harbord's or Peters' test is used rather than Egger's

#### Scenario: Trim and fill

- **WHEN** trim-and-fill is reported
- **THEN** it is labelled a sensitivity analysis, not a corrected estimate

### Requirement: Underpowered tests are blocked by default

`strata` MUST refuse to compute Egger, Begg, or PET-PEESE with `k < 10` unless
`--force` is given, and MUST label forced results accordingly.

_Source: `docs/spec/08-analysis.md` §6_

#### Scenario: Seven studies

- **WHEN** Egger's test is requested with `k = 7` without `--force`
- **THEN** it is refused with exit code 8 and an explanation citing the underpowering

### Requirement: No "correction" language

`strata` MUST NOT describe any method as correcting for publication bias;
generated prose MUST use language such as "consistent with small-study effects".

_Source: `docs/spec/08-analysis.md` §6_

#### Scenario: Asymmetric funnel

- **WHEN** Egger's test indicates asymmetry
- **THEN** generated prose describes the result as consistent with small-study effects

### Requirement: Sensitivity analyses and diagnostics

`strata` MUST provide leave-one-out (effect of each omitted study on `mu`,
`tau^2`, and `I2`), influence diagnostics (externally standardised residuals,
DFFITS, Cook's distance, covariance ratio, leave-one-out `tau^2` and `Q_E`, hat
values), subset analyses by any filter expression, and cumulative
meta-analysis ordered by year or any moderator. Influence diagnostics MUST flag
studies exceeding `|rstudent| > 1.96`, `Cook's D > 0.45`, or `hat > 3/k`, and
MUST NOT remove anything automatically.

_Source: `docs/spec/08-analysis.md` §7_

#### Scenario: Influential study

- **WHEN** a study's Cook's distance is 0.6
- **THEN** it is flagged in the diagnostics and remains in the pooled estimate
