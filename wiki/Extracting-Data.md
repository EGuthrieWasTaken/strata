# Extracting data

Extraction turns each included study into rows an analysis can use: a few **study-level fields** (sample size,
age group, retention interval, ...) and one or more **effects** (the numbers the paper reports for an outcome).
`strata` records every value with a **source locator** (where in the paper it came from), converts units,
computes the effect size as you type, warns about implausible values, and, with two extractors, reconciles
their differences with a recorded rationale.

## 1. The coding form

Declare the moderators and outcomes you expect in `protocol/moderators.yaml` and `protocol/outcomes.yaml`
([Setting up a review](Setting-Up-a-Review)), then draft the form from them:

```
strata --why "Drafting the coding form from the protocol" extract init
```

```
created extraction/schema.yaml with 3 field(s):
  n_total, retention_interval, learner_level
Edit it (and raise its version) to add fields; then run strata extract.
```

`extraction/schema.yaml` is plain text you can edit. Each field has a `name`, `label`, `type`, whether it is
`required`, and constraints:

| Type | Notes |
|---|---|
| `integer`, `number` | optional `min` / `max` |
| `quantity` | a value with a unit: `unit` (the stored unit) and `accepts_units` (what a reviewer may type) |
| `categorical`, `multi-categorical` | `levels` required |
| `boolean`, `text`, `date`, `citation` | |

A **quantity** is entered with its unit and stored normalised. For the field `retention_interval` (unit
`days`), typing `1 week` stores `value: 7, unit: days, entered: 1 week`. A unit that cannot be converted is
`E_UNIT` and blocks the analysis.

**Changing the form later** is expected. Raise the form's `version`; adding a required field marks existing
extractions *incomplete* for that field (not invalid), and `strata extract --missing` queues exactly those
studies.

The `effects` section of the form lists the outcomes and the **designs**: the ways an effect can be reported,
each with the inputs it requires.

## 2. Entering a study

Interactively, `strata extract STUDY_ID --by you` (a unique prefix of the id is enough) walks the fields, then
effects. In a script, give everything on the command line:

```
strata --why "Extracting from the full text" extract std_3bfqqz4nft3qqtqr --by ada \
    --set "n_total=120 @ Table 1" --set "retention_interval=7 days @ Methods" --set "learner_level=primary @ p.3" \
    --effect '{"outcome": "recall", "design": "two-group-means", "n1": 60, "m1": 14.2, "sd1": 3.1, "n2": 60, "m2": 12.5, "sd2": 3.3, "source": "Table 2"}'
```

```
effect recall||: yi=0.5276074842972333 vi=0.03449320690619356
recorded 3 field(s), 1 effect(s)
```

- `--set "NAME=VALUE @ SOURCE"`: a field and where you found it. Everything after `@` is the source locator
  (page, table, figure, section). **Always record one**; it is how a second reviewer, an editor or your future
  self checks a value, and `strata export provenance` lists every value with its source.
- `--effect '{json}'`: one effect. Repeat it for several effects from one study.
- Use the value `NR` for "not reported".
- `strata extract --list` shows the queue with what is missing for each study; `--missing` works only the
  incomplete ones.

### Effect designs

Enter the effect **in whatever form the paper reports it**; `strata` computes the effect size. The `design`
says which form, and the JSON must carry its inputs:

| Design | Inputs | Gives |
|---|---|---|
| `two-group-means` | `n1, m1, sd1, n2, m2, sd2` (or `se1`/`se2`, or `ci_lo1, ci_hi1` and `ci_level` in place of an SD) | standardised mean difference (Hedges' g); `"measure": "MD"` for the raw difference |
| `two-group-binary` | `events1, n1, events2, n2` | log odds ratio (default), `"measure": "logRR"` or `"RD"` |
| `single-group-proportion` | `events, n` | logit (default) or Freeman-Tukey (`"measure": "PFT"`) proportion |
| `correlation` | `r, n` | Fisher's z |
| `pre-post` | `n, m_pre, sd_pre, m_post, sd_post, r` | standardised mean change (`r` is the pre-post correlation) |
| `t-test` | `t, n1, n2` | standardised mean difference |
| `f-test` | `F, n1, n2, direction` (1 numerator df only) | standardised mean difference |
| `chi-square` | `chi2, n, direction` | standardised mean difference |
| `p-value-only` | `p, n1, n2, direction` | standardised mean difference (flagged: derived from a p-value) |
| `hazard-ratio` | `hr, ci_lo, ci_hi` | log hazard ratio |
| `precomputed` | `yi, vi, measure` | an effect and variance computed elsewhere |

Other keys an effect can carry: `outcome` (must be one of the form's outcomes), `timepoint`, `source`, and
`moderators` (effect-level moderators). An effect missing an input its design requires is `E_EFFECT_INPUTS`.
The statistics behind each design are on [Statistical methods](Statistical-Methods).

### Data-quality warnings

`strata` **warns but does not block**, because implausible values are sometimes right:

| Code | Raised when |
|---|---|
| `sd-outlier` | an SD is more than 3 times or less than a third of the median SD for that outcome |
| `large-effect` | a computed standardised effect has \|g\| above 3 |
| `zero-cell` | a 2x2 table has a zero cell (the correction that will be applied is explained) |
| `n-inconsistent` | `n_total` differs from the sum of the arms |
| `p-derived` | the effect size was derived from a p-value |
| `stat-p-inconsistent` | a reported t or F statistic does not match its reported p-value (a statcheck-style check) |

A warning you have looked into can be **acknowledged**, with a note, so it does not recur and the
acknowledgement is part of the record:

```
strata --why "0-100 test; the standardised effect is scale-free" extract std_9fz6sp8zep3zep1h --by ada \
    --ack sd-outlier=eff_9fz6sp8zep3zep1h_0001 --note "0-100 test; SMD is scale-free"
```

## 3. Two extractors (recommended for a review of record)

Set `extraction.mode = "dual"` in `strata.toml` (the default is `single`). Each extractor works into their own
file (`extraction/by-reviewer/<handle>/`) without seeing the other's; then someone reconciles:

```
strata extract --reconcile --list                 # studies with differences nobody has settled yet
strata extract STUDY_ID --reconcile --list        # one study: every difference
```

```
6 of 7 items agree (86%)
  std_3bfqqz4nft3qqtqr field:n_total: ada: 120  |  sam: 118
```

Each difference has an *item id*: `field:NAME` for a coding-form field (effects have their own ids, shown in the
same listing). Settle one by naming the study and the item:

```
strata --why "Table 1 gives 120 analysed participants" extract STUDY_ID --by ada --reconcile \
    --item field:n_total --choose ada --rationale "Table 1 gives 120 analysed participants" --source "Table 1"
```

```
reconciled field:n_total: ada
```

For each disagreeing item you pick a reviewer's value (`--choose ada`), the agreed value (`agreement`), or
another (`--choose other --value 14`), and every reconciliation is recorded with a rationale and source. The
consensus lands in `extraction/consensus/<study>.yaml`, which is what analyses use. The first line of the listing is the extraction agreement rate: the share of compared items on which the two
extractors independently agreed (it does not change when you reconcile).

## 4. Checking and exporting

- `strata status` shows `EXTRACTION n studies, x complete, y missing values`.
- `strata verify` reports `E_MISSING_EXTRACTION` (a warning until you analyse) for an included study with no
  consensus extraction, and `E_ORPHAN_EXTRACTION` for an extraction whose study is no longer included.
- `strata export effects --format csv --out effects.csv` writes one row per effect, with `study_id`,
  `effect_id`, `yi`, `vi` and every moderator joined, so it loads straight into R:
  `metafor::rma(yi, vi, data = read.csv("effects.csv"))`. Other formats: `tsv`, `xlsx`, `rds`, `json`.
- `strata export provenance --format tsv` lists every value with its source locator.

## Practical advice

- **Pilot the form** on three or four studies before extracting the rest; changing it later is possible but
  costs time.
- **Record the source of every number.** It is the single thing that makes extraction auditable.
- **Extract the numbers as printed**, not recalculated; let `strata` convert.
- **When a paper reports several timepoints or outcomes**, enter each as its own effect with `timepoint`
  and `outcome`; the analysis then chooses how to handle effects that share a study ([Analysis](Analysis)).
- **Don't silence a warning to make it go away**; investigate, then acknowledge with a note saying why it is
  acceptable.

Next: [Risk of bias](Risk-of-Bias) and then [Analysis](Analysis).
