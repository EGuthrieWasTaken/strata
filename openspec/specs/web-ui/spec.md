# web-ui Specification

## Purpose

`strata serve`, the strictly local web interface that is the primary surface for
screening, adjudication, and criteria editing: its screens, the screening
surface requirements, the criteria editor's non-mutating impact preview, its
technology constraints, accessibility, and localhost security model.

Rationale and worked examples: [design.md](design.md).

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

#### Scenario: Record detail

- **WHEN** a user opens `/records/<id>`
- **THEN** the record's provenance timeline matches `strata why <id>`

### Requirement: Screening surface requirements

The web screening surface MUST meet:

| # | Requirement |
|---|---|
| S1 | Every action has a single-key shortcut; the pointer is never required |
| S2 | A decision is visibly acknowledged in under 100 ms; persistence is asynchronous but append-before-advance |
| S3 | A digit ticks or unticks the reason with that number and never records a decision; `e` records the exclusion with the reasons ticked. Reasons are numbered as `strata screen` numbers them |
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
| S15 | A skipped record is offered again once the others are decided; the screen never says nothing is left while a record assigned to the reviewer is undecided |
| S16 | The position shown counts decisions made: a skipped record is not counted as done, and a record being decided again is one already counted |
| S17 | A decision that is refused is answered on the same screen, with the record, the place in the queue, the reasons ticked and the note kept |

#### Scenario: Repeated undo

- **WHEN** a reviewer presses `u` three times after three decisions
- **THEN** three correcting events are appended and all three records are undecided again

#### Scenario: Same order for two reviewers

- **WHEN** two reviewers open the same stage's queue with the same recorded ordering
- **THEN** they see records in the same order

#### Scenario: A stray digit

- **GIVEN** a review that requires a reason for every exclusion
- **WHEN** a reviewer presses `2` on the screening screen and nothing else
- **THEN** the second reason is ticked and no decision is recorded

#### Scenario: Exclude with nothing ticked

- **GIVEN** a review that requires a reason for every exclusion
- **WHEN** a reviewer presses `e` with no reason ticked
- **THEN** nothing is recorded and the screen says to tick a reason first, in place

#### Scenario: A skipped record comes back

- **GIVEN** a reviewer skipped one record and decided the rest
- **WHEN** the queue has nothing else left
- **THEN** the skipped record is shown again, and the screen says these are the records that were skipped

### Requirement: Re-screening mode

The re-screening screen MUST be identical to the screening surface, with the
prior decision and the staleness reason displayed prominently and a fourth
action, keep previous.

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

### Requirement: Extraction and risk-of-bias screens

The web UI MUST provide:

| Route | Purpose |
|---|---|
| `/extract/<study>` | The coding form |
| `/extract/<study>/reconcile` | Field-by-field reconciliation |
| `/rob/<study>` | Risk-of-bias instrument |

These screens MUST meet the same keyboard, accessibility, and security
requirements as the screening surface, and the coding form MUST make entering a
source locator a single keystroke.

#### Scenario: Reconciling in the browser

- **WHEN** a reconciler resolves a disagreement at `/extract/<study>/reconcile`
- **THEN** a `reconcile` event is recorded exactly as the CLI would record it

### Requirement: A session cookie of the server's own

A server's session cookie MUST be named so that another `strata` server reached on the same host
name does not replace it: `strata serve` names it after the port a browser reaches it on (the public
URL's port when one is configured), and a hosted instance on a port other than its scheme's default
does the same for its session, sign-in and sign-in-provider state cookies. A request refused for want
of a session MUST be told what to do (open the address the server printed).

#### Scenario: Two reviews open at once

- **GIVEN** two `strata serve` processes on `127.0.0.1`, on different ports, both opened in one browser
- **WHEN** the reviewer goes back to the first by a plain path
- **THEN** the page is served: the second server's cookie did not replace the first's

### Requirement: Shown in the reviewer's words

What the interface shows a reviewer MUST be written for a reviewer:

- A refused action says what is wrong and what to do. A setting name, a stored code, an error code or
  an identity MAY follow as a visually secondary line for whoever has to look it up, and MUST NOT be
  the message.
- A count is labelled with what it counts. Where two counts could be taken for each other (the records
  with a stale decision in the review, and one reviewer's own stale decisions; the records imported, and
  the distinct records left after duplicates are merged), each MUST say which it is.
- History and a record's provenance say who did what, when, and why: the reason recorded with the
  change, and its date. Provenance is written as sentences, with no event names or stored keys.
- An assignment is visible after it is made: who is assigned how many records at the stage, and the
  assignments that were made.
- An analysis that reads as current says what it is current against, and says so when a screening
  decision behind its studies is stale.

#### Scenario: An exclusion with no reason

- **WHEN** an exclusion is refused because no reason was ticked
- **THEN** the page says to tick at least one reason, and names the setting only in a secondary line

#### Scenario: A correction in the timeline

- **GIVEN** a record whose title was corrected with a reason
- **WHEN** its page is opened
- **THEN** the timeline says who corrected the title, from what to what, when, and gives the reason

#### Scenario: Stale counts

- **GIVEN** a two-reviewer review in which a criterion was tightened
- **WHEN** a reviewer looks at the dashboard and at the re-screening screen
- **THEN** the dashboard's count is labelled as records for the whole review, the re-screening screen's as the reviewer's own decisions, and each says the other can differ
