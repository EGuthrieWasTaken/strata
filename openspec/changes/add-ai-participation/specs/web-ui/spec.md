# Spec Delta

## ADDED Requirements

### Requirement: Suggestions screen

`/suggestions` MUST list pending suggestions with the kind of work, the target, the agent's rationale, the
model as the agent reported it and the person who invoked it, and MUST let a person adopt or reject each
with a rationale, recording exactly what `strata suggestions adopt` or `reject` records. It MUST honour
the blinding rules of `openspec:ai-suggestions#suggestions-respect-blinding`.

#### Scenario: Adopting in the browser

- **WHEN** a screener adopts a pending suggestion with a rationale
- **THEN** their own opinion is recorded and the suggestion leaves the pending list

#### Scenario: Not yet decided

- **GIVEN** `blind_reviewers` is set and the reviewer has not decided a record
- **WHEN** they open `/suggestions`
- **THEN** suggestions about that record are not listed

#### Scenario: Rejecting without a reason

- **WHEN** a suggestion is rejected with no reason
- **THEN** the form is refused and the suggestion stays pending

### Requirement: Agent work is labelled

Wherever the UI shows an event, decision, opinion or commit by an agent, it MUST label it with an icon and
the words "AI", the model as reported, and the person who invoked it, never by colour alone. The
dashboard MUST show whether AI participation is enabled and the policy in force.

#### Scenario: Record timeline

- **WHEN** a record's timeline includes a decision by an agent
- **THEN** that entry shows the AI label, the reported model and the invoking person

#### Scenario: Adjudication

- **GIVEN** a conflict between a person and an agent
- **WHEN** the adjudicator opens it
- **THEN** each opinion is labelled as a person's or an AI's

#### Scenario: Dashboard

- **GIVEN** screening is `suggest`
- **WHEN** the dashboard is shown
- **THEN** it says AI participation is on and links to the pending suggestions
