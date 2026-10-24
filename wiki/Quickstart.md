# Quickstart: a whole review in about 30 minutes

This walks through a complete, tiny review on invented data: set up, search records, import, remove
duplicates, screen, retrieve, extract, analyse, and draw the PRISMA diagram. It is a tour, not a recipe for
your review: each step has a full guide on the stage pages linked at the end.

Everything below was run for real; the output shown is what you will see. The data are invented (the journals
and authors do not exist), so the numbers mean nothing.

**You need:** [`strata` installed](Installation), a terminal, and the two small example files
[`spacing-medline.ris`](https://raw.githubusercontent.com/wiki/EGuthrieWasTaken/strata/examples/spacing-medline.ris)
and [`spacing-embase.ris`](https://raw.githubusercontent.com/wiki/EGuthrieWasTaken/strata/examples/spacing-embase.ris)
saved in your current folder. (They are 8 and 3 references, as if exported from two databases.)

> **About `--why`.** Every command that changes the review records *why*. In a terminal `strata` asks you;
> here every command carries `--why "..."` so you can paste the lines as they are. Put it before the command
> name, as shown. A real reason ("Pilot showed adults on a course count as formal education") is the most
> useful sentence in a review's history. It must be at least 12 characters, and a bare "fix" or "update" is
> refused (exit code 7): say what changed and why.

## 1. Start the review

```
strata init spacing-review --title "Spacing and retention" --actor ada --actor-name "Ada Example"
cd spacing-review
```

This makes a folder that is also a git repository (you will not need to use git). `ada` is your *actor
handle*: it labels everything you do. Look at where things stand at any time with:

```
strata status
```

A real review has at least two people screening each record independently. For this tour you are the only
reviewer, so tell `strata` that (it is recorded, and generated Methods text will say so plainly):

```
strata --why "One reviewer for this tour" config screening.mode single
git commit -qam "settings: single reviewer for this tour"
```

(`strata config` changes the file but does not commit it yet; that one `git commit` is the only git you need
in this tour. See [Known limitations](Known-Limitations).)

## 2. Say what you are looking for

Eligibility criteria are the heart of a review. Each has a *kind*, a *label*, a *definition* and the stages
it applies at:

```
strata --why "Protocol criteria" criteria add --kind inclusion --label "Learners in formal education" --definition "Participants are school pupils or university students." --applies-at title-abstract,full-text --by ada
strata --why "Protocol criteria" criteria add --kind inclusion --label "Spacing manipulated" --definition "Compares a spaced practice schedule with a massed one." --applies-at title-abstract,full-text --by ada
strata --why "Protocol criteria" criteria add --kind exclusion --label "Not an empirical study" --definition "Narrative reviews, editorials and commentaries without new data." --applies-at title-abstract,full-text --by ada
strata --why "Protocol criteria" criteria add --kind exclusion --label "Not human" --definition "Animal or in-vitro studies." --applies-at title-abstract --by ada
```

```
added INC-01 (criteria v1)
added INC-02 (criteria v2)
added EXC-01 (criteria v3)
added EXC-02 (criteria v4)
```

The criteria are now at **version 4**. If you change one later, `strata` can tell you exactly which decisions
that makes unsafe: see [Changing criteria mid-review](Changing-Criteria-Mid-Review).

## 3. Record the searches and import the results

Record each search *before* importing its results, with the query exactly as you ran it:

```
strata --why "Recording the MEDLINE search" search add --database MEDLINE --platform Ovid --by ada --query "1. exp Learning/ 2. (spaced or distributed or massed) adj3 practi*.ti,ab. 3. 1 and 2" --hits 8 --executed 2026-10-01
strata --why "Recording the Embase search" search add --database Embase --platform Ovid --by ada --query "spaced or distributed practice" --hits 3 --executed 2026-10-02
```

```
recorded search S-01-medline
recorded search S-01-embase
```

Then import each database's export, naming the search it came from:

```
strata --why "Importing the MEDLINE export" import --by ada --search S-01-medline ../spacing-medline.ris
strata --why "Importing the Embase export" import --by ada --search S-01-embase ../spacing-embase.ris
```

```
imported ../spacing-medline.ris as imp_01m5p6swtasmdqsg1d9a6vm3t8: 7 new, 1 matched existing, 0 rejected
imported ../spacing-embase.ris as imp_01m5p6t29rbcsv8xzcska4w1e3: 3 new, 0 matched existing, 0 rejected
```

(Adjust the path to wherever you saved the files. The import ids will differ.) The MEDLINE file had 8
references but 7 new records: two of its entries were the same paper (same DOI), which `strata` recognises
on import. Importing the same file twice does nothing the second time.

## 4. Remove duplicates

The Embase file repeats two papers without DOIs. `strata dedup` finds pairs that are almost certainly the
same paper and merges only those; anything doubtful goes to a queue for you to decide.

```
strata --why "Merging obvious duplicates" dedup --by ada
```

```
2 candidate pair(s); 2 auto-merged; 0 pending review
```

Nothing is deleted: the absorbed record is kept, linked to the one it merged into, and `strata dedup --undo`
reverses a merge. You now have 8 distinct records to screen.

## 5. Screen titles and abstracts

```
strata --why "Title and abstract screening" screen title-abstract --by ada
```

Each record appears with its criteria numbered. You type a letter:

```
title-abstract  record 1 of 8

Sleep and memory consolidation in rats
Lindqvist · Example Neuroscience Letters · 2017

Invented abstract for illustration. An animal study unrelated to classroom learning.

Criteria:
  1  INC-01  Learners in formal education
  2  INC-02  Spacing manipulated
  3  EXC-01  Not an empirical study
  4  EXC-02  Not human
[i]nclude [e]xclude [m]aybe [s]kip [u]ndo [q]uit [s]:
```

For this record press `e`, then `4` (the criterion that excludes it), then Enter for no note. Include the
next five (`i`, Enter). Exclude the narrative review with `e`, `3`. Include the last. Each decision is saved
the moment you make it; if your terminal closes, run the command again and it resumes where you stopped.

```
strata status
```

```
TITLE-ABSTRACT  8 records    8 resolved · 0 unscreened · 0 partial

RETRIEVAL  6 reports sought    0 retrieved · 6 outstanding · 0 not retrieved
  strata retrieve

NEXT  strata retrieve
```

Six records passed. They now need their full texts.

## 6. Retrieve full texts and screen them

`strata retrieve --by ada --list` shows the six reports sought. As you obtain each one, record it (the file
itself stays on your disk; only an identifier and version are recorded):

```
strata --why "Obtained through the library" retrieve --by ada --report rpt_3bfqqz4nft3qqtqr --outcome retrieved --source institutional-access --version version-of-record
strata --why "Not held; interlibrary loan refused" retrieve --by ada --report rpt_1qjn6pvab3h794qe --outcome not-retrieved --reason no-access
```

(Do the first line for each of the other four reports as well; `--list` gives their ids.) A report you could
not get must be given a reason; it appears in the PRISMA diagram.

Now screen the five you have. Exclusions at this stage must cite a criterion. At present the full-text queue
lists every record, so limit it to the five you retrieved:

```
strata --why "Full-text screening" screen full-text --by ada --filter "id in ['rec_3bfqqz4nft3qqtqr','rec_9fz6sp8zep3zep1h','rec_ayx2jbeg0p7ka6qq','rec_bja43jkhyfj1qxwv','rec_yszjwbn5drx1ybr0']"
```

Include four (`i`, Enter) and exclude the last with `e`, `2`, and a note. (See
[Screening](Screening) for why the filter is needed and [Known limitations](Known-Limitations).) Four studies
are included.

## 7. Extract the data

`strata extract init` drafts a coding form from your protocol. For this tour the draft is enough; it asks for
the total sample size and lets you enter the effect as the paper reports it.

```
strata --why "Drafting the coding form" extract init
strata extract --list
```

For each included study, enter its values with the place in the paper they came from (after `@`) and its
effect. Here, for the first study:

```
strata --why "Extracting from the full text" extract std_3bfqqz4nft3qqtqr --by ada --set "n_total=120 @ Table 1" --effect '{"outcome": "recall", "design": "two-group-means", "n1": 60, "m1": 14.2, "sd1": 3.1, "n2": 60, "m2": 12.5, "sd2": 3.3, "source": "Table 2"}'
```

```
effect recall||: yi=0.5276074842972333 vi=0.03449320690619356
recorded 1 field(s), 1 effect(s)
```

`strata` converted the group means and SDs into a standardised mean difference (`yi`, Hedges' g) and its
variance (`vi`). Do the same for the other three studies; the invented numbers are:

| Study id | Study | `n_total` | n1, mean1, SD1 | n2, mean2, SD2 |
|---|---|---|---|---|
| `std_9fz6sp8zep3zep1h` | Alder & Brooks (2016) | 90 | 45, 68.0, 14.0 | 45, 60.5, 15.2 |
| `std_ayx2jbeg0p7ka6qq` | Eriksen & Fofana (2014) | 72 | 36, 22.1, 5.0 | 36, 19.8, 5.4 |
| `std_bja43jkhyfj1qxwv` | Castellano & Dube (2018) | 103 | 52, 55.0, 11.0 | 51, 50.2, 12.0 |

The second study uses a 0-100 test, so `strata` warns that its SD is an outlier among the others
(`sd-outlier`). That is a *data-quality warning*, not an error: the value is saved, and because a
standardised effect does not depend on the scale you can acknowledge it so it does not recur:

```
strata --why "0-100 test; the standardised effect is scale-free" extract std_9fz6sp8zep3zep1h --by ada --ack sd-outlier=eff_9fz6sp8zep3zep1h_0001 --note "0-100 test; SMD is scale-free"
```

Because you declared no moderators, the drafted form asks only for the total sample size. Declare moderators
(retention interval, age group, ...) in `protocol/moderators.yaml` *before* `strata extract init` and the form
gets a field for each: see [Extracting data](Extracting-Data), which also covers every other way of entering
an effect (2x2 tables, correlations, test statistics, pre-computed values) and the other warnings.

## 8. Pool the results

An analysis is a small file in `analysis/`. Create `analysis/primary.yaml`:

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

```
strata --why "Primary analysis, as pre-specified" analyze primary --ack k-lt-5
```

```
primary (preregistered): SMD 0.476 [0.147, 0.805], 4 studies, 4 effects
  hk-truncation: The Knapp-Hartung standard error was truncated to the Wald standard error
(metafor's ad hoc rule).
```

`strata` warns that fewer than five studies is a thin base for estimating between-study variance (`k-lt-5`,
which you acknowledged with `--ack`). That is the point of its *guardrails*: they never block silently, they
tell you, and your acknowledgement is recorded. Results are in `analysis/results/primary/`: `summary.md`
(plain-language), `estimates.json`, `studies.tsv` and the forest and funnel plots as SVG.

## 9. Draw the flow diagram and draft the text

```
strata --why "Flow diagram" prisma
strata report checklist --status
strata --why "Methods draft" report methods
strata --why "Results draft" report results
```

`reports/prisma.svg` is the PRISMA 2020 flow diagram, drawn from the log (every count is checked for
consistency first). `reports/methods.md` and `reports/results.md` are drafts that state what was done and
found, marked with the commit they came from; `strata` never writes a Discussion or Conclusion. The
checklist command reports which of the 42 PRISMA 2020 items are filled in from the repository and which are
yours to write.

A flavour of the generated Results:

> The searches and other sources identified 11 records. After removing 3 before screening (3 duplicates), 8
> records were screened and 2 excluded. Of 6 reports sought for retrieval, 1 could not be retrieved; 5 were
> assessed for eligibility and 1 excluded (Spacing manipulated, n = 1). In total, 4 studies (4 reports) were
> included.

## 10. Check, and what next

```
strata verify
```

```
ok — repository is valid
```

Your whole review is in the `spacing-review` folder. Back it up like any folder, or share it (see
[Working with others](Working-with-Others)).

Go deeper, in the order of a review:
[Setting up a review](Setting-Up-a-Review) ·
[Searching and importing](Searching-and-Importing) ·
[Removing duplicates](Removing-Duplicates) ·
[Screening](Screening) ·
[Adjudication and agreement](Adjudication-and-Agreement) ·
[Changing criteria mid-review](Changing-Criteria-Mid-Review) ·
[Retrieving full texts](Retrieving-Full-Texts) ·
[Extracting data](Extracting-Data) ·
[Risk of bias](Risk-of-Bias) ·
[Analysis](Analysis) ·
[Reporting](Reporting)
