# Design: cli

*Informative.* The requirements are in [spec.md](spec.md).

## Every problem names its fix

`strata status` is the answer to "where am I?", and every line that reports a
problem names the command that addresses it. The tool should never report a
state the user cannot act on.

```
$ strata status

  Spaced retrieval and long-term retention                   criteria v4
  38 commits · 2 actors · last sync 2 hours ago · clean

  SEARCHES        4 databases, 7,282 records identified, last run 2026-03-04
                  ! S-04-psycinfo has no query string recorded  (PRISMA item 7)

  DEDUPLICATION   2,918 canonical  (4,364 duplicates removed)
                  47 pairs awaiting review                      strata dedup --review

  TITLE/ABSTRACT  2,918 records
                  ############################......  4,002 / 4,182 resolved
                  14 conflicts                                  strata adjudicate
                  180 stale                                     strata rescreen

  FULL TEXT       204 reports · 196 assessed · 8 not retrieved
                  21 stale (upstream)

  EXTRACTION      38 studies · 31 complete · 5 partial · 2 not started
                  3 studies with unreconciled disagreements     strata extract --reconcile

  ANALYSIS        primary        stale (data changed since last run)
                  sensitivity    up to date

  NEXT            strata rescreen        180 records, ~55 min at your recent pace
```

## Errors are for researchers under deadline

Every error says what happened, why, and what to do next, with no stack trace
unless `-vv`:

```
  error: cannot run `strata analyze primary`

  3 included studies have no reconciled extraction:

    std_7x2k9m1p3v5r8t0w   Larsen et al. (2009)
    std_2b8n4k6m0p2r4t6v   Kornell (2009)
    std_9v3x1z5c7b9n1m3q   Roediger & Karpicke (2006)

  Extract them first:   strata extract --missing
  Or exclude them from this analysis by editing the `include.filter`
  in analysis/primary.yaml.
```

## Why everything is scriptable

Reviews must be reproducible from a script and drivable from CI, so every
interactive workflow has a non-interactive equivalent, and `--json` output is a
versioned contract.

## Why `--yes` never skips the rationale

`--yes` answers confirmations. The rationale is data, not a confirmation, and a
flag that silently supplied one would defeat its purpose.

## Why exit codes are fine-grained

Scripts and CI need to tell "the repository is invalid" (4) from "a guardrail
blocked this" (8) from "you need to explain yourself" (7) without parsing text.
