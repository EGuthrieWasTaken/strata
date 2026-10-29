# Spec Delta

## ADDED Requirements

### Requirement: Assignment names real reviewers

`strata assign` MUST refuse a handle that is not an active actor of the review (one that was never added, or has been deactivated), MUST name every handle it refused, and MUST list the actors who can be assigned. It MUST write nothing when it refuses, with or without `--no-commit`.

#### Scenario: A handle that is not an actor

- **GIVEN** a review whose active actors are `ethan` and `sam`
- **WHEN** `strata assign title-abstract --actors ethan,ghost --by ethan` runs
- **THEN** it exits with a usage error saying it cannot assign `ghost` because it is not an actor of the review, and that the eligible actors are `ethan` and `sam`
- **AND** no assignment is recorded for `ethan` either

#### Scenario: An actor who has been deactivated

- **GIVEN** `sam` has been deactivated
- **WHEN** `strata assign title-abstract --actors sam --by ethan` runs
- **THEN** it says `sam` has been deactivated and lists only the actors who are still active

#### Scenario: The web form offers the same actors

- **WHEN** the assignment screen is shown
- **THEN** the reviewers it offers are exactly the eligible actors, and a request naming anyone else is refused with the same message

### Requirement: Correcting a record

`strata fix` MUST correct the plain-text fields, the authors and the date of a record, and MUST refuse any other field, naming the fields it can correct. It MUST store a DOI, PMID, PMCID or ISBN as an import stores it, MUST remove a field when given an empty value (except the title), and MUST read authors as `Family, Given; Family, Given` and a date as `YYYY`, `YYYY-MM` or `YYYY-MM-DD`. A value the record already has MUST change nothing, record nothing, and ask for no rationale.

#### Scenario: Correcting the year

- **GIVEN** a record published `2008-03`
- **WHEN** `strata fix <id> --field year --value 2009` runs
- **THEN** the record's date is `2009-03`, a `record-amend` event for `issued` records the old and new date, and `derived/pool.tsv` shows 2009

#### Scenario: Correcting the authors

- **WHEN** `strata fix <id> --field author --value "Cepeda, Nicholas J.; Vul, Edward"` runs
- **THEN** the record has two authors with family and given names, and `strata why` shows the old and new authors as text

#### Scenario: A value the record already has

- **WHEN** `strata fix` is run, with no rationale, for a value the record already has
- **THEN** it reports that nothing changed, exits successfully, writes no event and makes no commit

#### Scenario: A value that does not fit

- **WHEN** `strata fix <id> --field year --value nineteen` runs
- **THEN** it exits with a usage error saying a year is four digits, and writes nothing

#### Scenario: A field that is not metadata

- **WHEN** `strata fix <id> --field id --value x` runs
- **THEN** it exits with a usage error that lists the fields it can correct, and writes nothing
