# Spec Delta

## ADDED Requirements

### Requirement: AI participation commands

The CLI MUST provide `strata ai enable`, `strata ai policy [KIND [MODE]]`, `strata ai revoke AGENT`,
`strata ai report`, `strata suggestions list|show|adopt|reject`, `strata audit --ai`, `strata migrate`,
`strata actor add --kind agent --model MODEL`, and `strata mcp --as HANDLE [--allow-dir DIR]`. Each that
changes a review MUST require a rationale.

#### Scenario: Showing the policy

- **WHEN** `strata ai policy` runs with no arguments
- **THEN** it lists every kind of work with its mode and says whether AI participation is enabled

#### Scenario: Setting a mode

- **WHEN** `strata --why "Piloting AI suggestions on screening" ai policy screening suggest` runs
- **THEN** the mode is recorded in one commit with `Strata-Op: ai-policy`

#### Scenario: AI not enabled

- **GIVEN** AI participation is not enabled
- **WHEN** `strata ai policy screening suggest` runs
- **THEN** it exits with a usage error that names `strata ai enable`

#### Scenario: Adopting a suggestion

- **GIVEN** a pending screening suggestion `ev_01j...`
- **WHEN** `strata --why "Agree: meets the population criterion" suggestions adopt ev_01j...` runs as an active screener
- **THEN** the operation is recorded as that person's and the suggestion is marked adopted

#### Scenario: Listing as JSON

- **WHEN** `strata --json suggestions list` runs
- **THEN** it prints the pending suggestions, each with the model as reported, the person who invoked the agent, the operation and the target

#### Scenario: Reserved commands stay reserved

- **WHEN** any `strata ai` command or `strata actor add` is invoked
- **THEN** it is a command-line action only, and no MCP tool performs it
