# Design: Analysis

## Context

`strata` is written in Python, which is weak for meta-analysis compared with R.
The gap is closed by validation, not by reimplementing R: every estimator is
checked against `metafor` fixtures and published worked examples, and
`metafor` is also available as an optional engine (`architecture` spec). The formulae
are in the delta specs; their sources are listed below.

## Goals / Non-Goals

**Goals:**

- Every estimator matches `metafor` to 1e-8 (1e-6 for iterative `tau^2`).
- Byte-identical results and plots across platforms.
- Guardrails that make bad practice deliberate rather than silent.

**Non-Goals:**

- Selection models, p-curve, p-uniform* (post-1.0).
- GLMM for proportions, network meta-analysis, Bayesian models (export to R).
- Describing any method as "correcting for publication bias".

## Decisions

- **Trustworthy before comprehensive.** A model `strata` cannot compute
  correctly is absent, not approximated; `strata export effects` is the path to
  R.
- **Defaults follow current best practice, not tradition**: REML `tau^2`,
  Knapp–Hartung intervals for random effects (with `metafor`'s ad hoc
  truncation), cluster-robust CR2 when any study contributes multiple effects,
  and never common-effect by default.
- **Conventions are named in output** (`variance_convention: "LS"`, prediction
  interval df `k-2`, HK truncation) so a reader can reproduce them elsewhere.
- **Assumptions are recorded and swept automatically**: an assumed pre-post
  correlation triggers a sensitivity sweep over r in {0.3, 0.5, 0.7}; `rho` for
  dependent effects over {0.2, 0.5, 0.8}.
- **Guardrails block with `--force` always available and always logged** in
  `run.json` (Q5 in [docs/open-questions.md](../../../docs/open-questions.md)).
- **Hand-written SVG** rather than matplotlib, for determinism.

## Risks / Trade-offs

- Convention mismatches with `metafor` each take time to run down; the
  milestone should be budgeted generously rather than compressed.
- Where `strata` deliberately differs from `metafor` (prediction-interval df),
  fixtures must pin `metafor`'s matching option explicitly; a silent tolerance
  bump is forbidden.

## Reference: an analysis specification

```yaml
id: "primary"
title: "Effect of spaced practice on delayed recall"
preregistered: true

effect_size:
  measure: "SMD"
  correction: "hedges"
  direction: "higher-is-better"

include:
  stage: "included"
  filter: "outcome == 'recall' and timepoint_hours >= 24"

model:
  type: "random-effects"
  tau2_estimator: "REML"
  ci_method: "knapp-hartung"
  level: 0.95

dependency:
  handling: "cluster-robust"
  cluster: "study_id"
  rho: 0.60
  small_sample_correction: "CR2"

moderators:
  - {name: "mean_age", type: "continuous", centering: "mean"}
  - {name: "design", type: "categorical", reference: "rct"}

heterogeneity: ["Q", "I2", "tau2", "H2", "prediction_interval"]
publication_bias: ["funnel", "egger", "begg", "trim_fill", "pet_peese"]

sensitivity:
  - {id: "loo", type: "leave_one_out"}
  - {id: "influence", type: "influence_diagnostics"}
  - {id: "low-rob", type: "subset", filter: "rob_overall == 'low'"}
  - {id: "no-pval-derived", type: "subset", filter: "not derived_from_pvalue"}

plots: ["forest", "funnel", "baujat", "bubble"]
seed: 20260911
```

## Reference: `run.json`

```json
{
  "analysis": "primary",
  "strata_version": "0.4.1",
  "engine": "native",
  "schema_version": 1,
  "input_digest": "sha256:...",
  "inputs": {"studies": 38, "effects": 61, "criteria_version": 4},
  "seed": 20260911,
  "dependencies": {"numpy": "2.1.3", "scipy": "1.14.1"},
  "platform": {"python": "3.12.4"},
  "warnings": ["dependence:cluster-robust:clusters=23"],
  "conventions": {"variance": "LS", "pi_df": "k-2", "hk_truncation": true},
  "generated_from_commit": "4f1a2b9"
}
```

## Reference: sources for conventions

- SMD variance: `metafor::escalc(measure="SMD")`, `vtype="LS"`; Hedges & Olkin
  (1985) for `g` and the exact small-sample correction.
- Zero cells: Haldane–Anscombe 0.5 correction; double-zero studies excluded from
  ratio measures and counted.
- Freeman–Tukey back-transformation instability: Schwarzer et al. (2019).
- `d` from log OR: Chinn (2000), `d = logOR * sqrt(3)/pi` (opt-in, flagged).
- Knapp–Hartung intervals with `metafor`'s ad hoc truncation.
- Prediction interval df `k-2`: Higgins, Thompson & Spiegelhalter; IntHout et
  al. (2016). `metafor::predict()` defaults to `k-p`, so fixtures pin it.
- Cluster-robust inference: CR2 with Satterthwaite df (Tipton 2015;
  Pustejovsky & Tipton 2021); the CHE working model as the default for
  dependent effects.
- Aggregation within study: Borenstein et al.
- Small-study tests: Egger; Harbord or Peters for log OR; Begg; Duval & Tweedie
  trim-and-fill (sensitivity only); PET-PEESE. Cochrane guidance against
  asymmetry tests below 10 studies.
- Influence cutoffs follow `metafor` (`|rstudent| > 1.96`, Cook's D > 0.45,
  `hat > 3/k`).
- Validation datasets: BCG vaccine (Colditz et al. 1994); Borenstein, Hedges,
  Higgins & Rothstein, *Introduction to Meta-Analysis*; a Cochrane review with
  published RevMan output for zero-cell OR and RR.

## Reference: why common-effect is never the default

Its assumption — every study estimates exactly the same parameter — is almost
never defensible in the social and health sciences, and defaults in this field
are sticky. The prediction interval is shown on every random-effects forest
plot because it answers the question practitioners actually have ("what should I
expect in a new setting?"), which the confidence interval does not.
