# Removing duplicates

The same paper arrives from several databases. Counting it twice would double-count a study and distort the
PRISMA numbers; merging two different papers would lose one. `strata dedup` is built around that asymmetry: it
merges only when it is nearly certain, asks you about the rest, remembers every answer, and can undo any merge.

```
strata --why "Merging obvious duplicates" dedup --by ada
```

```
2 candidate pair(s); 2 auto-merged; 0 pending review
```

Run it after each import. It is idempotent, and it never asks about a pair you have already judged.

## What happens

1. `strata` finds **candidate pairs** cheaply (records sharing a DOI, a PubMed id, the start of a title, a
   first author with the same year and volume, a first page, or a very similar title).
2. Each pair gets a **similarity score** from 0 to 1, from the DOI when both have one, and otherwise from the
   title, authors, year, journal and volume/page ([how it is scored](How-Deduplication-Works)).
3. At **0.95 or more** the pair is merged automatically. From **0.80 up to 0.95** it goes in a **review
   queue**. Below 0.80 the records are left alone.
4. Two records with **different DOIs** are never merged automatically, however alike the rest: they go to the
   queue marked `doi-conflict`, because a DOI is the strongest evidence that they are different papers (a
   correction or a preprint, say).

Merging keeps the more complete record (the one with a DOI, abstract, authors, pages) as the *canonical* one
and copies in anything it lacks from the other. The absorbed record is **kept**, flagged as not canonical, so
nothing is lost and its original source is still on the canonical record's list of sources.

## Working the review queue

```
strata --why "Resolving doubtful duplicates" dedup --by ada --review
```

Each pair is shown with both records, which database each came from, and how similar each part is (this is
the layout; the pair shown is illustrative):

```
Pair 1 of 3                                        score 0.88

  A  rec_...     [MEDLINE]
     Castellano, Dube (2018)
     Distributed practice improves recall: a randomised classroom trial
  B  rec_...     [Embase]
     Castellano, Dube (2018)
     Distributed practice improves recall - a randomized classroom trial
     title 0.98 | authors 1.00 | year 1.00 | journal 0.74 | locator 1.00

  [m] merge   [k] keep both   [s] skip   [?] help
```

- **`m`**: merge them.
- **`k`**: keep both. They are different papers; this is recorded and **the pair is never raised again**,
  not even after a later import.
- **`s`**: skip for now; it stays in the queue.

When in doubt, keep both: a duplicate that survives is found again at full-text screening or study grouping,
whereas a wrong merge hides a paper. If you want to review everything not exactly identical, `strata dedup
--strict` sets both thresholds to 1.0.

## Undoing a merge

```
strata --why "These are a preprint and its correction, not duplicates" dedup --by ada --undo CANONICAL_ID ABSORBED_ID
```

The absorbed record becomes canonical again and the reason is recorded. (Fields that the merge copied onto the
canonical record are not rolled back: the merge recorded which record each field came from, but not the
canonical record's previous values.)

## Checking what dedup did

`strata why REC_ID` lists the merge and the features that drove it. `strata records list --all` includes
absorbed duplicates (they are hidden by default). The PRISMA diagram's "duplicates removed" count adds the entries
recognised as repeats at import ("matched existing") to the records absorbed by merges.

## Things to know

- **Exact duplicates in one file** (the same DOI twice) are handled at import, before dedup runs; that is
  the "matched existing" in the import summary.
- **Conference abstracts and full papers**, **preprints and published versions**, and **a paper and its
  erratum** look alike but are different records. Review them with care; `keep both` is the safe answer, and
  you can group related reports into one study later ([Grouping reports into studies](Grouping-Reports-into-Studies)).
- **Records with no DOI and an unstructured source** (a pasted reference list) are flagged and always go to
  the queue.
- **Speed.** Fifty thousand records take about two minutes on a laptop. Measured accuracy on the project's
  labelled benchmark is in [the benchmark report](https://github.com/EGuthrieWasTaken/strata/blob/main/docs/dedup-benchmark-results.md).

Next: [Screening](Screening).
