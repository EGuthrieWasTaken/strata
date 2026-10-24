# Analysis

An **analysis** is a small, versioned file in `analysis/` that says *what to pool and how*. `strata analyze`
turns it into committed results: estimates, a per-study table, a plain-language summary, deterministic plots
and a record of the exact inputs. Results are written **only when you run `strata analyze`**, never as a side
effect of anything else, and the same repository at the same commit gives byte-identical output on any
computer.

## A first analysis

Create `analysis/primary.yaml`:

```yaml
id: primary
title: Effect of spaced practice on delayed recall
preregistered: true
effect_size:
  measure: SMD
model:
  type: random-effects
  tau2_estimator: REML
  ci_method: knapp-hartung
heterogeneity: [Q, I2, tau2, prediction_interval]
sensitivity:
- id: leave-one-out
  type: leave_one_out
plots: [forest, funnel]
```

Check it, then run it:

```
strata analyze --check
strata --why "Primary analysis, as pre-specified" analyze primary --ack k-lt-5
```

```
primary (preregistered): SMD 0.476 [0.147, 0.805], 4 studies, 4 effects
  hk-truncation: The Knapp-Hartung standard error was truncated to the Wald standard error
(metafor's ad hoc rule).
```

Everything lands in `analysis/results/primary/`:

| File | Contents |
|---|---|
| `summary.md` | A plain-language paragraph: the pooled estimate and interval, heterogeneity, the prediction interval, warnings and the conventions used |
| `estimates.json` | Every number: coefficients, heterogeneity with its confidence intervals, sensitivity results, bias tests |
| `studies.tsv` | One row per effect: `yi`, `vi`, `se`, its interval, its weight |
| `plots/*.svg` | The requested plots (forest, funnel, Baujat, bubble); `--plot-format pdf` or `png` for others |
| `run.json` | The reproducibility record: tool version, input digest, counts, criteria version, conventions, warnings and acknowledgements, and the commit |

An excerpt of the generated `summary.md`:

> Across 4 studies (4 effects), the pooled SMD was 0.476 (95% CI 0.147 to 0.805). Between-study heterogeneity:
> tau = 0.000 (tau^2 = 0.000), I^2 = 0.0%, Q(3) = 0.224, p = 0.9736. The 95% prediction interval, where a new
> study's true effect is expected to fall, is 0.031 to 0.920 (t distribution on k-2 degrees of freedom).

## The specification file

Only `id`, `title` and `effect_size.measure` are required; the rest have defaults.

| Section | Choices |
|---|---|
| `preregistered` | `true` or `false`. An analysis that is not preregistered is labelled **exploratory** in every output it feeds |
| `effect_size.measure` | `SMD`, `MD`, `logOR`, `logRR`, `RD`, `ZCOR` (correlations, back-transformed for display), `PLO` and `PFT` (proportions), `logHR`, `SMCR` (standardised mean change). Also `correction: hedges\|none` and `direction: higher-is-better\|lower-is-better` |
| `include.filter` | Which effects to pool: a [filter](Filter-Language), e.g. `rob_overall != 'high'` to leave out studies at high risk of bias |
| `model.type` | `random-effects` (default), `common-effect` (or `fixed-effect`) |
| `model.tau2_estimator` | `DL`, `HE`, `HS`, `SJ`, `ML`, `REML` (default), `EB`, `PM` |
| `model.ci_method` | `knapp-hartung` (default) or `wald`. `model.level` is the confidence level (0.95) |
| `dependency` | What to do when one study contributes several effects (below) |
| `moderators` | Meta-regression terms: `{name, type: continuous\|categorical, centering: mean\|none, reference}` |
| `heterogeneity` | any of `Q`, `I2`, `tau2`, `H2`, `prediction_interval` |
| `publication_bias` | any of `funnel`, `egger`, `begg`, `trim_fill`, `pet_peese` (trim-and-fill and PET-PEESE are reported as *sensitivity* analyses, not corrections) |
| `sensitivity` | a list of `{id, type}` with `type`: `leave_one_out`, `influence_diagnostics`, `cumulative` (with `order`), `subset` (with a `filter`) |
| `plots` | `forest`, `funnel`, `baujat`, `bubble` (effect against a continuous moderator) |
| `seed` | for any resampling |

### Effects that share a study

If a study contributes more than one effect (several outcomes, timepoints, or subgroups) treating them as
independent overstates your certainty. `dependency.handling` chooses:

| `handling` | Does |
|---|---|
| `none` | pools them as if independent. A guardrail warns (`dependence-ignored`) and the warning goes into the generated text |
| `aggregate` | combines each study's effects into one, with an assumed correlation `rho` |
| `cluster-robust` | keeps all effects and corrects the standard errors for clustering (small-sample CR2 correction, Satterthwaite df); few clusters trigger a warning |
| `multilevel` | a three-level model with effects nested in studies |

Any assumed within-study correlation (`rho`) is a guardrail too: state it in the manuscript. The statistics
are on [Statistical methods](Statistical-Methods).

## Guardrails

`strata` warns, by name, about conditions that make results fragile. A warning **never blocks silently**; you
acknowledge it with `--ack NAME` and the acknowledgement is recorded in `run.json` and reported in the
generated text. Some are *blocking* (exit code 8) unless you pass `--force`, and then the result is
labelled as forced.

| Name | When |
|---|---|
| `k-lt-3` | fewer than 3 studies: pooling is not meaningful; report them individually |
| `k-lt-5` | fewer than 5: `tau^2` is very poorly estimated, interpret `I^2` with great caution |
| `k-lt-10-bias-tests` | fewer than 10 studies: publication-bias tests are underpowered. **Blocked** unless `--force` |
| `meta-regression-overfitting` | fewer than 10 studies per moderator coefficient |
| `cluster-robust:few-clusters` | fewer than 20 clusters with cluster-robust SEs (and a stronger warning for very few) |
| `dependence-ignored` | a study has several effects and `handling: none` |
| `p-value-derived` | an effect was derived from a p-value (the weakest conversion) |
| `assumed-correlation` | an effect used an assumed correlation |
| `high-heterogeneity` | `I^2` above 75%: consider whether pooling is appropriate |
| `exploratory` | the analysis is not marked `preregistered` |
| `freeman-tukey-instability` | studies of very different sizes with the Freeman-Tukey transform |
| `double-zero-excluded` | double-zero studies dropped from a binary analysis |
| `hk-truncation` | the Knapp-Hartung standard error was truncated to the Wald one (`metafor`'s rule) |

For example, asking for Egger's test on four studies:

```
strata analyze primary
```

```
blocked (k-lt-10-bias-tests): Egger's test is underpowered with 4 studies (fewer than 10): the test
cannot tell small-study effects from chance, so it is refused; use --force to compute it anyway (the
result is then labelled underpowered)
```

`strata analyze --check` reports the guardrails for every specification without computing anything: run it
whenever you change a file.

## Keeping results honest

- **Stale results.** Results record a digest of their exact inputs. If screening, extraction or a spec changes
  an input, `strata status` reports the analysis **stale** (and `strata verify` says whether the data or the tool
  changed). Screening never re-runs an analysis; run `strata analyze` when you decide to.
- **What moved.** `strata diff v1-protocol..HEAD` shows the pooled estimate before and after changes to the
  protocol.
- **Validated or absent.** Every estimator is compared with R's `metafor` (and `clubSandwich` for cluster-robust
  errors) to a relative tolerance of 1e-8 on committed fixtures. A model `strata` cannot compute correctly is
  *refused*, not approximated; the error suggests `strata export effects` to take the data to R.
- **Several analyses.** Keep the pre-specified one (`preregistered: true`) apart from sensitivity analyses
  (`preregistered: false`, labelled exploratory in the text), and run them all with `strata analyze --all`.

## Taking the data elsewhere

`strata export effects --format csv --out effects.csv` writes one row per effect, loadable directly with
`metafor::rma(yi, vi, data = read.csv("effects.csv"))`, so you can cross-check any result in R.

Next: [Reporting](Reporting).
