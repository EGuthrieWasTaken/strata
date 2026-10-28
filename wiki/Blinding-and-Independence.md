# Blinding and independent screening

The credibility of dual screening rests on the two reviewers being *independent*: neither is influenced by
the other's decisions. `strata` enforces that in the data and in the screen, and keeps the independence
measurable.

## What is enforced

- **Separate files.** Each reviewer's decisions are written to their own file under
  `events/screen/<stage>.<handle>.ndjson`. Nobody appends to anybody else's file, which is also why two
  people screening at once can never conflict when they share the review.
- **Blind reviewers** (`screening.blind_reviewers = true`, the default). While you screen a record, nothing on
  the screen reveals what your colleague decided, at any stage. Their opinion becomes visible only when the
  record turns up as a conflict for adjudication.
- **Blind metadata** (`screening.blind_metadata = true`, off by default). Additionally hides authors,
  journal and year during screening, for reviews that want to reduce bias from reputation.
- **First opinions are kept.** Agreement statistics use each reviewer's *first* decision on a record, so
  revising a decision, adjudication and re-screening cannot inflate agreement.

## What is not enforced

`strata` cannot stop two people from talking, sitting next to each other, or sharing a screen. Blinding in the
tool means "the software does not show it". If your protocol promises independence, say how you protected it
(the generated Methods text states that the reviewers worked independently; check that matches what you did).

Decisions imported from another tool are marked `imported` in the log, since their independence cannot be
verified.

## Changing the settings

```
strata config screening.blind_reviewers false      # not recommended for a review of record
strata config screening.blind_metadata true
```

`strata config` changes `strata.toml` but does not commit; commit the change (`git commit -am "settings:
blind metadata for the title screen"`) so that it is part of the shared history. Changing blinding midway
through a review is a methods change; record why. Related: [Screening](Screening),
[Adjudication and agreement](Adjudication-and-Agreement).
