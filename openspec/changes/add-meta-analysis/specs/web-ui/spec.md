# web-ui Specification Delta

## ADDED Requirements

### Requirement: Analysis results screen

The web UI MUST provide `/analysis/<id>`, showing an analysis's results, plots,
and guardrail warnings, served entirely from local assets.

#### Scenario: Guardrails visible

- **WHEN** a user opens `/analysis/primary` for an analysis whose run fired the `k < 10` guardrail
- **THEN** the warning is displayed alongside the results
