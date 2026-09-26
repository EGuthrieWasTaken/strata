# cli Specification Delta

## ADDED Requirements

### Requirement: Reporting and export commands

`strata` MUST provide:

| Command | Description |
|---|---|
| `strata prisma [--format F] [--columns one\|both] [--allow-stale]` | Flow diagram |
| `strata report <section>` | `methods`, `results`, `characteristics`, `amendments`, `checklist`, `rob`, `manuscript` |
| `strata export <what> --format F` | `effects`, `records`, `bibliography`, `package` |

_Source: `docs/spec/10-cli.md` §2_

#### Scenario: Unknown report section

- **WHEN** `strata report discussion` runs
- **THEN** it exits with a usage error listing the supported sections
