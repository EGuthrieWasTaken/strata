# Tasks

## 1. Analysis specification and runs

- [ ] 1.1 Ship the JSON Schema for `analysis/<id>.yaml`
- [ ] 1.2 Implement `strata analyze [<id>] [--all]` writing `analysis/results/<id>/`
- [ ] 1.3 Implement `strata analyze --check` (validate specs and report guardrails without computing)
- [ ] 1.4 Write `run.json` with `input_digest` over the exact effect rows and options
- [ ] 1.5 Label non-preregistered analyses exploratory everywhere

## 2. Effect sizes (`stats/escalc.py`, 100% branch coverage)

- [ ] 2.1 SMD with exact-J for `df < 10`, MD, log OR / log RR / RD with zero-cell handling
- [ ] 2.2 ZCOR with back-transformation, hazard ratios from CIs, logit and Freeman–Tukey proportions
- [ ] 2.3 SMCR with required assumed correlation and automatic sensitivity sweep
- [ ] 2.4 Conversions from t, F, r, and p-values with `derived_from` / `derived_from_pvalue` flags

## 3. Pooling models

- [ ] 3.1 Common-effect and random-effects pooling
- [ ] 3.2 `tau^2` estimators DL, HE, HS, SJ, ML, REML, EB, PM (Fisher scoring with step-halving for ML/REML)
- [ ] 3.3 Wald and Knapp–Hartung intervals with ad hoc truncation
- [ ] 3.4 Q, I2, H2, `tau^2` Q-profile CI, prediction interval
- [ ] 3.5 Meta-regression with dummy coding, centring, and the `k/p` guard
- [ ] 3.6 Dependent effects: aggregate, cluster-robust CR2 (CHE), multilevel, with `rho` sweep and cluster-count guardrail

## 4. Bias, sensitivity, diagnostics

- [ ] 4.1 Funnel (contour-enhanced), Egger (with Harbord/Peters for log OR), Begg, trim-and-fill, PET-PEESE with the `k < 10` guardrail
- [ ] 4.2 Leave-one-out, influence diagnostics with flagging, cumulative meta-analysis, subset analyses

## 5. Plots and guardrails

- [ ] 5.1 Deterministic SVG forest, funnel, Baujat, and bubble plots with `studies.tsv`
- [ ] 5.2 Implement every guardrail as a named, acknowledgeable warning recorded in `run.json`

## 6. Surfaces

- [ ] 6.1 Add the analysis CLI commands and `--json` output
- [ ] 6.2 Add the `/analysis/<id>` web screen
- [ ] 6.3 Show pooled-estimate changes in `strata diff`

## 7. Tests (suite additions, `docs/spec/15-roadmap.md` M4)

- [ ] 7.1 The full `metafor` fixture set and generator script; the nightly live-R drift job
- [ ] 7.2 Published worked examples (BCG, Borenstein et al., Hedges & Olkin, a Cochrane zero-cell review)
- [ ] 7.3 Every numerical edge case produces a correct value or a specific error
- [ ] 7.4 Property test P12 (effect-size monotonicity)
- [ ] 7.5 Byte-identical plot comparison across platforms
- [ ] 7.6 A test that every guardrail fires and that `--force` bypasses and records it
