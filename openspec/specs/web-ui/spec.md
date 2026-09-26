# web-ui Specification

## Purpose

`strata serve`, the strictly local web interface that is the primary surface for
screening, adjudication, and criteria editing: its screens, the screening
surface requirements, the criteria editor's non-mutating impact preview, its
technology constraints, accessibility, and localhost security model.

Rationale and wireframes: `docs/spec/11-web-ui.md`.

## Requirements

### Requirement: Strictly local

`strata serve` MUST bind to `127.0.0.1` on an ephemeral port by default and
open a browser. Binding to any other interface MUST require both `--host` and
`--token`, and MUST print a warning explaining the exposure. There MUST be no
account system, login, or multi-tenancy: the person at the keyboard is a
configured actor, selectable at startup when several are configured. Data MUST
NOT leave the machine: no CDN, analytics, third-party fonts, or error reporting.
The server MUST be stateless with respect to the repository, reading and
appending to the same event log the CLI uses.

_Source: `docs/spec/11-web-ui.md` §1_

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

### Requirement: Screens

The web UI MUST provide at least these screens:

| Route | Purpose |
|---|---|
| `/` | Dashboard — the `strata status` content, with actions as links |
| `/screen/<stage>` | The screening surface |
| `/rescreen/<stage>` | The stale queue, with prior decisions shown |
| `/adjudicate/<stage>` | Conflict resolution |
| `/dedup` | Duplicate review queue |
| `/records` | Searchable, filterable record table |
| `/records/<id>` | Record detail with the `strata why` provenance timeline |
| `/criteria` | Criteria editor, with live impact preview |
| `/history` | Domain-level history from commit trailers |

_Source: `docs/spec/11-web-ui.md` §2_

#### Scenario: Record detail

- **WHEN** a user opens `/records/<id>`
- **THEN** the record's provenance timeline matches `strata why <id>`

### Requirement: Screening surface requirements

The web screening surface MUST meet:

| # | Requirement |
|---|---|
| S1 | Every action has a single-key shortcut; the pointer is never required |
| S2 | A decision is visibly acknowledged in under 100 ms; persistence is asynchronous but append-before-advance |
| S3 | Exclusion with a criterion is one keystroke (`e` then a digit), or a digit alone when `require_exclusion_reason` is set |
| S4 | Multiple criteria may be cited on one exclusion |
| S5 | A criterion's full definition is shown on hover and on keyboard focus |
| S6 | User-configured terms are highlighted in title and abstract |
| S7 | `u` undoes the previous decision by appending a correcting event, repeatably |
| S8 | Closing the tab and returning resumes at the same record |
| S9 | Records with no abstract are visually flagged, never silently skipped |
| S10 | Another reviewer's decision is never shown while `blind_reviewers` is set |
| S11 | Author, journal, and year are hidden while `blind_metadata` is set |
| S12 | Works offline; no network request leaves the machine |
| S13 | A note can be attached to any record without leaving the keyboard |
| S14 | The queue order is deterministic and recorded |

_Source: `docs/spec/11-web-ui.md` §3.1_

#### Scenario: Repeated undo

- **WHEN** a reviewer presses `u` three times after three decisions
- **THEN** three correcting events are appended and all three records are undecided again

#### Scenario: Same order for two reviewers

- **WHEN** two reviewers open the same stage's queue with the same recorded ordering
- **THEN** they see records in the same order

### Requirement: Re-screening mode

The re-screening screen MUST be identical to the screening surface, with the
prior decision and the staleness reason displayed prominently and a fourth
action, keep previous.

_Source: `docs/spec/11-web-ui.md` §3.2_

#### Scenario: Keep previous in the browser

- **WHEN** a reviewer presses `k` on a stale record in `/rescreen/<stage>`
- **THEN** a fresh `screen` event with the prior decision at the current criteria version is appended

### Requirement: Criteria editor impact preview

The criteria editor MUST show a live impact preview (how many decisions would
become stale, broken down by reason, how many remain valid, and an estimated
re-screening time) together with the direction choice and a rationale field.
The preview MUST be computed without mutating anything, MUST update as the
direction changes, and MUST be recomputed on save in case the repository
changed underneath.

_Source: `docs/spec/11-web-ui.md` §4_

#### Scenario: Changing the direction radio

- **GIVEN** an edit to `EXC-03` with 42 exclusions citing it
- **WHEN** the user switches the direction from tightened to loosened
- **THEN** the preview updates to show 42 decisions becoming stale
- **AND** the repository is unchanged

#### Scenario: Repository changed before save

- **GIVEN** a collaborator's decisions were synced after the preview was shown
- **WHEN** the user saves
- **THEN** the impact is recomputed against the current repository

### Requirement: Technology

The web UI MUST be server-rendered HTML with progressive enhancement: no SPA
framework and no build step required to run from source. All assets MUST be
vendored into the package and a strict `Content-Security-Policy` with no
external origins MUST be sent. The UI MUST function with JavaScript disabled, at
reduced convenience. Total shipped JavaScript SHOULD stay under 50 KB
uncompressed.

_Source: `docs/spec/11-web-ui.md` §5_

#### Scenario: JavaScript disabled

- **WHEN** a reviewer screens with JavaScript disabled
- **THEN** each decision is recorded via a full page load and screening remains possible

#### Scenario: Content-Security-Policy

- **WHEN** any page is served
- **THEN** its `Content-Security-Policy` permits no external origins

### Requirement: Accessibility

The web UI MUST meet WCAG 2.1 Level AA, specifically: full keyboard operability
with a visible focus indicator on every control; semantic HTML and correct ARIA
roles; contrast of at least 4.5:1 for text and 3:1 for UI components; states
never conveyed by colour alone (an icon and text label accompany colour); a
live region announcing each recorded decision; honouring
`prefers-reduced-motion` and `prefers-color-scheme`; and reflow to 320 px width
without horizontal scrolling, usable at 200% zoom.

_Source: `docs/spec/11-web-ui.md` §6_

#### Scenario: Screen reader user records a decision

- **WHEN** a decision is recorded
- **THEN** a live region announces it

#### Scenario: Conflict state display

- **WHEN** a record in conflict is listed
- **THEN** the state is shown with an icon and text label, not colour alone

### Requirement: Localhost security

Because any page in the user's browser can issue requests to `127.0.0.1`, the
server MUST:

- Generate a random session token at startup, required on every mutating
  request, delivered via the opened URL and stored in a `SameSite=Strict`,
  `HttpOnly` cookie.
- Accept mutations only via `POST`/`PUT`/`DELETE` carrying a CSRF token.
- Validate the `Origin` and `Host` headers on every request, defeating DNS
  rebinding.
- Escape all user-supplied content (titles, abstracts, notes) on output and
  never render raw HTML from record data.
- Resolve user-supplied file paths and check they are within permitted roots.
- Exit after 60 minutes of inactivity by default.

_Source: `docs/spec/11-web-ui.md` §7; `docs/spec/13-nonfunctional.md` §5_

#### Scenario: Cross-site request

- **WHEN** a request with a foreign `Origin` header attempts to record a decision
- **THEN** it is rejected

#### Scenario: DNS rebinding

- **WHEN** a request arrives with a `Host` header other than the bound local address
- **THEN** it is rejected

#### Scenario: Abstract containing HTML

- **GIVEN** an abstract containing `<script>alert(1)</script>`
- **WHEN** the record is displayed
- **THEN** the markup is escaped and not executed

#### Scenario: Idle server

- **WHEN** no request arrives for 60 minutes
- **THEN** the server exits
