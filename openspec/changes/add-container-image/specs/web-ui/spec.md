# web-ui Specification Delta

## ADDED Requirements

### Requirement: Configurable public URL

`strata serve` MUST accept a public URL (`--public-url`, or `STRATA_PUBLIC_URL`)
naming the scheme, host, and port a browser uses to reach the server. When one
is given, `Host` and `Origin` validation MUST accept exactly that host and
origin instead of values derived from the bind address; when none is given,
validation MUST behave as it does today. Requests whose `Host` or `Origin` do not
match MUST still be rejected.

#### Scenario: Behind a published port

- **GIVEN** the server binds `0.0.0.0:8765` in a container with `--public-url http://localhost:8765`
- **WHEN** a browser sends `Host: localhost:8765`
- **THEN** the request is accepted

#### Scenario: DNS rebinding still refused

- **GIVEN** the same server
- **WHEN** a request arrives with `Host: attacker.example:8765`
- **THEN** it is rejected

### Requirement: Health endpoint

The server MUST expose `GET /healthz`, which requires no session, returns HTTP
200 while the server can read its repository, and returns no repository data.

#### Scenario: Unauthenticated probe

- **WHEN** `/healthz` is requested without a session cookie or token
- **THEN** the response is 200 with a body containing only a status indicator
