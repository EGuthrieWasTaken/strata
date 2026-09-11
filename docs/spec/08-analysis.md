# 08 — Analysis *(normative)*

## 1. Posture

`strata` must be *trustworthy* before it is *comprehensive*. A meta-analysis tool
that is subtly wrong is worse than no tool, because its output looks
authoritative and lands in the published literature.

Therefore:

- Every estimator in this document MUST be validated numerically against
  `metafor` to a relative tolerance of 1e-8 on the fixture datasets in
  [14 §4](14-testing.md). Where `metafor` and another reference disagree,
  `metafor`'s convention is authoritative and the difference MUST be documented.
- Any model `strata` cannot compute correctly MUST be absent, not approximated.
  `strata export effects` exists so the user can go to R.
- Guardrails (§8) are not optional polish. Meta-analysis is notoriously easy to
  do wrongly with small `k`, and the tool should say so at the point of use.

## 2. The analysis specification

Analyses are declarative files, so that an analysis is a versioned, reviewable,
diffable artefact rather than a sequence of button presses.

```yaml
# analysis/primary.yaml
id: "primary"
title: "Effect of spaced practice on delayed recall"
preregistered: true

effect_size:
  measure: "SMD"                  # see §3
  correction: "hedges"            # none | hedges
  direction: "higher-is-better"

include:
  stage: "included"
  filter: "outcome == 'recall' and timepoint_hours >= 24"

model:
  type: "random-effects"          # fixed-effect | random-effects | meta-regression
  tau2_estimator: "REML"          # DL | HE | HS | SJ | ML | REML | EB | PM
  ci_method: "knapp-hartung"      # wald | knapp-hartung
  level: 0.95

dependency:
  handling: "cluster-robust"      # none | aggregate | cluster-robust | multilevel
  cluster: "study_id"
  rho: 0.60                       # assumed within-study correlation
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

`preregistered: false` analyses MUST be labelled exploratory in all generated
output. The distinction between confirmatory and exploratory analysis is a
methodological commitment, and the tool should carry it rather than leave it to
the author's memory at writing time.

## 3. Effect size computation *(normative)*

Notation: group 1 is treatment/experimental, group 2 is control/comparison.
All logs are natural.

### 3.1 Standardised mean difference (`SMD`)

```
s_pooled = sqrt( ((n1-1)*sd1^2 + (n2-1)*sd2^2) / (n1+n2-2) )
d        = (m1 - m2) / s_pooled
df       = n1 + n2 - 2
J        = 1 - 3/(4*df - 1)                     # Hedges' small-sample correction
g        = J * d
var(g)   = 1/n1 + 1/n2 + g^2 / (2*(n1+n2))
```

The variance uses `g` rather than `d`, matching `metafor::escalc(measure="SMD")`
with its default `vtype="LS"`. The alternative convention `var(g) = J^2 * var(d)`
differs trivially but would break byte-comparison against the reference; the
choice MUST be documented in output metadata as `variance_convention: "LS"`.

`J` MUST be computed via the exact gamma-function form
`J = Γ(df/2) / (sqrt(df/2) * Γ((df-1)/2))` when `df < 10`, where the
`1 - 3/(4df-1)` approximation is least accurate, and MAY use the approximation
above that threshold. Report which was used.

### 3.2 Raw mean difference (`MD`)

```
yi = m1 - m2
vi = sd1^2/n1 + sd2^2/n2
```

### 3.3 Ratios from a 2x2 table

With `a = events1`, `b = n1 - events1`, `c = events2`, `d = n2 - events2`:

```
log odds ratio   yi = log(a*d / (b*c))          vi = 1/a + 1/b + 1/c + 1/d
log risk ratio   yi = log((a/n1) / (c/n2))      vi = 1/a - 1/n1 + 1/c - 1/n2
risk difference  yi = a/n1 - c/n2               vi = a*b/n1^3 + c*d/n2^3
```

**Zero cells.** If any of `a, b, c, d` is zero, add `0.5` to all four cells
(Haldane–Anscombe) for OR and RR, and record `continuity_correction: 0.5` on
that effect. If both arms have zero events, the study contributes no information
to a ratio measure and MUST be excluded from the ratio analysis with a reported
count — silently including it with an invented correction is a known source of
bias. `strata` MUST report the number of studies so excluded.

### 3.4 Correlations (`ZCOR`)

```
yi = atanh(r) = 0.5 * log((1+r)/(1-r))
vi = 1/(n-3)
```

Results MUST be back-transformed to `r` for display (`tanh`), with the
transformation named in the output.

### 3.5 Hazard ratios

From a reported HR with a confidence interval at level `L`:

```
yi = log(HR)
se = (log(ci_hi) - log(ci_lo)) / (2 * z_{(1+L)/2})
vi = se^2
```

### 3.6 Proportions

```
logit          yi = log(p/(1-p))                vi = 1/(n*p) + 1/(n*(1-p))
Freeman-Tukey  yi = asin(sqrt(x/(n+1))) + asin(sqrt((x+1)/(n+1)))
               vi = 1/(n+0.5)
```

Freeman–Tukey double-arcsine back-transformation is unstable when study sizes
vary widely (Schwarzer et al. 2019). `strata` MUST warn when it is used with a
sample-size ratio above 10 and SHOULD default to logit with a random-effects
model (GLMM is out of scope for v1).

### 3.7 Within-subject / pre-post designs

```
SMCR (change vs raw pre-test SD, correlation r required)
  yi = J * (m_post - m_pre) / sd_pre
  vi = 2*(1 - r)/n + yi^2/(2*n)
```

`r` is rarely reported. `strata` MUST require an explicit assumed value, record it
on the effect as `assumed_correlation`, and automatically include a sensitivity
analysis over `r` in {0.3, 0.5, 0.7} whenever any effect uses an assumed value.
Quietly defaulting to 0.5 and never mentioning it is a common and consequential
practice this tool should not make easy.

### 3.8 Conversions between reported statistics

| From | To `d` |
|---|---|
| `t`, `n1`, `n2` | `d = t * sqrt(1/n1 + 1/n2)` |
| `F(1, df)` | `t = sqrt(F)`, then as above |
| `r`, `n` | `d = 2r / sqrt(1 - r^2)` |
| `p` (two-tailed), `n1`, `n2`, direction | `t = quantile_t(1 - p/2, n1+n2-2)`, signed, then as above |

Every converted effect MUST be flagged with the conversion used
(`derived_from: "t"`), and conversions from a p-value alone MUST additionally set
`derived_from_pvalue: true` so the sensitivity analysis in §2 can exclude them.

Converting between `d` and `log OR` (Chinn 2000: `d = logOR * sqrt(3)/pi`) is
supported but MUST be opt-in per effect and flagged, because mixing measures is
a judgement call the reader must be told about.

## 4. Pooling models *(normative)*

### 4.1 Fixed-effect (common-effect)

```
w_i  = 1/v_i
mu   = sum(w_i * y_i) / sum(w_i)
var  = 1 / sum(w_i)
```

`strata` MUST call this "common-effect" in output, with "fixed-effect" as an alias,
and MUST NOT select it by default. Its assumption — that every study estimates
exactly the same parameter — is almost never defensible in the social and health
sciences, and defaults in this field are sticky.

### 4.2 Random-effects

```
w*_i = 1/(v_i + tau^2)
mu   = sum(w*_i * y_i) / sum(w*_i)
var  = 1 / sum(w*_i)
```

Required `tau^2` estimators: DerSimonian–Laird (`DL`), Hedges (`HE`),
Hunter–Schmidt (`HS`), Sidik–Jonkman (`SJ`), maximum likelihood (`ML`),
restricted maximum likelihood (`REML`, **default**), empirical Bayes (`EB`), and
Paule–Mandel (`PM`).

```
DL:  tau^2 = max(0, (Q - (k-1)) / C),   C = sum(w_i) - sum(w_i^2)/sum(w_i)
```

`ML`/`REML` MUST be fitted by Fisher scoring with a step-halving fallback,
convergence tolerance 1e-10, maximum 200 iterations. Non-convergence is an error
reported to the user, never a silently returned last iterate.

### 4.3 Confidence intervals

- `wald`: `mu +/- z_{(1+L)/2} * sqrt(var)`.
- `knapp-hartung` (**default** for random-effects): inflate the variance by the
  weighted residual mean square and use a `t` distribution with `k-1` df:

```
s2   = sum(w*_i * (y_i - mu)^2) / (k - 1)
se   = sqrt(s2 / sum(w*_i))
CI   = mu +/- t_{k-1, (1+L)/2} * se
```

Knapp–Hartung maintains nominal coverage far better than Wald with small `k`,
which is the regime almost every real meta-analysis is in. `strata` MUST apply the
`ad hoc` truncation used by `metafor` (never let the HK standard error fall below
the Wald standard error) and MUST document that it does.

### 4.4 Heterogeneity

```
Q   = sum(w_i * (y_i - mu_FE)^2),  df = k - 1,  p from chi-square
I2  = max(0, (Q - df)/Q) * 100
H2  = Q / df
```

Report `tau^2` with a confidence interval (Q-profile method), and `tau` on the
effect-size scale, which is far more interpretable than `I2` and should be shown
first in generated prose.

**Prediction interval** (Higgins–Thompson–Spiegelhalter / IntHout et al.):

```
PI = mu +/- t_{k-2, (1+L)/2} * sqrt(tau^2 + var(mu))
```

Requires `k >= 3`. The `k-2` degrees of freedom follow IntHout et al. (2016);
`metafor::predict()` uses the model's `k-p` df by default, so the comparison
fixture MUST pin `metafor`'s option explicitly and the output MUST name the
convention used.

The prediction interval SHOULD be displayed on every forest plot of a
random-effects model. It answers the question clinicians and practitioners
actually have ("what should I expect in a new setting?"), which the confidence
interval does not.

### 4.5 Meta-regression

Weighted least squares with `W = diag(1/(v_i + tau^2))`, `tau^2` estimated from
the residual heterogeneity under the specified estimator:

```
beta   = (X'WX)^-1 X'Wy
Var    = (X'WX)^-1                     # or the HK-adjusted / cluster-robust form
Q_E    = residual heterogeneity, df = k - p
Q_M    = omnibus test of the moderators, df = p - 1
R2     = max(0, (tau2_null - tau2_model) / tau2_null) * 100
```

Categorical moderators are dummy-coded against the declared reference level.
Continuous moderators are mean-centred when `centering: mean`, and the centring
constant MUST be reported so coefficients are interpretable.

`strata` MUST warn when `k / p < 10` — the conventional minimum of about ten
studies per covariate — and MUST refuse to fit when `k <= p`.

## 5. Dependent effect sizes *(normative)*

One study reporting three outcomes contributes three statistically dependent
estimates. Ignoring this understates standard errors, sometimes badly. `strata`
MUST NOT allow it to happen silently: if any `study_id` contributes more than one
effect and `dependency.handling == "none"`, the analysis MUST emit a prominent
warning naming the affected studies.

| Handling | Method |
|---|---|
| `none` | Treat effects as independent. Permitted, warned about. |
| `aggregate` | Average effects within study first, using the assumed correlation `rho` to compute the aggregate variance (Borenstein et al.). Simple, defensible, loses within-study moderators. |
| `cluster-robust` | Fit the model ignoring dependence, then compute cluster-robust (sandwich) standard errors clustered on `study_id`, with the CR2 small-sample correction and Satterthwaite degrees of freedom (Tipton 2015; Pustejovsky & Tipton 2021). **Recommended default when any study contributes multiple effects.** |
| `multilevel` | Three-level model with random effects at study and effect level. |

The correlated-hierarchical-effects (CHE) working model — a multilevel model with
a compound-symmetric within-study correlation `rho`, combined with CR2
cluster-robust inference — is the current best-practice default and is what
`cluster-robust` SHOULD implement.

`rho` is an assumption, not data. `strata` MUST require it explicitly, record it in
the results, and run the analysis at `rho` in {0.2, 0.5, 0.8} as an automatic
sensitivity check.

**Cluster-count guardrail.** Cluster-robust inference is unreliable with few
clusters. `strata` MUST warn below 20 clusters and warn strongly below 10, naming
the Satterthwaite df actually achieved.

## 6. Publication bias and small-study effects

| Method | Notes |
|---|---|
| Funnel plot | Standard error on a reversed y-axis; contour-enhanced shading at p = .10, .05, .01 SHOULD be the default, because it separates "asymmetry from publication bias" from "asymmetry from heterogeneity" far better than a bare funnel |
| Egger's regression | Regress `y_i/se_i` on `1/se_i`; test the intercept. For non-SMD measures use the precision form; for log OR use Harbord's or Peters' test, since Egger's is miscalibrated there |
| Begg's rank correlation | Kendall's tau between standardised effect and variance; low power, included for completeness |
| Trim and fill | Duval & Tweedie; `L0` default, `R0` and `Q0` available. MUST be presented as a sensitivity analysis, never as a bias-corrected estimate |
| PET-PEESE | PET: WLS of `y` on `se`; PEESE: on `v`. Conditional estimator selects PEESE when PET's one-tailed intercept test has p < .10 |
| Selection models | Vevea–Hedges three-parameter selection model — **v2** |
| p-curve / p-uniform* | **v2** |

**Guardrail.** Tests for funnel-plot asymmetry are underpowered and prone to
false positives with fewer than 10 studies; Cochrane recommends against them
below that threshold. `strata` MUST refuse to compute Egger/Begg/PET-PEESE with
`k < 10` unless `--force` is given, and MUST label the result accordingly when
forced.

`strata` MUST NOT describe any of these as "correcting for publication bias".
Generated prose MUST use language such as "consistent with small-study effects",
since asymmetry has several possible causes.

## 7. Sensitivity analysis and diagnostics

| Analysis | Output |
|---|---|
| Leave-one-out | Refit `k` times; report each omitted study's effect on `mu`, `tau^2`, and `I2` |
| Influence diagnostics | Externally standardised residuals, DFFITS, Cook's distance, covariance ratio, leave-one-out `tau^2` and `Q_E`, hat values |
| Baujat plot | Contribution to heterogeneity (x) against influence on the pooled estimate (y) |
| Subset analyses | Any `filter` expression from §2 |
| Cumulative meta-analysis | Ordered by year (or any moderator); shows when the evidence stabilised |

Influence diagnostics MUST flag studies exceeding conventional cutoffs
(`|rstudent| > 1.96`, `Cook's D > 0.45` per `metafor`'s convention, `hat > 3/k`)
but MUST NOT remove anything automatically. Outlier removal is a substantive
decision that belongs in a declared sensitivity analysis with a rationale.

## 8. Guardrails *(normative)*

`strata analyze` MUST emit these, each as a named, suppressible-with-acknowledgement
warning recorded in `run.json`:

| Condition | Warning |
|---|---|
| `k < 3` | Random-effects pooling is not meaningful; report studies individually |
| `k < 5` | `tau^2` is very poorly estimated; prefer Paule–Mandel or Knapp–Hartung, and interpret `I2` with great caution |
| `k < 10` | Publication-bias tests are underpowered (blocked by default, §6) |
| `k/p < 10` in meta-regression | Overfitting risk |
| Clusters `< 20` with cluster-robust SEs | Small-sample df; report the Satterthwaite df |
| Any study with `> 1` effect and `handling: none` | Dependence ignored |
| Any effect derived from a p-value | Lowest-quality conversion; check the sensitivity analysis |
| Any effect using an assumed correlation | State the assumption in the manuscript |
| `I2 > 75%` | Consider whether pooling is appropriate at all |
| Analysis not marked `preregistered` | Will be reported as exploratory |

## 9. Reproducibility *(normative)*

`analysis/results/<id>/run.json` MUST record:

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

`input_digest` is a hash over the canonical serialisation of the exact effect
rows and options fed to the estimator — not over the whole repository — so that
`strata verify` can tell "the analysis is stale because the data changed" apart
from "the analysis is stale because the tool changed".

Given the same repository at the same commit, `strata analyze` MUST produce
byte-identical output on any platform ([02 §5.5](02-repository-format.md)).

## 10. Plots

SVG output, deterministic, theme-aware (light and dark), colour-blind-safe
palettes, and never relying on colour alone to convey a distinction.

**Forest plot** MUST show: study label, `n`, the effect estimate and CI
numerically, the plotted estimate with CI, the weight, a diamond for the pooled
estimate, the prediction interval as a distinct band, and a heterogeneity
footer (`k`, `tau`, `I2`, `Q`, `p`). Subgroup rows when a categorical moderator
is specified.

**Funnel plot** MUST default to contour-enhanced, with the pooled estimate and
pseudo-confidence contours marked.

**Bubble plot** for continuous moderators: effect against moderator, bubble area
proportional to weight, fitted line with a confidence band.

Every plot MUST have a `--format svg|pdf|png` option and MUST be accompanied by
the underlying values in `studies.tsv`, so the user can rebuild it elsewhere.
