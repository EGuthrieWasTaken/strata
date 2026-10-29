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
