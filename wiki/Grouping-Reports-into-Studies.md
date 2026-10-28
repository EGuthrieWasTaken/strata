# Grouping reports into studies

In a meta-analysis the unit is the **study**, not the paper. One trial may produce several reports
(a main paper, a long-term follow-up, a secondary analysis, a conference abstract), and one report may describe
several studies. Counting the same participants twice biases the pooled estimate, so before extracting data you
decide which reports belong to which study.

By default every included report is its own study. `strata studies` shows the position and what it suspects:

```
strata studies --list
```

```
4 included reports -> 4 studies
```

## Suggestions, never automatic

`strata` looks for signs that reports belong together: a shared trial registration number, shared authors and
sample size, a follow-up with the same sample in a different language, mutual citation. It shows each suggestion
**with its evidence** and never applies one. Grouping is a judgement, and every decision needs a rationale:

```
strata --why "Same trial, 12-month follow-up" studies --by ada \
    --group rpt_3kq8v1r0zx2m4a7b --group rpt_9m2f4t7c1x8a5d6e
```

Run `strata studies --by ada` (without options) for the interactive version, which walks the suggestions:
`g` group, `k` keep separate, `?` show both reports, `s` skip, `q` quit.

| Option | Meaning |
|---|---|
| `--group REPORT` | A report to put in the study (repeat it for each report) |
| `--study STUDY` | With `--group`: redefine this existing study instead of creating a new one |
| `--split REPORT` | A report that actually describes several studies |
| `--into N` | With `--split`: how many studies (default 2) |

## When to group

Group when the reports are the **same participants** analysed or followed up. Keep separate when they are
different trials by the same team, or the same trial reporting different, non-overlapping subgroups that you
treat as separate studies (and then handle dependence in the analysis, see [Analysis](Analysis)).

## When to split

Split a report that contains several independent experiments (a common pattern in psychology: "Study 1,
Study 2"). Each resulting study is extracted and weighted separately.

## What happens next

Each study gets a study id (`std_...`) and appears in the extraction queue. Grouping and splitting are
recorded as events with your rationale, so the history shows when and why a study's reports changed. Group
*before* you extract: regrouping afterwards means checking the extraction again.

Next: [Extracting data](Extracting-Data).
