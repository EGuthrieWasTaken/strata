# effect-sizes Specification

## Purpose

Computing effect sizes and their variances from extracted inputs, and
converting between reported statistics, with every convention and conversion
named in the output so the numbers can be reproduced elsewhere. Group 1 is
treatment/experimental, group 2 is control/comparison; all logs are natural.

## ADDED Requirements

### Requirement: Standardised mean difference

`SMD` MUST be computed as:

```
s_pooled = sqrt( ((n1-1)*sd1^2 + (n2-1)*sd2^2) / (n1+n2-2) )
d        = (m1 - m2) / s_pooled
df       = n1 + n2 - 2
J        = 1 - 3/(4*df - 1)
g        = J * d
var(g)   = 1/n1 + 1/n2 + g^2 / (2*(n1+n2))
```

matching `metafor::escalc(measure="SMD")` with `vtype="LS"`, and the output MUST
record `variance_convention: "LS"`. `J` MUST use the exact gamma form
`Γ(df/2) / (sqrt(df/2) * Γ((df-1)/2))` when `df < 10`, MAY use the
approximation otherwise, and MUST report which was used. Increasing `m1` with
all else fixed MUST increase `d`, and increasing `n` MUST decrease `v`.

_Source: `docs/spec/08-analysis.md` §3.1; property P12 in `docs/spec/14-testing.md` §2_

#### Scenario: Small sample

- **WHEN** an SMD is computed with `n1 = n2 = 4` (`df = 6`)
- **THEN** `J` uses the exact gamma form and the output says so

### Requirement: Raw mean difference

`MD` MUST be computed as `yi = m1 - m2`, `vi = sd1^2/n1 + sd2^2/n2`.

_Source: `docs/spec/08-analysis.md` §3.2_

#### Scenario: Raw difference

- **WHEN** `m1 = 10, m2 = 8, sd1 = sd2 = 2, n1 = n2 = 4`
- **THEN** `yi = 2` and `vi = 2`

### Requirement: Ratios from a 2x2 table

With `a = events1`, `b = n1 - events1`, `c = events2`, `d = n2 - events2`:

```
log odds ratio   yi = log(a*d / (b*c))          vi = 1/a + 1/b + 1/c + 1/d
log risk ratio   yi = log((a/n1) / (c/n2))      vi = 1/a - 1/n1 + 1/c - 1/n2
risk difference  yi = a/n1 - c/n2               vi = a*b/n1^3 + c*d/n2^3
```

If any cell is zero, 0.5 MUST be added to all four cells for OR and RR and
`continuity_correction: 0.5` recorded on the effect. A study with zero events in
both arms MUST be excluded from ratio analyses, and the number excluded MUST be
reported.

_Source: `docs/spec/08-analysis.md` §3.3_

#### Scenario: One zero cell

- **WHEN** a log OR is computed with `a = 0`
- **THEN** 0.5 is added to every cell and the effect records `continuity_correction: 0.5`

#### Scenario: Double-zero study

- **WHEN** a study has zero events in both arms in a log RR analysis
- **THEN** it is excluded and the report counts it among excluded double-zero studies

### Requirement: Correlations, hazard ratios, and proportions

- `ZCOR`: `yi = atanh(r)`, `vi = 1/(n-3)`, back-transformed to `r` (`tanh`) for
  display with the transformation named.
- Hazard ratios: `yi = log(HR)`, `se = (log(ci_hi) - log(ci_lo)) / (2 * z_{(1+L)/2})`, `vi = se^2`.
- Proportions: logit `yi = log(p/(1-p))`, `vi = 1/(n*p) + 1/(n*(1-p))`;
  Freeman–Tukey `yi = asin(sqrt(x/(n+1))) + asin(sqrt((x+1)/(n+1)))`,
  `vi = 1/(n+0.5)`. `strata` MUST warn when Freeman–Tukey is used with a
  sample-size ratio above 10 and SHOULD default to logit.

`r = 1` and `n <= 3` for `ZCOR` MUST produce a specific error, never `NaN` or
`inf`.

_Source: `docs/spec/08-analysis.md` §3.4–§3.6; `docs/spec/14-testing.md` §4.3_

#### Scenario: Perfect correlation

- **WHEN** a correlation effect with `r = 1` is computed
- **THEN** a specific error explains that Fisher's z is undefined

#### Scenario: Unstable Freeman–Tukey

- **WHEN** Freeman–Tukey is used with study sizes 20 and 400
- **THEN** a warning about back-transformation instability is emitted

### Requirement: Pre-post designs require an explicit correlation

`SMCR` MUST be computed as `yi = J * (m_post - m_pre) / sd_pre`,
`vi = 2*(1 - r)/n + yi^2/(2*n)`. `r` MUST be supplied explicitly and recorded on
the effect as `assumed_correlation` when assumed, and whenever any effect uses
an assumed value a sensitivity analysis over r in {0.3, 0.5, 0.7} MUST be run
automatically.

_Source: `docs/spec/08-analysis.md` §3.7_

#### Scenario: Missing correlation

- **WHEN** a pre-post effect is entered without `r`
- **THEN** it cannot be computed until an assumed value is supplied

#### Scenario: Assumed correlation

- **WHEN** an analysis includes an effect with `assumed_correlation: 0.5`
- **THEN** results at r = 0.3, 0.5, and 0.7 are reported

### Requirement: Conversions between reported statistics

`strata` MUST convert to `d` from `t, n1, n2` (`d = t * sqrt(1/n1 + 1/n2)`),
from `F(1, df)` (`t = sqrt(F)`), from `r, n` (`d = 2r / sqrt(1 - r^2)`), and from
a two-tailed `p, n1, n2, direction` (`t = quantile_t(1 - p/2, n1+n2-2)`, signed).
Every converted effect MUST record `derived_from`, and p-value conversions MUST
additionally set `derived_from_pvalue: true`. Conversion between `d` and log OR
(`d = logOR * sqrt(3)/pi`) MUST be opt-in per effect and flagged.

_Source: `docs/spec/08-analysis.md` §3.8_

#### Scenario: Effect from a t statistic

- **WHEN** an effect is entered as `t = 2.5, n1 = 30, n2 = 30`
- **THEN** its `d` is computed and the effect records `derived_from: "t"`

#### Scenario: Effect from a p-value

- **WHEN** an effect is entered from a p-value only
- **THEN** it records `derived_from_pvalue: true` and the p-value guardrail fires
