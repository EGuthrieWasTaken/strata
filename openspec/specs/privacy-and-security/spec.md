# privacy-and-security Specification

## Purpose

`strata`'s privacy posture (no telemetry, offline by default, opt-in and logged
enrichment, polite use of free scholarly APIs, no stored credentials) and its
threat model with mitigations for a local, single-user tool.

Rationale: `docs/spec/13-nonfunctional.md` §4–§5.

## Requirements

### Requirement: No telemetry

`strata` MUST NOT send telemetry of any kind: no anonymous usage statistics, no
crash reporting, no version check.

_Source: `docs/spec/13-nonfunctional.md` §4_

#### Scenario: Any command

- **WHEN** any `strata` command runs with default configuration
- **THEN** no network request is made to any project-controlled or third-party endpoint

### Requirement: Offline by default

With `enrichment.enabled = false` (the default), `strata` MUST make no network
request except those the user explicitly initiates (`strata sync`, which talks
only to the configured git remote).

_Source: `docs/spec/13-nonfunctional.md` §4_

#### Scenario: Import without enrichment

- **WHEN** an export is imported with enrichment disabled
- **THEN** no network request is made

### Requirement: Enrichment is opt-in, per provider, and logged

Enrichment MUST be enabled explicitly and per provider. When enabled, every
outbound request MUST be recorded in `.strata/network.log` with timestamp,
endpoint, and purpose.

_Source: `docs/spec/13-nonfunctional.md` §4_

#### Scenario: Crossref enrichment

- **GIVEN** `enrichment.enabled = true` with `providers = ["crossref"]`
- **WHEN** records are enriched
- **THEN** each request to Crossref is logged in `.strata/network.log` and no other provider is contacted

### Requirement: Polite API use

When calling Crossref, OpenAlex, PubMed, or Unpaywall, `strata` MUST send a
descriptive `User-Agent` including the configured `contact_email`, MUST respect
`Retry-After` and rate limits, MUST back off exponentially on 429/503, and MUST
cache responses locally keyed by DOI so a re-run does not re-query.

_Source: `docs/spec/13-nonfunctional.md` §4_

#### Scenario: Rate limited

- **WHEN** a provider responds 429 with `Retry-After: 30`
- **THEN** `strata` waits at least 30 seconds before retrying

#### Scenario: Re-run

- **WHEN** enrichment is re-run for DOIs already fetched
- **THEN** cached responses are used and no request is repeated

### Requirement: No stored credentials

`strata` MUST NOT store credentials; git remote authentication is delegated
entirely to the user's git credential helper or SSH agent.

_Source: `docs/spec/13-nonfunctional.md` §4_

#### Scenario: Sync to a private remote

- **WHEN** `strata sync` pushes to a private remote
- **THEN** authentication is handled by git's configured helper and nothing is written to the repository or `strata.toml`

### Requirement: Threat mitigations

`strata` MUST implement these mitigations:

| Threat | Mitigation |
|---|---|
| Malicious import file | Parsers are memory-bounded, never `eval`, and are fuzzed; XML parsing disables external entity resolution and DTD processing |
| Zip bomb / billion laughs in `.xlsx` or EndNote XML | Decompression ratio and absolute size caps enforced before parsing |
| Path traversal via a record field used in a filename | Ids are `[a-z0-9_]` only; user strings are never used as paths without sanitisation |
| Localhost server reachable from a web page | Origin/Host validation, session token, CSRF tokens, `SameSite=Strict` |
| XSS from an abstract containing HTML | Escape on output; never render raw HTML from record data |
| Regex denial of service in `--filter matches` | Linear-time engine or a hard timeout |
| Supply chain | Pinned, hash-locked dependencies; reproducible builds; signed release artefacts; a published SBOM |

Security issues MUST be reportable privately and fixed before disclosure.

_Source: `docs/spec/13-nonfunctional.md` §5_

#### Scenario: XML external entity

- **WHEN** an EndNote XML file declaring an external entity is imported
- **THEN** the entity is not resolved

#### Scenario: Record field as filename

- **WHEN** a record's title contains `../../etc/passwd`
- **THEN** no file path is derived from it without sanitisation
