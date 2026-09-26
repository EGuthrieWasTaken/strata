# adjudication Specification

## Purpose

Resolving screening conflicts between reviewers: who may adjudicate, how an
adjudication supersedes opinions without erasing them, the mandatory rationale,
and the "discuss" path that leaves a conflict open.

Rationale and worked examples: [design.md](design.md).

## Requirements

### Requirement: The adjudication queue

`strata adjudicate [--stage S]` MUST present each open conflict with the record
and every reviewer's opinion, date, cited criteria, and note, and offer
include, exclude, discuss, and skip.

#### Scenario: Conflict shown with both opinions

- **GIVEN** `ethan` included a record with a note and `sam` excluded it citing `EXC-04`
- **WHEN** the adjudicator opens it
- **THEN** both opinions, their dates, `EXC-04`, and both notes are displayed

### Requirement: Only adjudicators may resolve

Only actors with the `adjudicator` role or listed in `screening.adjudicators`
MUST be permitted to resolve a conflict.

#### Scenario: Screener attempts adjudication

- **GIVEN** `sam` has role `screener` and is not in `screening.adjudicators`
- **WHEN** `sam` runs `strata adjudicate`
- **THEN** the command refuses to record a resolution

### Requirement: Adjudication supersedes without erasing

An `adjudicate` event MUST supersede the conflicting opinions (listing them in
`supersedes[]`) without erasing them; the opinions remain in the log and IRR
still reflects the original disagreement.

#### Scenario: Resolving a conflict

- **WHEN** an adjudicator records `exclude` on a conflict
- **THEN** the record resolves to `exclude`, the adjudicate event lists both superseded opinion events, and both opinions remain in their files

### Requirement: Rationale is required

A rationale MUST be recorded for every adjudication.

#### Scenario: Adjudication without a rationale

- **WHEN** an adjudicator tries to resolve a conflict without a rationale
- **THEN** the resolution is refused

### Requirement: Self-adjudication is recorded

Adjudicating a record one did not screen MUST be allowed. Adjudicating one's
own conflict MUST be allowed but MUST be noted in the event, and generated
reports MUST count such adjudications.

#### Scenario: Lead adjudicates their own conflict

- **GIVEN** `ethan` is one of the two conflicting reviewers and an adjudicator
- **WHEN** `ethan` resolves the conflict
- **THEN** the adjudicate event notes that it is a self-adjudication

### Requirement: Discuss leaves the conflict open

The discuss action MUST record a `note` event on the record and leave the
conflict open.

#### Scenario: Deferring to a meeting

- **WHEN** an adjudicator presses `d` and enters "discuss at Tuesday meeting"
- **THEN** a `note` event is recorded and the record remains in `conflict`
