# Design: adjudication

*Informative.* The requirements are in [spec.md](spec.md).

```
$ strata adjudicate

  Conflict 3 of 14                                    title-abstract

  Retrieval practice and the testing effect in medical education
  Larsen, Butler & Roediger (2009), Medical Education

  [abstract ...]

  ethan   INCLUDE   2026-03-07   "looks like an RCT with a delayed test"
  sam     EXCLUDE   2026-03-08   EXC-04 (wrong population)
                                 "medical residents, not undergraduates"

  [i] include   [e] exclude   [d] discuss (add a note, leave open)   [s] skip
```

## Why opinions are superseded, not erased

The adjudication resolves the record, but the original disagreement is the
honest input to inter-rater reliability. Both opinions remain in their files.

## Why a rationale is required

An adjudication is exactly the decision a peer reviewer will question.

## Why self-adjudication is allowed but counted

The review lead commonly adjudicates, and sometimes they were one of the two
conflicting screeners. Forbidding that would stall small teams; allowing it
silently would overstate independence. So it is allowed, noted in the event, and
counted in generated reports.

## Why "discuss" exists

Some conflicts need the Tuesday meeting. `[d]` records a note and leaves the
conflict open instead of forcing a premature decision.
