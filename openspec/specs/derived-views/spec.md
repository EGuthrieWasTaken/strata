# derived-views Specification

## Purpose

The generated, committed, human-diffable views under `derived/` — the candidate
pool, open conflicts, stale decisions, PRISMA counts, and inter-rater
reliability. They exist so a reviewer can read in a `git diff` what a change did
to the review; they are never read back as input.

Rationale: `docs/spec/02-repository-format.md` §6.

## Requirements

### Requirement: Candidate pool view

`derived/pool.tsv` MUST have one row per **canonical** record (absorbed records
do not appear), sorted by `record_id`, with columns in this order:

```
record_id  tiab  fulltext  stale  year  first_author  title  journal  doi
```

- `tiab`, `fulltext`: the screening state per stage.
- `stale`: `-`, `tiab`, `ft`, or `tiab,ft`.
- `title`: truncated to 120 characters with a trailing `…` if truncated.

_Source: `docs/spec/02-repository-format.md` §6.1_

#### Scenario: Long title

- **WHEN** a canonical record has a 200-character title
- **THEN** its `pool.tsv` title is the first 120 characters followed by `…`

#### Scenario: Absorbed record

- **GIVEN** a record absorbed by deduplication
- **WHEN** `pool.tsv` is regenerated
- **THEN** it has no row for the absorbed record

#### Scenario: Stale at both stages

- **WHEN** a record's title-abstract and full-text decisions are both stale
- **THEN** its `stale` column is `tiab,ft`

### Requirement: PRISMA counts view

`derived/counts.json` MUST hold every count PRISMA needs, derived from the event
log, together with the reconciliation assertions that prove the funnel is
internally consistent.

_Source: `docs/spec/02-repository-format.md` §6.2_

#### Scenario: Counts regenerated after screening

- **WHEN** screening decisions are committed
- **THEN** `derived/counts.json` is regenerated from the event log with no hand-entered numbers

### Requirement: Conflicts view

`derived/conflicts.tsv` MUST list open screening disagreements with columns

```
record_id  stage  opinions  criteria_cited  first_seen  title
```

where `opinions` is e.g. `ethan=include;sam=exclude`, sorted by
`(stage, record_id)`.

_Source: `docs/spec/02-repository-format.md` §6.3_

#### Scenario: New disagreement

- **WHEN** `ethan` includes and `sam` excludes the same record
- **THEN** `conflicts.tsv` contains a row with `opinions` `ethan=include;sam=exclude`

### Requirement: Stale decisions view

`derived/stale.tsv` MUST list decisions invalidated by protocol change with
columns

```
record_id  stage  prior_decision  prior_criteria  reason  since_version  title
```

where `reason` is one of the defined staleness causes, sorted by
`(stage, record_id)`.

_Source: `docs/spec/02-repository-format.md` §6.4_

#### Scenario: Inclusion invalidated by a new criterion

- **WHEN** a new exclusion criterion applying at title-abstract is added at version 4
- **THEN** each previously included record appears in `stale.tsv` with `reason` `criterion-added` and `since_version` 4

### Requirement: Inter-rater reliability view

`derived/irr.json` MUST report, per stage and per reviewer pair, raw agreement,
Cohen's kappa, PABAK, the 2x2 table, and the count of records both reviewers
screened. It MUST be computed over independent first opinions only; an opinion
changed after seeing the other reviewer's decision MUST be excluded.

_Source: `docs/spec/02-repository-format.md` §6.5_

#### Scenario: Opinion changed after adjudication discussion

- **GIVEN** `sam` first excluded a record and later changed to include
- **WHEN** `irr.json` is regenerated
- **THEN** `sam`'s opinion for that record counts as `exclude` in the agreement statistics
