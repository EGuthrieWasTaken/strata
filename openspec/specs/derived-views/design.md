# Design: derived-views

*Informative.* The requirements are in [spec.md](spec.md).

## pool.tsv is the most important generated file

`derived/pool.tsv` is what a reviewer reads in a `git diff` to see what a change
did to the candidate pool. Everything about its format serves that: one row per
canonical record, fixed columns, rows sorted by id so unrelated rows never move,
titles truncated so lines stay readable, and TSV rather than JSON so a line diff
is a record diff.

An example diff after tightening a criterion:

```
-rec_3kq8v1r0zx2m4a7b	include	include	-	2008	Cepeda	Spacing effects in learning...
+rec_3kq8v1r0zx2m4a7b	include	include	tiab,ft	2008	Cepeda	Spacing effects in learning...
```

## Why IRR uses first opinions only

A reviewer who changes their opinion after seeing a colleague's decision (in
adjudication discussion, say) is no longer an independent rater. Counting the
changed opinion would inflate agreement and make the reported inter-rater
reliability a fiction. The fold therefore keeps each actor's first event per
record as well as the last, and IRR is computed from the first.

## Why derived views are committed

See principle P3 in the `repository-format` design: the views are regenerated
deterministically and never read as input, so committing them costs nothing in
correctness and makes every change's consequences visible in ordinary git tools.
