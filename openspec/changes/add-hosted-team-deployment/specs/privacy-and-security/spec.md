# privacy-and-security Specification Delta

## MODIFIED Requirements

### Requirement: Offline by default

With `enrichment.enabled = false` (the default), `strata` MUST make no network
request except those the user explicitly initiates (`strata sync`, which talks
only to the configured git remote) and, on a hosted instance, those its operator
configured: the projects' git remotes and the identity provider.

#### Scenario: Import without enrichment

- **WHEN** an export is imported with enrichment disabled
- **THEN** no network request is made

#### Scenario: Hosted instance traffic

- **GIVEN** a hosted instance with GitHub remotes and no identity provider configured
- **WHEN** it runs for a day with enrichment disabled
- **THEN** every outbound connection it made was to a configured git remote

### Requirement: No stored credentials

A local `strata` install MUST NOT store credentials; git remote authentication
is delegated entirely to the user's git credential helper or SSH agent. A hosted
instance MUST store only the credentials it needs to operate (password hashes,
project remote credentials, identity-provider secrets), only in instance state,
and never in a review repository.

#### Scenario: Sync to a private remote

- **WHEN** a local `strata sync` pushes to a private remote
- **THEN** authentication is handled by git's configured helper and nothing is written to the repository or `strata.toml`

#### Scenario: Hosted instance credentials

- **WHEN** a hosted instance's data volume and every project repository are searched for plaintext passwords or remote tokens
- **THEN** none is found in any project repository, and instance state holds only hashes or encrypted values
