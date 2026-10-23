# M4 ("Analysis") — implementation notes

A working note for whoever picks up the work after M4, modelled on
[`m3-plan.md`](m3-plan.md). The normative text is the OpenSpec change
`add-meta-analysis` (and, once archived, the specs it merges into:
`analysis-specification`, `effect-sizes`, `pooling-models`, `bias-and-sensitivity`,
`analysis-plots`, plus additions to `cli` and `web-ui`). This file records what was built, the
conventions that emerged, and what is deliberately partial.

## Status

| Group | What | Status |
|---|---|---|
| 1 | Analysis specification (`analysis/<id>.yaml`, JSON Schema), `strata analyze [<id>] [--all] [--check]`, `analysis/results/<id>/`, `run.json` with `input_digest`, exploratory labelling | done |
| 2 | `stats/escalc.py`: SMD, MD, log OR / RR, RD, ZCOR, log HR, logit and Freeman–Tukey proportions, SMCR with the r sweep, conversions from t, F, r, chi-square and p; 100% branch coverage | done |
| 3 | `stats/models.py`: common-effect and random-effects pooling, eight `tau^2` estimators, Wald and Knapp–Hartung (ad hoc truncation), Q / I² / H², Q-profile CI, prediction interval, meta-regression with the `k/p` guard | done |
| 3 | `stats/robust.py`: aggregation, CHE multilevel model, cluster-robust CR2 with Satterthwaite df, the `rho` sweep | done |
| 4 | `stats/bias.py` and `stats/diagnostics.py`: Egger, Peters, Harbord, Begg, trim-and-fill, PET-PEESE, leave-one-out, influence diagnostics, cumulative, subset analyses | done |
| 5 | `stats/canvas.py` and `analysis/plots.py`: deterministic SVG (and PDF) forest, funnel (contour-enhanced), Baujat and bubble plots with `studies.tsv`; fourteen named guardrails | done |
| 6 | CLI `--json`; `/analysis` and `/analysis/<id>` web screens; `strata diff <ref>..<ref>`; analyses in `strata status` and `strata verify` | done |
| 7 | `metafor` / `clubSandwich` fixtures and generator, published worked examples, edge cases, P12, golden plots, guardrail tests, nightly drift job | done, with the caveats below |

### Partial or deliberately left for later

- **Worked examples.** The Borenstein et al. (2009) six-study example, the BCG trials
  (Viechtbauer 2010), Raudenbush (1985) and the Niel-Weise et al. (2007) zero-cell trials are
  reproduced (`tests/statistical/test_published_examples.py`). **Hedges & Olkin (1985) is not**: its
  tables could not be obtained, so no number from it is asserted. The zero-cell example asserts
  behaviour (which trials are corrected, which is double-zero, the direction and plausibility of the
  pooled odds ratio), not a published pooled value.
- **Cross-platform byte identity** is asserted by comparing the plots with committed files
  (`tests/golden/plots/`) on every platform in the CI matrix, and across hash seeds locally. It has
  been run on Linux only; the first CI run on macOS and Windows is the real check. `run.json` records
  the Python, numpy and scipy versions, so it is byte-identical only for the same versions; the
  estimates, the study table and the plots do not depend on them.
- **The nightly drift job** installs the current `metafor`, `clubSandwich` and `mvtnorm` from the
  Posit package mirror, regenerates the fixtures into a scratch directory and fails when a number
  moves by more than 1e-9 relative (`tests/statistical/compare_fixtures.py`). It has not run on
  GitHub yet; the same steps were run here against `metafor` 4.4.0.
- **PNG output** needs the optional `cairosvg` package; without it `--plot-format png` is a specific
  error that suggests SVG or PDF.
- **`strata report` plots.** Robvis-style risk-of-bias plots are M5.
- **Models that are absent, not approximated**: Mantel–Haenszel and Peto, network meta-analysis,
  diagnostic-accuracy and dose–response models, three-level models beyond the CHE working model.
  `strata export effects` writes the data for `metafor` (`engine: metafor` is not implemented).
- **Trim-and-fill** matches `metafor` for L0, R0 and Q0 wherever `metafor` returns a result. On
  some datasets (`egger2001_logor`) `metafor`'s own Q0 fails; strata refuses with a specific error
  and the case is tested as such rather than compared.

## Conventions established

Everything in [`m1-plan.md`](m1-plan.md), [`m2-plan.md`](m2-plan.md) and [`m3-plan.md`](m3-plan.md)
still applies. Additions:

- **`metafor` is authoritative.** Every estimator is compared with committed JSON fixtures generated
  by `tests/statistical/generate.R` (relative tolerance 1e-8, 1e-6 for iterative `tau^2`
  estimators). Where strata deliberately differs, the generator pins the matching option and says
  why. The differences a reader will notice:
  - `I²` and `H²` are Q-based, `(Q - df) / Q`, for every `tau^2` estimator; `metafor` prints a
    `tau^2`-based `I²` for REML and others (92.22% against 92.12% for the BCG trials).
  - The prediction interval uses a *t* distribution on `k - 2` degrees of freedom (Riley et al.);
    `metafor`'s `predict()` uses the normal quantile by default.
  - `ci_method: knapp-hartung` is `metafor`'s `test = "adhoc"`: the variance factor is truncated at
    1, and the run records `hk_truncation` and fires the `hk-truncation` warning.
  - The Hedges correction is always the exact gamma-function form, not the `1 - 3/(4 df - 1)`
    approximation.
  - Freeman–Tukey proportions follow `metafor`'s `PFT` times two in `yi` (so `vi` is four times
    larger); the risk difference gets no zero correction.
- **Dependence.** A study with several effects is handled by aggregation (Borenstein's unweighted
  mean with the compound-symmetry variance), by the CHE working model (study and effect random
  effects, correlated sampling errors at `rho`, REML) or by cluster-robust CR2 with Satterthwaite
  df, matching `clubSandwich`. `handling: none` pools them as independent and fires
  `dependence-ignored`. The `rho` sweep (0.3, 0.5, 0.7) and the pre-post `r` sweep are automatic.
- **Guardrails are named, acknowledgeable and recorded.** Fourteen codes (`guardrails.CODES`); only
  `k-lt-10-bias-tests` blocks (exit code 8) and only `--force` bypasses it. `--ack CODE` marks a
  warning acknowledged in `run.json`; a forced test is labelled underpowered everywhere.
- **Results are written only on a deliberate `strata analyze`.** Nothing else touches
  `analysis/results/`. `input_digest` is a SHA-256 over the canonical serialisation of the exact
  effect rows and options, so `strata verify` and `strata status` can tell *stale-data* from
  *stale-tool* (a different strata version).
- **Plots are drawn by the tool, not a library.** `stats/canvas.py` writes SVG with
  content-derived ids and numbers formatted by one function, light and dark themes through CSS
  variables on classes, the Okabe–Ito palette, and shapes and dashes so that no distinction rests on
  colour. The web UI serves them from `/analysis/<id>/plots/<name>` with their own Content Security
  Policy (an inline stylesheet and nothing else); every page keeps the strict policy.
- **`strata diff`** exports each commit with `git archive` (no checkout, no index) and folds it with
  the same code `strata status` uses, so a number in the diff is the number the dashboard would have
  shown there. The pooled-estimate line reads each side's committed `estimates.json`.
- **Degenerate input is a specific error, never `NaN`.** A single dominant weight that swamps double
  precision, an all-tied Begg test, trim-and-fill on a funnel with no spread in precision, and a
  risk-difference study with zero variance (excluded, with the reason shown) are all named.
- **New extraction design.** `single-group-proportion` (`events`, `n`, `measure` PLO or PFT) was added
  so proportion analyses are reachable from entered data rather than only from `precomputed` effects.
