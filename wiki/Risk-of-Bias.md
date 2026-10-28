# Risk of bias

Risk-of-bias (RoB) assessment judges how far each included study's design and conduct could have distorted its
result. `strata rob` records the assessment domain by domain, with the signalling answers, your judgement, the
quote or note that supports it and where it came from. For RoB 2 it computes the **algorithmic suggestion** from
your answers; you may override it, but an override needs a written justification.

## Choose an instrument

```
strata --why "Using the RoB 2 instrument for the randomised trials" rob init --instrument rob2
```

```
created rob/instrument.yaml (RoB 2)
```

| `--instrument` | Tool | Judgement |
|---|---|---|
| `rob2` | RoB 2, parallel-group trials, effect of assignment | per domain: low / some concerns / high; overall = worst domain |
| `rob2-adhering` | RoB 2, effect of adhering to the intervention | as above (domain 2 differs) |
| `robins-i` | ROBINS-I, non-randomised studies of interventions | seven domains; overall = most severe |
| `nos-cohort`, `nos-case-control` | Newcastle-Ottawa Scale | stars per domain; overall = their sum |

The instrument is copied into `rob/instrument.yaml`, a plain file you may edit, or replace with your own in the
same shape (a custom instrument has no suggested judgements).

> **The official question wording is not included.** Cochrane's RoB 2 materials are CC BY-NC-ND 4.0 and the
> other tools have their own terms, so `strata` ships only domain names, judgement vocabularies, the
> question *numbers* with a short neutral topic ("Allocation sequence concealed"), and the answer options. Keep
> the official guidance beside you when you answer. If you hold a licence for the full wording you can add a
> `text:` entry to any question in `rob/instrument.yaml` and `strata` will show it. Details and what has and
> has not been checked: [the RoB instruments note](https://github.com/EGuthrieWasTaken/strata/blob/main/docs/rob-instruments.md).

## Assess a study

Interactively, `strata rob STUDY_ID --by you` walks the domains; for each it asks the signalling questions
(`Y`, `PY`, `PN`, `N`, `NI` for no information, `NA` where not applicable), shows the algorithm's suggestion,
and asks for your judgement and a supporting quote. From a script, one domain at a time:

```
strata --why "RoB 2 for Haddad and Ito" rob std_3bfqqz4nft3qqtqr --by ada --domain D1 \
    --answer 1.1=Y --answer 1.2=Y --answer 1.3=N --judgement low \
    --support "Central randomisation, opaque envelopes" --source "p.4"
```

```
the algorithm suggests: low
recorded D1: low
```

- `--domain` is a domain id (`D1` to `D5`) or `overall`.
- `--answer QUESTION=ANSWER` is repeatable. Use `NA` for questions the flow skips.
- `--judgement` is yours. If it differs from the suggestion you must also give `--override-justification
  "why"`.
- `--support` is the quote or note; `--source` the page or section.
- `strata rob --list` shows every study and its domains at a glance:

```
std_3bfqqz4nft3qqtqr  Haddad & Ito (2019)
    D1:low  D2:low  D3:low  D4:low  D5:low
std_9fz6sp8zep3zep1h  Alder & Brooks (2016)
    D1:some-concerns  D2:low  D3:low  D4:low  D5:low
```

Finish each study with the overall judgement:

```
strata --why "RoB 2 overall" rob std_9fz6sp8zep3zep1h --by ada --domain overall --judgement some-concerns
```

## Two assessors (recommended)

Each assessor works into their own file without seeing the other's; then reconcile:

```
strata --why "Reconciling the risk-of-bias assessments" rob STUDY_ID --by ada --reconcile
strata --why "Sam found the protocol deviation table" rob STUDY_ID --by ada --reconcile \
    --domain D2 --choose sam --rationale "Sam found the protocol deviation table"
```

The first walks the differences for a study interactively; the second settles one domain from a script.
`--choose` takes a reviewer's handle, `agreement`, or `other` (with `--value` for the judgement). Each
reconciliation is recorded with its rationale.

## Using the judgements

- `strata report rob` writes the assessment table; `strata report rob --format svg` the traffic-light plot
  ([Reporting](Reporting)).
- The judgements are available as moderators, `rob_overall` and `rob.D1` and so on, in `--filter` expressions
  and in `strata export effects`. A sensitivity analysis that drops high-risk studies is then one `subset`
  line in an analysis file ([Analysis](Analysis)).
- RoB 2 versions for cluster-randomised and crossover trials, ROBINS-E and QUADAS-2 are not shipped; define
  them as a custom instrument if you need them.

## A caution about the RoB 2 algorithm

The suggestions follow the published decision rules as transcribed in two independent open-source
implementations, which agree on every combination of answers; they have not yet been checked against
Cochrane's own algorithm tables. Treat a suggestion as a prompt for your judgement, not a replacement for it,
until that check is done (it is on [Known limitations](Known-Limitations)).
