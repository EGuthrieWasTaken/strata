# Design: provenance-queries

*Informative.* The requirements are in [spec.md](spec.md).

These commands are the answer to a peer reviewer's "why is this paper in your
review?" — generated, not remembered (goal G1: nothing is lost).

## Example: `strata why`

```
$ strata why rec_3kq8v1r0zx2m4a7b

  Cepeda et al. (2008). Spacing effects in learning...
  Psychological Science, 19(11), 1095-1102.  doi:10.1111/j.1467-9280.2008.02209.x

  Current state:  INCLUDED (full-text) -> study std_7x2k9m1p3v5r8t0w

  2026-03-04  imported          S-01-medline (Ovid MEDLINE), row 412
  2026-03-04  imported again    S-02-embase, row 88  -> absorbed rec_9m2p0000000000ab
                                  score 1.00 (exact DOI)
  2026-03-07  screened  ethan   include   (criteria v3)
  2026-03-08  screened  sam     include   (criteria v3)
              -> resolved INCLUDE at title-abstract
  2026-03-19  criteria change   v3 -> v4  (EXC-07 added)
              -> decision marked STALE: a new exclusion criterion applies
                 commit 4f1a2b9 "Add age criterion after pilot extraction"
                 rationale: "Pilot extraction showed 9 of 40 studies used
                 child samples, which our question does not cover."
  2026-03-20  re-screened ethan include   (criteria v4)
  2026-03-20  re-screened sam   include   (criteria v4)
              -> resolved INCLUDE, no longer stale
  2026-03-28  retrieved         via institutional access, version of record
  2026-04-02  full-text ethan   include   (criteria v4)
  2026-04-02  full-text sam     include   (criteria v4)
  2026-04-03  grouped           into study std_7x2k9m1p3v5r8t0w
  2026-04-11  extracted         ethan, sam -> reconciled by ethan
              contributes 2 effects to analysis `primary`
```

## Example: `strata diff`

```
$ strata diff v1-protocol..HEAD

  Criteria:   v1 -> v4  (2 added, 1 tightened, 1 retired)
  Records:    +1,882 identified   (-419 duplicates)
  Pool:       1,204 -> 1,229 at full-text  (+67 entered, -42 left)
  Included:   38 -> 41 studies
  Primary:    g = 0.42 [0.31, 0.53] -> g = 0.38 [0.28, 0.48]
              I2 = 61% -> 58%,  k = 38 -> 41
```

The last line is the payoff of committing `analysis/results/`: a reviewer can
see exactly what a protocol change did to the headline number.
