# Dedup benchmark results

Generated 2026-09-24 by `scripts/dedup_benchmark.py` against the fixture in
`tests/fixtures/dedup-benchmark/` (55 hand-labelled, synthesised records --
**not** a real ASySD or `revtools` export; see that directory's `README.md`
for why and how it was built). Enforced by
`tests/integration/test_dedup_benchmark.py` on every CI run, so these numbers
cannot drift from what the test suite actually checks.

Evaluated at default (non-strict) thresholds: `auto_merge_threshold=0.95`,
`review_threshold=0.80`, per openspec:deduplication#thresholds-and-actions.

| Metric | Value | v1 target (openspec:deduplication#validation-against-a-labelled-benchmark) |
|---|---|---|
| Recall | 1.000 | >= 0.95 |
| False-merge rate | 0.0000 | <= 0.001 |
| Precision | 1.000 | (not targeted) |
| F1 | 1.000 | (not targeted) |

**PASS** against the v1 acceptance bar.

Detail:
- 21 ground-truth duplicate pairs (same-work
  clusters of 2-3 records each); 21 ended up
  in the same final cluster after `strata dedup` (directly auto-merged, or
  transitively via a chain of two auto-merges).
- 20 correct auto-merge actions,
  0 incorrect ones (false merges).
- 38 candidate pairs proposed by blocking in
  total, of which 2 were queued for human review rather
  than auto-merged or silently discarded -- among them
  2 of the fixture's labelled "confusable"
  hard-negative pairs (deliberately adversarial true negatives, e.g. an
  erratum vs. its original, or a two-part study); the rest of the confusable
  pairs scored low enough to fall to plain "distinct" with no event at all.
  Either outcome is correct -- both avoid a false merge. See the fixture's
  `README.md` for what each hard-negative pair is testing.

Recall and the false-merge rate are the two numbers
openspec:deduplication#validation-against-a-labelled-benchmark requires; precision
and F1 are reported for context, not gated on. Recall is computed against
each ground-truth pair's *final canonical id* after dedup, not against the
literal `dedup-merge` event log, so a three-record chain (A absorbs B, then
A absorbs C) correctly credits the untouched pair (B, C) as resolved --
see `strata.dedup.benchmark`'s module docstring for why that distinction
matters.

This is a small (55-record), hand-curated benchmark, not a large real-world
corpus: it demonstrates the scoring/blocking/threshold logic is *correct* on
a set of realistic cross-database formatting variations and a handful of
deliberately hard true negatives (an erratum, a two-part study, same-author
same-issue distinct papers), not that recall/false-merge-rate will hold at
this level on an arbitrary real dataset. Performance at 50,000 records is
checked separately (`tests/benchmark/`, advisory CI tier, not this file).
