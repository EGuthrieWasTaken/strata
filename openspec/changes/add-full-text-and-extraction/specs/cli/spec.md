# cli Specification Delta

## ADDED Requirements

### Requirement: Full-text and extraction commands

`strata` MUST provide:

| Command | Description |
|---|---|
| `strata retrieve` | Work the retrieval queue |
| `strata studies` | Group reports into studies; suggest groupings and splits |
| `strata extract init` | Generate a draft coding form from the protocol |
| `strata extract [<study>] [--missing]` | Extract data |
| `strata extract --reconcile [<study>]` | Reconcile dual extractions |
| `strata rob [<study>]` | Risk-of-bias assessment |
| `strata export effects --format F` | Export one row per effect for outside analysis |

#### Scenario: Queue of missing data

- **WHEN** `strata extract --missing` runs
- **THEN** it queues exactly the studies with missing required values
