# Statistical methods

The formulae, conventions and sources behind `strata analyze`, for methods sections and for anyone checking the numbers. For *how to run* an analysis see [Analysis](Analysis).

What `strata analyze` computes, with the formulae and where each one comes from. The normative text is
the OpenSpec capabilities `effect-sizes`, `pooling-models` and `bias-and-sensitivity`; the code is
`src/strata/stats/`. `metafor` (Viechtbauer 2010, *J Stat Softw* 36(3)) is the reference
implementation: every estimator is checked against committed `metafor` output
(`tests/statistical/`, relative tolerance 1e-8, and 1e-6 for the iterative `tau^2` estimators), and
where strata differs on purpose the difference is listed under [Conventions](#conventions-that-differ-from-common-defaults).
This page is a reference for methods sections, not a tutorial; for how the repository records an analysis
see [`m4-plan.md`](https://github.com/EGuthrieWasTaken/strata/blob/main/docs/m4-plan.md).

Notation: `yi` is a study's effect estimate, `vi` its sampling variance, `k` the number of effects,
`p` the number of model coefficients (1 for a pooled mean), `tau^2` the between-study variance,
`wi = 1/(vi + tau^2)`. Every log is natural. Group 1 is the experimental group, group 2 the control.

## Effect sizes (`stats/escalc.py`)

| Measure | `yi` | `vi` | Source and notes |
|---|---|---|---|
| Mean difference, `MD` | `m1 - m2` | `sd1^2/n1 + sd2^2/n2` | |
| Standardised mean difference, `SMD` (Hedges' g) | `J * (m1 - m2) / sd_pooled` | `1/n1 + 1/n2 + g^2 / (2 (n1 + n2))` | Hedges (1981); `sd_pooled = sqrt(((n1-1)sd1^2 + (n2-1)sd2^2)/(n1+n2-2))`; the variance is `metafor`'s `vtype = "LS"` |
| Hedges' correction `J` | `Γ(df/2) / (sqrt(df/2) Γ((df-1)/2))`, `df = n1 + n2 - 2` | | always the exact gamma form, never `1 - 3/(4 df - 1)`; the result records `j_form` |
| Log odds ratio, `logOR` | `log(ad/bc)` | `1/a + 1/b + 1/c + 1/d` | `a, b` events and non-events in group 1, `c, d` in group 2 |
| Log risk ratio, `logRR` | `log((a/n1)/(c/n2))` | `1/a - 1/n1 + 1/c - 1/n2` | |
| Risk difference, `RD` | `a/n1 - c/n2` | `ab/n1^3 + cd/n2^3` | no continuity correction; a study with zero variance is excluded, with the reason shown |
| Fisher's z, `ZCOR` | `atanh(r)` | `1/(n - 3)` | pooled values are back-transformed with `tanh` |
| Log hazard ratio, `logHR` | `log(HR)` | `((log(hi) - log(lo)) / (2 z))^2` | the SE recovered from the reported confidence interval (Parmar et al. 1998) |
| Logit proportion, `PLO` | `log(p/(1-p))` | `1/(n p) + 1/(n (1-p))` | `metafor` "PLO"; back-transformed with the inverse logit |
| Freeman–Tukey proportion, `PFT` | `asin(sqrt(x/(n+1))) + asin(sqrt((x+1)/(n+1)))` | `1/(n + 0.5)` | Freeman & Tukey (1950); this is `metafor`'s "PFT" with `yi` doubled, so `vi` is four times `metafor`'s; Miller's (1978) back-transformation with the harmonic mean of the sizes; a warning when the largest study is over ten times the smallest (Schwarzer et al. 2019) |
| Standardised mean change, `SMCR` | `J * (m_post - m_pre) / sd_pre`, `df = n - 1` | `2(1 - r)/n + yi^2/(2n)` | Becker (1988); `r`, the pre-post correlation, is never defaulted, and a sweep over `r = 0.3, 0.5, 0.7` runs automatically |

**Zero cells.** When any cell of a 2×2 table is zero, 0.5 is added to all four cells (and recorded as
`continuity_correction`); a double-zero study is flagged `double_zero`. For `PLO`, 0.5 is added to the events
and non-events when the proportion is 0 or 1. Mantel–Haenszel and Peto estimators, which need no correction,
are not implemented.

**Conversions** (each records what it was converted from, and opt-in conversions are marked): `d` from a
t statistic, `d = t sqrt(1/n1 + 1/n2)`; from a 1-df F, `t = sqrt(F)` signed by a stated direction; from a
correlation, `d = 2r / sqrt(1 - r^2)` (equal groups assumed); from a 2×2 chi-square, `phi = sqrt(chi2/n)`
then as a correlation; from a two-tailed p, `t = t_{1 - p/2, n1 + n2 - 2}` signed by a stated direction; `sd`
from a standard error, `se sqrt(n)`, or from a confidence interval with the t distribution on `n - 1` df;
`d <-> logOR` by `d = logOR sqrt(3)/pi` (Chinn 2000; the result is an uncorrected `d`, not Hedges' g).

## Pooling (`stats/models.py`)

**Common-effect model**: `mu = sum(w_i yi) / sum(w_i)` with `w_i = 1/vi`.

**Random-effects model**: the same with `w_i = 1/(vi + tau^2)`. `tau^2` estimators (negative values are
set to zero; a non-convergent iterative estimator is an error, never the last iterate):

| Code | Estimator | Source |
|---|---|---|
| `DL` | `(Q - (k - p)) / trace(P)` | DerSimonian & Laird (1986) |
| `HE` | `(sum(e_i^2) - sum(vi (1 - h_i))) / (k - p)`, `e_i` the unweighted residuals, `h_i` the hat values | Hedges (1983) |
| `HS` | `(Q - k) / sum(1/vi)` | Hunter & Schmidt (2004) |
| `SJ` | `t0 * RSS / (k - p)` with weights `1/(vi + t0)`, `t0 = var(y)(k-1)/k` | Sidik & Jonkman (2005) |
| `ML`, `REML` | maximum likelihood, restricted maximum likelihood (Fisher scoring from the HE value, at most 200 iterations, tolerance 1e-10) | Viechtbauer (2005) |
| `EB` | empirical Bayes | Morris (1983), Berkey et al. (1995) |
| `PM` | the `tau^2` at which the generalised Q equals `k - p` | Paule & Mandel (1982) |

REML is the default. A likelihood at zero above the iterate's means a local maximum, and `tau^2` is set to
zero (`metafor`'s guard).

**Intervals**: `wald` uses `mu ± z * se`. `knapp-hartung` (the default) multiplies the variance by the
weighted residual mean square `RSS_w / (k - p)`, uses `t` on `k - p` df (Knapp & Hartung 2003), and, as
`metafor`'s `test = "adhoc"`, never lets the standard error fall below the Wald one; the run records
`hk_truncation` and the `hk-truncation` warning fires when it did. It needs `k > p`.

**Heterogeneity**: `Q = sum(w_i (yi - mu)^2)` with `w_i = 1/vi`, `p`-value from `chi^2` on `k - p` df;
`I^2 = max(0, (Q - df)/Q)` and `H^2 = Q/df` (Higgins & Thompson 2002) for every `tau^2` estimator;
`tau^2` and `tau` come with a Q-profile confidence interval (Viechtbauer 2007).

**Prediction interval**: `mu ± t_{k-2} sqrt(tau^2 + se^2)` (Higgins, Thompson & Spiegelhalter 2009; Riley et
al. 2011), for `k >= 3`.

**Meta-regression**: weighted least squares with `W = diag(1/(vi + tau^2))`, one `tau^2` estimated from the
residual heterogeneity; moderators are centred and reference levels recorded; it refuses when `k <= p`
and warns when `k / p < 10`.

## Dependent effects (`stats/robust.py`)

A study with several effects can be handled four ways (`handling:` in the analysis specification):

- `aggregate`: one effect per study, `y = mean(y_i)`, `v = (sum v_i + sum_{i != j} rho sqrt(v_i v_j)) / m^2`
  (Borenstein et al. 2009, ch. 24), with `rho` swept over 0.3, 0.5, 0.7.
- `multilevel`: the correlated-and-hierarchical-effects (CHE) working model, REML, with study and effect random effects
  and sampling errors correlated at `rho` (Pustejovsky & Tipton 2022).
- `cluster-robust`: CR2 cluster-robust standard errors with Satterthwaite degrees of freedom, as
  `clubSandwich` (Pustejovsky & Tipton 2018); fewer than 20 clusters warns and fewer than 10 warns strongly,
  naming the degrees of freedom.
- `none`: pooled as independent, firing the `dependence-ignored` warning.

## Small-study effects and sensitivity (`stats/bias.py`, `stats/diagnostics.py`)

None of these corrects for publication bias; each result says what it measured. Egger (or Harbord), Begg
and PET-PEESE are refused below ten studies unless forced (guardrail `k-lt-10-bias-tests`, exit code 8), and a
forced result is labelled underpowered wherever it appears; trim-and-fill is a sensitivity analysis and is not
held to that rule.

- **Egger's regression** (Egger et al. 1997): the effect on its standard error, weights `1/v`, `t` on `k - 2` df,
  as `metafor::regtest`; **PET** and **PEESE** (Stanley & Doucouliagos 2014) are the same regression on the
  standard error and the variance, PEESE used when the one-tailed PET test is significant.
- **Harbord** (2006) and **Peters** (2006): tests for log odds ratios (`Z / sqrt(V)` on `sqrt(V)`; `ln(OR)` on
  `1/n` with weights `m1 m0 / n`), checked against the same regressions written out in R. For a `logOR`
  analysis the `egger` option runs Harbord's test (the result says so); Peters' test is implemented in
  `stats/bias.py` but the analysis specification does not select it.
- **Begg's rank correlation** (Begg & Mazumdar 1994); an all-tied input is a specific error, not `NaN`.
- **Trim-and-fill** (Duval & Tweedie 2000) with the `L0`, `R0` and `Q0` estimators of `metafor::trimfill`;
  a sensitivity analysis only. On a funnel with no spread in precision it refuses.
- **Leave-one-out, influence diagnostics** (externally standardised residual, DFFITS, Cook's distance,
  covariance ratio, leave-one-out `tau^2` and `I^2`; Viechtbauer & Cheung 2010), **cumulative** and
  **subset** analyses.

## Conventions that differ from common defaults

- `I^2` and `H^2` are Q-based for every `tau^2` estimator; `metafor` prints a `tau^2`-based `I^2` for REML and
  others (92.22% against 92.12% for the BCG trials).
- The prediction interval uses `t` on `k - 2` df; `metafor`'s `predict()` uses the normal quantile by default.
- `knapp-hartung` is `metafor`'s `adhoc` form (variance factor truncated at 1), not the untruncated original.
- The Hedges correction is the exact gamma function, not an approximation.
- Freeman–Tukey `yi` is twice `metafor`'s "PFT" (so `vi` is four times).

## What is not here

Network meta-analysis, diagnostic-accuracy and dose–response models, three-level models beyond the CHE
working model, Mantel–Haenszel and Peto pooling, and an `engine: metafor` that runs R (`strata export effects`
writes the data for `metafor`). The published examples reproduced are Borenstein et al. (2009), the BCG
trials (Viechtbauer 2010), Raudenbush (1985) and the Niel-Weise et al. (2007) zero-cell trials; **Hedges &
Olkin (1985) is not**, because its tables could not be obtained here.

## Sources

Becker (1988) *Br J Math Stat Psychol* 41; Begg & Mazumdar (1994) *Biometrics* 50; Berkey et al. (1995) *Stat
Med* 14; Borenstein et al. (2009) *Introduction to Meta-Analysis*; Chinn (2000) *Stat Med* 19; DerSimonian &
Laird (1986) *Control Clin Trials* 7; Duval & Tweedie (2000) *Biometrics* 56; Egger et al. (1997) *BMJ* 315;
Freeman & Tukey (1950) *Ann Math Stat* 21; Harbord et al. (2006) *Stat Med* 25; Hedges (1981) *J Educ Stat* 6;
Hedges (1983) *Psychol Bull* 93; Higgins & Thompson (2002) *Stat Med* 21; Higgins, Thompson & Spiegelhalter
(2009) *J R Stat Soc A* 172; Hunter & Schmidt (2004) *Methods of Meta-Analysis*; Knapp & Hartung (2003) *Stat
Med* 22; Miller (1978) *Am Stat* 32; Morris (1983) *J Am Stat Assoc* 78; Parmar et al. (1998) *Stat Med* 17;
Paule & Mandel (1982) *J Res Natl Bur Stand* 87; Peters et al. (2006) *JAMA* 295; Pustejovsky & Tipton (2018)
*J Bus Econ Stat* 36; Pustejovsky & Tipton (2022) *Prev Sci* 23; Riley et al. (2011) *BMJ* 342; Schwarzer et al.
(2019) *Res Synth Methods* 10; Sidik & Jonkman (2005) *J Stat Plan Inference* 129; Stanley & Doucouliagos (2014)
*Res Synth Methods* 5; Viechtbauer (2005) *J Educ Behav Stat* 30; Viechtbauer (2007) *Stat Med* 26; Viechtbauer
(2010) *J Stat Softw* 36; Viechtbauer & Cheung (2010) *Res Synth Methods* 1.
