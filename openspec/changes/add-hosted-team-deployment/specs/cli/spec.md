# cli Specification Delta

## ADDED Requirements

### Requirement: Hosted instance commands

`strata` MUST provide a `host` command group for running and administering a
hosted instance:

| Command | Description |
|---|---|
| `strata host [--data DIR] [--public-url URL]` | Run the hosted instance |
| `strata host init [--data DIR]` | Initialise instance state and the first administrator |
| `strata host project add <id> [--remote URL]` | Add a project by cloning its remote, or initialise a new one |
| `strata host project list` | List projects with remote and last-sync status |
| `strata host user add\|disable <username>` | Manage local accounts |
| `strata host member add <project> <username> --actor HANDLE --role ROLE` | Map a user to an actor and role in a project |

These commands MUST operate on instance state only and MUST NOT write accounts,
memberships, or secrets into any review repository.

#### Scenario: Adding a member

- **WHEN** `strata host member add spacing sam.okonkwo --actor sam --role screener` runs
- **THEN** the membership is stored in instance state and the project's repository is unchanged

#### Scenario: Unknown actor

- **WHEN** a member is added with an actor handle absent from the project's `strata.toml`
- **THEN** the command fails with a usage error naming the missing handle
