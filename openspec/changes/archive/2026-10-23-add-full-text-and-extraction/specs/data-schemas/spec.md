# data-schemas Specification Delta

## MODIFIED Requirements

### Requirement: Project manifest

`strata.toml` MUST carry `schema_version`, `created_with`, a `[project]` table
(`id`, `title`, `slug`, `created`, optional `registry`, and a data `license`),
an `[[actors]]` array (`handle`, `name`, `email`, optional `orcid`, `role` of
`lead | screener | extractor | adjudicator | observer | inactive`), and the
`[screening]`, `[screening.assignment]`, `[extraction]`, `[dedup]`, `[git]`,
`[enrichment]`, and `[analysis]` tables. It MUST enforce:

- `actors[].handle` matches `^[a-z0-9][a-z0-9-]{0,31}$` and is unique.
- An actor who has authored an event MUST NOT be removed; they are set to
  `role = "inactive"` instead.
- `screening.mode = "dual"` with an assignment list of length 1 is a
  configuration error (`E_CONFIG`).
- `enrichment.enabled = true` with an empty `contact_email` is a configuration
  error.
- `extraction.mode`, when present, is `single` or `dual`; it defaults to
  `single`, and risk-of-bias assessments follow the same mode.

#### Scenario: Invalid actor handle

- **WHEN** an actor is added with handle `Ethan G`
- **THEN** it is rejected because it does not match the handle pattern

#### Scenario: Removing an actor with history

- **GIVEN** actor `sam` has authored screening events
- **WHEN** a user tries to remove `sam`
- **THEN** removal is refused and `strata actor deactivate` is offered instead

#### Scenario: Dual screening with one reviewer

- **WHEN** `mode = "dual"` and `"title-abstract" = ["ethan"]`
- **THEN** configuration validation fails with `E_CONFIG`

#### Scenario: Unknown extraction mode

- **WHEN** `strata.toml` sets `[extraction] mode = "triple"`
- **THEN** loading the manifest fails with `E_SCHEMA`
