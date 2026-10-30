# Spec Delta

## ADDED Requirements

### Requirement: Agent actors and AI settings

An `[[actors]]` entry MAY have `kind` of `human` (the default) or `agent`. An agent entry MUST have a
`model` and MUST NOT have the role `lead`; a human entry MUST NOT have a `model`. The manifest MAY carry
`[ai]` (`enabled`, and `show_suggestions` of `after-own-decision`, the default, or `always`) and
`[ai.policy]` (one mode per kind of work).

#### Scenario: Agent without a model

- **WHEN** an actor with `kind = "agent"` has no `model`
- **THEN** configuration validation fails with `E_CONFIG`

#### Scenario: Person with a model

- **WHEN** an actor with no `kind` has a `model`
- **THEN** configuration validation fails with `E_CONFIG`

#### Scenario: Policy without enabling

- **GIVEN** `[ai] enabled = false`
- **WHEN** `[ai.policy]` sets any kind of work to `suggest` or `count`
- **THEN** configuration validation fails with `E_CONFIG`

#### Scenario: Registering an agent before AI is enabled

- **GIVEN** `[ai]` is absent
- **WHEN** `strata actor add` is run with `--kind agent`
- **THEN** it is refused with a message naming `strata ai enable`

#### Scenario: Agent actor with history

- **GIVEN** an agent actor has authored events
- **WHEN** a user tries to remove it
- **THEN** removal is refused and `strata ai revoke` is offered
