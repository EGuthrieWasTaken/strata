# Tasks

## 1. Analysis specification and runs

- [x] 1.1 Ship the JSON Schema for `analysis/<id>.yaml`
- [x] 1.2 Implement `strata analyze [<id>] [--all]` writing `analysis/results/<id>/`
- [x] 1.3 Implement `strata analyze --check` (validate specs and report guardrails without computing)
- [x] 1.4 Write `run.json` with `input_digest` over the exact effect rows and options
- [x] 1.5 Label non-preregistered analyses exploratory everywhere

## 2. Effect sizes (`stats/escalc.py`, 100% branch coverage)

- [x] 2.1 SMD with exact-J for `df < 10`, MD, log OR / log RR / RD with zero-cell handling
- [x] 2.2 ZCOR with back-transformation, hazard ratios from CIs, logit and Freeman–Tukey proportions
- [x] 2.3 SMCR with required assumed correlation and automatic sensitivity sweep
- [x] 2.4 Conversions from t, F, r, and p-values with `derived_from` / `derived_from_pvalue` flags

## 3. Pooling models

- [x] 3.1 Common-effect and random-effects pooling
- [x] 3.2 `tau^2` estimators DL, HE, HS, SJ, ML, REML, EB, PM (Fisher scoring with step-halving for ML/REML)
- [x] 3.3 Wald and Knapp–Hartung intervals with ad hoc truncation
- [x] 3.4 Q, I2, H2, `tau^2` Q-profile CI, prediction interval
- [x] 3.5 Meta-regression with dummy coding, centring, and the `k/p` guard
- [x] 3.6 Dependent effects: aggregate, cluster-robust CR2 (CHE), multilevel, with `rho` sweep and cluster-count guardrail

## 4. Bias, sensitivity, diagnostics

- [x] 4.1 Funnel (contour-enhanced), Egger (with Harbord/Peters for log OR), Begg, trim-and-fill, PET-PEESE with the `k < 10` guardrail
- [x] 4.2 Leave-one-out, influence diagnostics with flagging, cumulative meta-analysis, subset analyses

## 5. Plots and guardrails

- [x] 5.1 Deterministic SVG forest, funnel, Baujat, and bubble plots with `studies.tsv`
- [x] 5.2 Implement every guardrail as a named, acknowledgeable warning recorded in `run.json`

## 6. Surfaces

- [x] 6.1 Add the analysis CLI commands and `--json` output
- [x] 6.2 Add the `/analysis/<id>` web screen
- [x] 6.3 Show pooled-estimate changes in `strata diff`

## 7. Tests (suite additions, docs/roadmap.md M4)

- [x] 7.1 The full `metafor` fixture set and generator script; the nightly live-R drift job
- [ ] 7.2 Published worked examples (BCG, Borenstein et al., Hedges & Olkin, a Cochrane zero-cell review)
- [x] 7.3 Every numerical edge case produces a correct value or a specific error
- [x] 7.4 Property test P12 (effect-size monotonicity)
- [x] 7.5 Byte-identical plot comparison across platforms
- [x] 7.6 A test that every guardrail fires and that `--force` bypasses and records it

## Notes

- 7.2 is open: the Borenstein et al., BCG, Raudenbush and Niel-Weise (zero-cell) examples are
  reproduced, but the Hedges & Olkin worked tables could not be obtained, and the zero-cell review
  asserts behaviour rather than a published pooled value. Close it with those sources or drop the
  items by editing this task.
- 7.1 and 7.5 are implemented and were run on Linux; the nightly live-R job and the macOS and
  Windows byte-identity runs happen on GitHub, not here.
- 5.1: PNG output needs the optional `cairosvg` package; SVG and PDF are built in. `run.json`
  records the Python, numpy and scipy versions, so it is byte-identical only for the same versions.
