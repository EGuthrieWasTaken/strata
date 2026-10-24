# How deduplication works

This is the concept page behind [Removing duplicates](Removing-Duplicates): why the tool behaves as it does,
in the terms a methodologist would use to defend it.

## Four promises

Deduplication in `strata` is **sticky, reversible, conservative and explainable**.

- **Sticky.** Every merge, and every "these are not duplicates" judgement you make, is recorded as an event.
  Running `strata dedup` again after another import never re-asks about a pair you already judged.
- **Reversible.** Any merge can be undone, with a recorded reason. Nothing is ever deleted; an absorbed record
  stays in the repository, marked as not canonical.
- **Conservative.** When the evidence is not overwhelming, a person decides. A wrongly merged pair hides a
  study; a missed duplicate is merely caught later.
- **Explainable.** Every automatic merge stores the numbers that drove it, so `strata why` can show *why* two
  records were treated as one.

## Finding candidates (blocking)

Comparing every record with every other would take far too long on tens of thousands of references. Instead,
two records are compared only if they share at least one cheap *block key*:

| Key | Meaning |
|---|---|
| DOI | The normalised DOI |
| PubMed id | The PMID |
| Title start | First 12 characters of the normalised title, plus the year |
| First author, year, volume | Normalised family name + year + volume |
| Title similarity hash | A locality-sensitive hash of character 3-grams of the title (catches titles that differ by a subtitle or punctuation) |
| First page | Normalised journal + volume + first page |

A block that grows past 2,000 members (usually a parse fault that put the same text in thousands of titles) is
split by year and a warning is shown.

## Scoring a pair

If **both** records have a DOI, the score is decisive: 1.0 if they are equal, 0.0 if they differ. Otherwise:

```
score = 0.50 × title + 0.20 × authors + 0.15 × year + 0.10 × journal + 0.05 × volume/page
```

- *title*: the better of a word-set overlap and an edit-distance ratio on the sorted words.
- *authors*: overlap of family names (half credit if only a first author is available on either side).
- *year*: 1 if equal, 0.7 if one apart, 0 otherwise.
- *journal*: similarity after expanding common abbreviations ("J" to "journal").
- *volume/page*: 1 if both match, 0.5 if one does.

The score is symmetric (a against b is b against a). Records that score highly but have *different* DOIs are
sent to review labelled `doi-conflict` rather than discarded.

## Actions

| Score | What happens |
|---|---|
| 0.95 or more (`auto_merge_threshold`) | merged automatically |
| 0.80 to 0.95 (`review_threshold`) | queued for you |
| below 0.80 | treated as different; nothing is recorded |

Both thresholds are in `strata.toml` under `[dedup]`; `--strict` temporarily makes both 1.0.

## Choosing the survivor

The canonical record is the most complete one (count of populated DOI, abstract, authors and pages), then the
one from the most trusted source (`dedup.source_trust`: CrossRef, PubMed, Scopus, Web of Science, Embase,
EBSCO, then manual), then the lowest id. Fields combine: an empty field is filled from the other record; where
both have a value, the more trusted source wins; the abstract takes the longest; keywords are the union. Every
field's origin is recorded.

## Why it is trustworthy

The engine is evaluated against a labelled benchmark with published results, reporting recall, precision and,
weighted most heavily, the **false-merge rate**. The targets are recall of at least 0.95 and a false-merge
rate of at most 0.001 at default thresholds; the published run meets them (see the
[benchmark report](https://github.com/EGuthrieWasTaken/strata/blob/main/docs/dedup-benchmark-results.md)).
The benchmark is a synthesised stand-in for the public ones in the literature, so treat it as evidence of
the algorithm's behaviour, not a guarantee for your particular databases: always keep an eye on the review
queue.
