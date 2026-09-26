# web-ui Specification Delta

## ADDED Requirements

### Requirement: Live flow diagram screen

The web UI MUST provide `/prisma`, rendering the current flow diagram from the
event log, with the DRAFT watermark while any decision is stale.

#### Scenario: Diagram updates after screening

- **WHEN** decisions are recorded and `/prisma` is reloaded
- **THEN** the diagram reflects the new counts
