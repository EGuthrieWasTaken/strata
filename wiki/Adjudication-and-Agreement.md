# Adjudication and agreement

When two reviewers screen independently they will sometimes disagree. Resolving those disagreements, and
reporting how often they happen, are separate jobs that `strata` keeps separate: **adjudication** settles a
record; **agreement statistics** describe the reviewers' independent first opinions and are never altered by
the settling.

## What counts as a conflict

At each stage, a record is in *conflict* when the reviewers assigned to it have all opined and either they
disagree or anyone said "maybe". `strata status` shows the number and tells you what to run:

```
TITLE-ABSTRACT  8 records    6 resolved · 0 unscreened · 0 partial
  2 conflicts                strata adjudicate

NEXT  strata adjudicate
```

## Adjudicating

Only the people listed in `screening.adjudicators` in `strata.toml` (by default the lead) may adjudicate. A
**rationale is always required**, whatever your `require_rationale` setting, because an adjudication is the
final word on a record and has to be defensible.

```
strata --why "Adult learners on a university course count as formal education; the full abstract describes a manipulated schedule" adjudicate --by ada
```

Each conflict is shown with both opinions, the criteria cited and any notes:

```
Conflict 1 of 2                title-abstract

Retrieval practice schedules in adult language learners

ada        INCLUDE    2026-10-24
sam        EXCLUDE    2026-10-24
           citing INC-01
           "Adults outside formal education"

 include    exclude    discuss    skip    quit
Decision [s]:
```

The prompt takes one key: `i` include, `e` exclude (you then cite criteria), `d` discuss (record a note
without deciding, for example "talk to Sam on Thursday"), `s` skip, `q` quit. The rationale comes from `--why`
(in a terminal without `--why` you are asked for it, once per decision). Restrict to one stage with `--stage
full-text`.

An adjudication overrides the reviewers' opinions for the record, but their opinions stay in the log, and
agreement statistics still use them.

### When disagreement is really about the criteria

If the same disagreement keeps recurring ("is a university student in an evening course a learner in formal
education?"), the criterion is underspecified. Settle the individual records, then **change the criterion**
(with its direction) rather than adjudicating the same question a hundred times:
[Changing criteria mid-review](Changing-Criteria-Mid-Review).

## Agreement statistics

```
strata irr
```

```
title-abstract   ada x sam   n=7   agreement=0.86   kappa=0.70   pabak=0.71
```

For each pair of reviewers and each stage it reports:

| Statistic | Meaning |
|---|---|
| `n` | Records both reviewers screened *independently* |
| `agreement` | The proportion of records on which they gave the same decision |
| `kappa` | Cohen's kappa: agreement beyond chance |
| `pabak` | Prevalence-adjusted bias-adjusted kappa; read it alongside kappa when nearly everything is excluded (which depresses kappa) |

They are computed from each reviewer's **first** opinion on each record, so changing your mind, adjudication and
re-screening do not inflate them. (Decisions imported from another tool are not told apart yet, so only report
agreement for screening done independently in `strata`; see [Screening](Screening).) `strata irr`
rewrites `derived/irr.json` but does not commit; the next command that commits picks it up. The generated
Methods report these figures (for example "Agreement between ada and sam at title-abstract was 86% (Cohen's
kappa 0.70, n = 7)"). `--stage` limits it to one stage.

How to read kappa is a judgement call (conventions vary; many reviews aim for at least 0.6 to 0.8 after the
pilot); `strata` reports the number and does not grade it.

## Spot-checking exclusions

Because staleness relies on the criteria cited when a record was excluded ([Staleness](Staleness)), a
reviewer who cited the wrong criterion can hide a decision from a later change. `strata` cannot fully protect
against that, but it can help you look:

```
strata audit --criteria --sample 20 --seed 1
```

re-presents 20 randomly chosen past exclusions with the criteria cited, so a second pair of eyes can confirm
them (`--seed` reproduces the same sample, which is useful to report). Schedule one after the pilot and one
before you finish.

Next: [Changing criteria mid-review](Changing-Criteria-Mid-Review), or on to
[Retrieving full texts](Retrieving-Full-Texts).
