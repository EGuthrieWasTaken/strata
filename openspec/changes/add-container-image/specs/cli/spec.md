# cli Specification Delta

## ADDED Requirements

### Requirement: Serve behind a public URL

`strata serve` MUST accept `--public-url URL` (also read from
`STRATA_PUBLIC_URL`), and MUST exit with a usage error (code 2) when the value is
not an absolute `http` or `https` URL.

#### Scenario: Invalid public URL

- **WHEN** `strata serve --public-url localhost` runs
- **THEN** it exits with code 2 explaining that a scheme is required
