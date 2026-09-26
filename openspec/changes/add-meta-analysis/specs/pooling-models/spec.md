# pooling-models Specification

## Purpose

Pooling effect sizes: common-effect and random-effects models, `tau^2`
estimators, confidence and prediction intervals, heterogeneity statistics,
meta-regression, and correct handling of statistically dependent effects.

## ADDED Requirements

### Requirement: Common-effect model is never the default

The common-effect model MUST be computed as `w_i = 1/v_i`,
`mu = sum(w_i * y_i) / sum(w_i)`, `var = 1 / sum(w_i)`, MUST be called
"common-effect" in output (with "fixed-effect" as an alias), and MUST NOT be
selected by default.

#### Scenario: Model type omitted

- **WHEN** an analysis file omits `model.type`
- **THEN** a random-effects model is fitted, not a common-effect model

### Requirement: Random-effects model and tau-squared estimators

The random-effects model MUST use `w*_i = 1/(v_i + tau^2)`. The `tau^2`
estimators DerSimonian–Laird (`DL`), Hedges (`HE`), Hunter–Schmidt (`HS`),
Sidik–Jonkman (`SJ`), `ML`, `REML` (default), empirical Bayes (`EB`), and
Paule–Mandel (`PM`) MUST be available. `ML`/`REML` MUST be fitted by Fisher
scoring with a step-halving fallback, tolerance 1e-10, and at most 200
iterations; non-convergence MUST be reported as an error, never a silently
returned last iterate. Results MUST match `metafor` to 1e-8 (1e-6 for iterative
estimators).

#### Scenario: Non-convergence

- **WHEN** REML fails to converge within 200 iterations
- **THEN** `strata analyze` reports an error naming the estimator rather than returning an estimate

#### Scenario: DerSimonian–Laird at zero

- **WHEN** `Q < k - 1`
- **THEN** the DL estimate of `tau^2` is 0

### Requirement: Confidence intervals

`wald` intervals MUST be `mu ± z_{(1+L)/2} * sqrt(var)`. `knapp-hartung` (the
default for random effects) MUST inflate the variance by the weighted residual
mean square with a `t` distribution on `k-1` df, and MUST apply `metafor`'s ad
hoc truncation (the HK standard error never falls below the Wald standard
error), documenting that it does.

#### Scenario: Truncation applies

- **WHEN** the Knapp–Hartung standard error would be smaller than the Wald standard error
- **THEN** the Wald standard error is used and the output records `hk_truncation: true`

### Requirement: Heterogeneity and prediction intervals

`strata` MUST report `Q` (with df and chi-square p), `I2 = max(0, (Q - df)/Q) * 100`,
`H2 = Q / df`, `tau^2` with a Q-profile confidence interval, and `tau` on the
effect-size scale, shown first in generated prose. The prediction interval MUST
be `mu ± t_{k-2, (1+L)/2} * sqrt(tau^2 + var(mu))`, requires `k >= 3`, and the
output MUST name the `k-2` df convention. The prediction interval SHOULD appear
on every random-effects forest plot.

#### Scenario: Too few studies for a prediction interval

- **WHEN** a random-effects model is fitted with `k = 2`
- **THEN** no prediction interval is reported and the reason is stated

### Requirement: Meta-regression

Meta-regression MUST use weighted least squares with `W = diag(1/(v_i + tau^2))`
and report coefficients, `Q_E` (df `k - p`), `Q_M` (df `p - 1`), and `R2`.
Categorical moderators MUST be dummy-coded against the declared reference;
continuous moderators with `centering: mean` MUST be mean-centred and the
centring constant reported. `strata` MUST warn when `k / p < 10` and MUST refuse
to fit when `k <= p`.

#### Scenario: More parameters than studies

- **WHEN** a meta-regression with 6 parameters is requested on 6 studies
- **THEN** the fit is refused

### Requirement: Dependent effect sizes are never ignored silently

If any `study_id` contributes more than one effect and
`dependency.handling == "none"`, the analysis MUST emit a prominent warning
naming the affected studies. The handlings `none`, `aggregate` (Borenstein et
al. with assumed `rho`), `cluster-robust` (sandwich SEs clustered on `study_id`
with CR2 and Satterthwaite df; SHOULD implement the CHE working model), and
`multilevel` (three-level) MUST be available. `rho` MUST be supplied
explicitly, recorded in results, and swept over {0.2, 0.5, 0.8} automatically.
`strata` MUST warn below 20 clusters and warn strongly below 10, naming the
Satterthwaite df achieved.

#### Scenario: Multiple outcomes per study with no handling

- **GIVEN** a study contributing three effects and `handling: none`
- **WHEN** the analysis runs
- **THEN** a prominent warning names that study

#### Scenario: Few clusters

- **WHEN** a cluster-robust analysis has 8 clusters
- **THEN** a strong warning reports the Satterthwaite df
