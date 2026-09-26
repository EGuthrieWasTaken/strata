# literature-import Specification Delta

## ADDED Requirements

### Requirement: Migration imports from incumbent tools

`strata import` MUST accept exports from Covidence, Rayyan, and EPPI-Reviewer,
providing an explicit migration path off those tools. Screening decisions
carried in such exports MUST be attributed to a declared actor and marked
`imported: true`, because their independence cannot be verified.

_Source: `docs/spec/15-roadmap.md` M6; `docs/spec/10-cli.md` §5_

#### Scenario: Migrating a Rayyan project

- **WHEN** a Rayyan export with include/exclude labels is imported
- **THEN** its records are imported with provenance and its decisions are recorded as `imported: true`
