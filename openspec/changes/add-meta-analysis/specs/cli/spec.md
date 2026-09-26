# cli Specification Delta

## ADDED Requirements

### Requirement: Analysis commands

`strata` MUST provide `strata analyze [<id>] [--all]` (run analysis
specifications, writing `analysis/results/<id>/`) and `strata analyze --check`
(validate specifications and report guardrails without computing). Blocking
guardrails MUST exit with code 8 unless `--force` is given.

_Source: `docs/spec/10-cli.md` §2_

#### Scenario: Check without computing

- **WHEN** `strata analyze --check` runs
- **THEN** it reports specification errors and guardrails and writes no results
