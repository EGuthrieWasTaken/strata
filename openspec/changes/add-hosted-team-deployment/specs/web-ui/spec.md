# web-ui Specification Delta

## MODIFIED Requirements

### Requirement: Strictly local

By default, `strata serve` MUST run in local mode: it MUST bind to `127.0.0.1`
on an ephemeral port and open a browser. Binding to any other interface MUST
require both `--host` and `--token`, and MUST print a warning explaining the
exposure. In local mode there MUST be no account system, login, or
multi-tenancy: the person at the keyboard is a configured actor, selectable at
startup when several are configured. The only exception is hosted mode
(`strata host`), which is started explicitly and is governed by the
`hosted-deployment` capability. In every mode, data MUST NOT leave the machine
except to the configured git remotes and, in hosted mode, the configured
identity provider: no CDN, analytics, third-party fonts, or error reporting. The
server MUST be stateless with respect to the repository, reading and appending
to the same event log the CLI uses.

#### Scenario: Default bind

- **WHEN** `strata serve` starts without options
- **THEN** it listens only on `127.0.0.1`

#### Scenario: Non-local bind without a token

- **WHEN** `strata serve --host 0.0.0.0` is run without `--token`
- **THEN** it refuses to start

#### Scenario: Screen in the browser, commit from the terminal

- **GIVEN** decisions recorded in the web UI
- **WHEN** the user runs a CLI command against the same repository
- **THEN** the CLI sees those decisions with no conflict

#### Scenario: Hosted mode is explicit

- **WHEN** `strata serve` is run with any combination of options
- **THEN** it never offers sign-in or serves more than one repository; that requires `strata host`
