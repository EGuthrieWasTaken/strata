# Design: deduplication

*Informative.* The requirements are in [spec.md](spec.md).

## Why it matters

The same paper appears in MEDLINE, Embase, PsycINFO, and Scopus in four slightly
different forms. Deduplication is unglamorous and is where reviews silently
break: a missed duplicate double-counts a study in the meta-analysis; an
over-eager merge deletes a real study. Both are publishable errors. Hence the
four properties: sticky, reversible, conservative ("the cost of a review
question is seconds; the cost of a wrong merge is a retraction"), and
explainable.

## Why LSH blocking

All-pairs comparison is O(n^2) and infeasible at 50,000 records. Prefix blocking
misses titles that differ by an OCR error, a subtitle, or a truncation; the
MinHash/LSH band over title 3-grams catches them. The 2,000-member block cap
exists because a runaway block is almost always a parse failure that put a
constant string in the title field.

## The DOI veto is the highest-risk rule

Different DOIs usually mean different papers: an erratum, a reprint, and a
preprint/version-of-record pair are genuinely distinct records. But publishers
do occasionally issue two DOIs for one article. So a DOI mismatch scores 0 for
automatic merging, yet a pair that scores high on every other feature is routed
to a human labelled `doi-conflict` rather than discarded.

## Why the false-merge rate is weighted most

A false merge destroys data; a missed duplicate merely wastes screening time.
The benchmark therefore reports the false-merge rate separately and holds it to
a much tighter target (<= 0.001) than recall (>= 0.95). Results are published in
[docs/dedup-benchmark-results.md](../../../docs/dedup-benchmark-results.md).

## The review queue

```
$ strata dedup --review

  Pair 3 of 47                                       score 0.88   doi-conflict

  A  rec_3kq8v1r0zx2m4a7b     [scopus]   10.1111/j.1467-9280.2008.02209.x
     Cepeda, Vul, Rohrer, Wixted & Pashler (2008)
     Spacing effects in learning: A temporal ridgeline of optimal retention
     Psychological Science, 19(11), 1095-1102

  B  rec_7p1m4k8v2x6z0a3c     [embase]   10.1111/j.1467-9280.2008.02209.x-2
     Cepeda N.J., Vul E., Rohrer D., et al. (2009)
     Spacing effects in learning. A temporal ridgeline of optimal retention
     Psychol Sci, 19, 1095

     title 0.97 | authors 1.00 | year 0.70 | journal 1.00 | pages 0.50
     DOIs differ (suffix "-2" on B) -- flagged for human judgement

  [m] merge   [k] keep both   [s] skip   [o] open both   [?] help
```

One pair per screen, with the evidence visible. `[k]` records a
`dedup-distinct` event so the pair is never raised again.

## Prior art

ASySD and `revtools` (R) implement deduplication well; `strata` reimplements the
heuristics and validates against benchmarks of the kind they publish, because
the decision record has to live in `strata`'s event log.
