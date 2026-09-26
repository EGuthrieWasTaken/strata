# Design: Analysis

## Context

`strata` is written in Python, which is weak for meta-analysis compared with R.
The gap is closed by validation, not by reimplementing R: every estimator is
checked against `metafor` fixtures and published worked examples, and
`metafor` is also available as an optional engine (`architecture` spec). Full
formulae and their sources are in `docs/spec/08-analysis.md`.

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
  `run.json` (`docs/spec/16-open-questions.md` Q5).
- **Hand-written SVG** rather than matplotlib, for determinism.

## Risks / Trade-offs

- Convention mismatches with `metafor` each take time to run down; the
  milestone should be budgeted generously rather than compressed.
- Where `strata` deliberately differs from `metafor` (prediction-interval df),
  fixtures must pin `metafor`'s matching option explicitly; a silent tolerance
  bump is forbidden.
