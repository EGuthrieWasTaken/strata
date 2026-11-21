# Worked example: BCG vaccine and tuberculosis

A small, finished review built with `strata` from published data, kept here as an example to read and
as a regression test (`tests/e2e/test_worked_example_bcg.py` rebuilds it and compares).

**The data** are the 13 controlled trials of BCG vaccine against tuberculosis pooled by Colditz et al.
(1994), *Efficacy of BCG vaccine in the prevention of tuberculosis: meta-analysis of the published
literature*, JAMA 271(9), and reanalysed by Viechtbauer (2010), *Conducting meta-analyses in R with the
metafor package*, Journal of Statistical Software 36(3). `trials.json` holds each trial's first author,
year, 2x2 table, absolute latitude and method of allocation, as in `metafor`'s `dat.bcg`.

## What the review does

`build.py` drives the command line the way a reviewer would:

1. `strata init`, a second reviewer, and one inclusion criterion.
2. `strata import` of the 13 trials, as records found by citation searching (the meta-analysis's list).
3. Both reviewers include every trial at title and abstract and at full text.
4. `strata extract`: each trial's 2x2 table as a `two-group-binary` effect on the log risk ratio, its
   latitude and its method of allocation.
5. `strata analyze primary` (random effects, REML, Wald intervals) and `strata analyze latitude` (the
   same model with latitude as a moderator), `strata prisma`, and the Methods and Results drafts.

```
uv run python examples/bcg-vaccine/build.py /tmp/bcg
```

## The results, and the published ones

| | strata (`results/`) | Published (Viechtbauer 2010) |
|---|---|---|
| Pooled log risk ratio (95% CI) | -0.7145 (-1.0669 to -0.3622) | -0.7145 (-1.0669 to -0.3622) |
| Pooled risk ratio | 0.489 (0.344 to 0.696) | 0.489 |
| tau^2 | 0.3132 | 0.3132 |
| Q(12) | 152.23 | 152.23 |
| Latitude: intercept, slope | 0.2515, -0.0291 | 0.2515, -0.0291 |
| Latitude: residual tau^2 | 0.0763 | 0.0764 |

`metafor` prints I^2 = 92.22% for this fit; `strata`'s I^2 is the Q-based (Q - df) / Q, 92.12%, the
same for every estimator. The prediction interval uses a t distribution on k - 2 degrees of freedom,
wider than `metafor`'s normal-quantile one. Both are stated in `results/primary/summary.md`.

## What is not real

- **The bibliographic records are stubs.** `dat.bcg` gives each trial's first author and year only, so a
  record's title names the trial ("trial 4 of the Colditz et al. (1994) meta-analysis, Hart & Sutherland
  (1977)") and it has no journal, DOI or PMID. Replacing them with the trials' real citations would make
  the example a better one.
- **Retrieval is outstanding,** for the same reason: `strata retrieve` records where a full text came from
  by an identifier on the record, and these have none. So `strata status` lists 13 reports to retrieve
  and the PRISMA diagram is marked DRAFT. That is what `strata` does when it cannot tell where a report
  came from, rather than something to work around.
- **Two reviewers who agree on everything,** and one extractor, because the point is the numbers.

`results/` holds the files a rebuild reproduces byte for byte: each analysis's `estimates.json`,
`studies.tsv`, `summary.md` and plot, and the PRISMA diagram. The files that name the commit they came
from (`run.json`, the Methods and Results drafts) differ from build to build and are left out.
