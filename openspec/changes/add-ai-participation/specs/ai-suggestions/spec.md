# Spec Delta

## Purpose

How an agent's work is offered to a review without taking effect: a suggestion is validated as a real
write would be, changes nothing, and becomes part of the review only when a person adopts it, in which
case the person's own decision is recorded and linked to the idea it came from.

## ADDED Requirements

### Requirement: A suggestion changes nothing

A suggestion MUST be validated against the current state exactly as the real operation would be, and a
suggestion that the real operation would refuse MUST be refused. A recorded suggestion MUST NOT alter the
pool, record states, conflicts, PRISMA counts, derived views or staleness.

#### Scenario: Invalid suggestion

- **WHEN** an agent suggests excluding a record at full-text without citing a criterion
- **THEN** the suggestion is refused for the reason a real decision would be

#### Scenario: Valid suggestion

- **WHEN** an agent suggests including a record
- **THEN** a suggestion is recorded and `derived/` is byte-identical to before

### Requirement: What a suggestion records

A suggestion MUST record the operation, its exact arguments, the agent's rationale, the agent's identity as
every agent event does, and the criteria version it was made under. A suggestion for a criteria change
MUST also record the impact preview computed when it was made.

#### Scenario: Suggested criterion edit

- **WHEN** an agent suggests tightening `EXC-03`
- **THEN** the suggestion holds the proposed text and the count of decisions it would make stale

### Requirement: Adopting a suggestion

A person whose role permits the kind of work MUST be able to adopt a suggestion. Adoption MUST run the
operation as that person after validating it again against the current state, MUST require the person's
own rationale, and MUST record a link from the suggestion to the events it produced. The resulting events
MUST be the person's and MUST NOT carry the agent key.

#### Scenario: Adopting a screening suggestion

- **WHEN** `ada` adopts a suggestion that a record be included
- **THEN** a screening event by `ada` is recorded, the suggestion is marked adopted with a link to it, and `strata why` shows both

#### Scenario: State moved on

- **GIVEN** the criteria changed after the suggestion was made
- **WHEN** a person tries to adopt it
- **THEN** they are told what changed and may adopt it only by confirming against the current state

#### Scenario: Wrong role

- **WHEN** an observer tries to adopt a suggestion
- **THEN** it is refused

### Requirement: Rejecting a suggestion

A person MUST be able to reject a suggestion with a reason. A rejected suggestion MUST remain in the
record and in the ledger, and MUST NOT be offered again.

#### Scenario: Rejection

- **WHEN** a person rejects a suggestion with a reason
- **THEN** it is marked rejected with that reason and is no longer pending

### Requirement: A newer suggestion supersedes

A later suggestion from the same agent for the same operation and target MUST supersede an earlier
unresolved one, and only unresolved, unsuperseded suggestions MUST be pending.

#### Scenario: Agent changes its mind

- **WHEN** an agent suggests `include` and later `exclude` for one record
- **THEN** only the latter is pending and the former is shown as superseded

### Requirement: Suggestions respect blinding

While `blind_reviewers` is set, a suggestion about a record at a stage MUST NOT be shown to a reviewer
assigned to that record at that stage before they have recorded their own opinion, unless the review sets
`[ai] show_suggestions = "always"`. An opinion recorded after the reviewer saw a suggestion MUST be marked
as informed by it and excluded from agreement between independent reviewers.

#### Scenario: Default blinding

- **GIVEN** `blind_reviewers` is set and `show_suggestions` is not
- **WHEN** `ada` opens a record the agent has made a suggestion about, before deciding it
- **THEN** nothing on the screen indicates the suggestion

#### Scenario: After her own decision

- **WHEN** `ada` has recorded her opinion
- **THEN** the suggestion is available to her, and changing her opinion afterwards is treated like any change made after seeing another opinion

#### Scenario: AI-first reviews

- **GIVEN** `show_suggestions = "always"`
- **WHEN** `ada` adopts a suggestion before deciding
- **THEN** her opinion is marked as informed by it and is left out of independent agreement

### Requirement: Suggestions are in the ledger, not the counts

Suggestions and their outcomes MUST appear in the AI ledger and in generated disclosure, and MUST NOT
appear in PRISMA counts as decisions.

#### Scenario: Counts unaffected

- **GIVEN** 500 pending suggestions to exclude records
- **WHEN** `derived/counts.json` is regenerated
- **THEN** no record is counted as excluded because of them
