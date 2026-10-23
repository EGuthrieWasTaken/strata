# Design: data-extraction

*Informative, but several decisions are load-bearing.* The requirements are in
[spec.md](spec.md).

## Every value can answer "where did this number come from?"

A value is stored with a `source` locator (page, table, paragraph). The CLI form
accepts `value @ source`; the web form has a source input beside every field. In
dual mode, a disagreement is reconciled against the two reviewers' locators, so the
person resolving it can open the PDF at the right place.

## Adding a required field makes extractions incomplete, not stale

Staleness is for decisions that a protocol change may have invalidated. A new
required field invalidates nothing already recorded; it just leaves a gap.
`strata extract --missing` queues the gap and `strata status` counts it, rather than
throwing away completed work.

## Quantities are stored as entered and as normalised

"1 week" alone is unanalysable; 168 hours alone is unverifiable against the paper.
The record keeps both (`value: 168, unit: hours, entered: "1 week"`). Conversions
use a small registry of units per dimension (time, mass, length, dose) that a
project can extend; an unknown unit is `E_UNIT`, never a silent guess.

## Effects are entered in whatever form the paper reports

Means with SD, SE or a confidence interval; a 2x2 table; a correlation; a *t*, *F* or
chi-square; a bare *p*-value; a pre-post change; a hazard ratio with its interval;
a single-group proportion; or a pre-computed effect. The tool computes the effect
size and shows it as you type, following `metafor`'s conventions, and records which
conversion produced it (`derived_from`) so an effect derived from a *p*-value alone,
the lowest-quality route, can be flagged downstream.

## Guards warn, never block

Six guards (`sd-outlier`, `large-effect`, `zero-cell`, `n-inconsistent`, `p-derived`,
`stat-p-inconsistent`, the last a GRIM/statcheck-style comparison of a reported test
statistic with its *p*-value) produce warnings. A warning that a reviewer has examined is acknowledged with a
recorded note, so it is auditable and does not recur. Blocking would push reviewers
to enter a different number to get past a check; warning keeps the true value and
the doubt both on record.

## Reconciliation is a recorded decision

In dual mode each reviewer's work is in `by-reviewer/<handle>/` and the agreed
result in `consensus/`. Reconciling a field writes both a `reconcile` event naming
the chosen value and the reason and the consensus file, so the agreement rate and
every override are reconstructible from the log.

## Example

```
$ strata extract --reconcile std_7x2k9m1p3v5r8t0w

  Cepeda et al. (2008)                       11 fields, 2 disagreements

  n_total            ethan 148     sam 148       agree
  design             ethan rct     sam rct       agree
  retention_interval ethan 168 h   sam 24 h      DISAGREE
      ethan: "p. 1097 -- 1 week retention interval"
      sam:   "Table 2 -- the 1-day condition"
      [1] ethan   [2] sam   [o] other value   [?] open the PDF
```

`extraction/schema.yaml`:

```yaml
version: 2
fields:
  - name: "n_total"
    label: "Total analysed N"
    type: integer
    required: true
    min: 1
  - name: "retention_interval"
    label: "Retention interval"
    type: quantity
    unit: "hours"
    accepts_units: ["minutes", "hours", "days", "weeks"]
    required: true
effects:
  outcome_field: "outcome"
  outcomes: ["recall", "recognition", "transfer"]
  designs:
    - id: "two-group-means"
      requires: ["n1", "m1", "sd1", "n2", "m2", "sd2"]
    - id: "single-group-proportion"
      requires: ["events", "n"]
    - id: "precomputed"
      requires: ["yi", "vi", "measure"]
```

`extraction/consensus/std_7x2k9m1p3v5r8t0w.yaml`:

```yaml
study: "std_7x2k9m1p3v5r8t0w"
extracted_by: ["ethan", "sam"]
reconciled_by: "ethan"
fields:
  n_total:   {value: 148, source: "p. 1097, para 2"}
  retention_interval: {value: 168, unit: "hours", entered: "1 week", source: "p. 1097"}
effects:
  - id: "eff_7x2k9m1p3v5r8t0w_0001"
    outcome: "recall"
    design: "two-group-means"
    timepoint: "1 week"
    n1: 74
    m1: 0.62
    sd1: 0.18
    n2: 74
    m2: 0.48
    sd2: 0.21
    source: "Table 2"
```
