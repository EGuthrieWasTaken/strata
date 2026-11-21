# cli Specification Delta

## ADDED Requirements

### Requirement: Hosted instance commands

`strata` MUST provide a `host` command group for running and administering a
hosted instance:

| Command | Description |
|---|---|
| `strata host [--data DIR] [--public-url URL]` | Run the hosted instance |
| `strata host init [--data DIR]` | Initialise instance state and the first administrator |
| `strata host project add <id> [--remote URL] [--host-key LINE ...]` | Add a project by cloning its remote, or initialise a new one; with `--host-key`, pin the remote's SSH host key, and print the fingerprint of the key the clone accepted |
| `strata host project host-key <id> [--host-key LINE ...] [--clear]` | Show, pin or unpin a project's SSH host key |
| `strata host project list` | List projects with remote and last-sync status, and which are unavailable |
| `strata host user add\|disable <username>` | Manage local accounts |
| `strata host member add <project> <username> --actor HANDLE --role ROLE` | Map a user to an actor and role in a project |
| `strata host token add <username> --project ID [--days N]` | Make an API token that reads one project and expires, after 90 days unless `--days` says (1 to 365); shown once |
| `strata host audit [--limit N]` | Show who changed memberships and tokens, newest first |

These commands MUST operate on instance state only and MUST NOT write accounts,
memberships, or secrets into any review repository.

#### Scenario: Adding a member

- **WHEN** `strata host member add spacing sam.okonkwo --actor sam --role screener` runs
- **THEN** the membership is stored in instance state and the project's repository is unchanged

#### Scenario: Unknown actor

- **WHEN** a member is added with an actor handle absent from the project's `strata.toml`
- **THEN** the command fails with a usage error naming the missing handle

#### Scenario: A token needs a project its owner belongs to

- **WHEN** `strata host token add` is run without `--project`, for a project the user is not a member of, or with `--days` over 365 or under 1
- **THEN** it fails with a usage error, makes no token, and says how to fix it

#### Scenario: Pinning at add

- **WHEN** `strata host project add spacing --remote git@host:review.git --host-key 'host ssh-ed25519 AAAA…'` runs
- **THEN** the project is cloned believing only that key, and the command prints the key's fingerprint
