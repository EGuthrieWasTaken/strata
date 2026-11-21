# web-ui Specification Delta

## MODIFIED Requirements

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

## ADDED Requirements

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
