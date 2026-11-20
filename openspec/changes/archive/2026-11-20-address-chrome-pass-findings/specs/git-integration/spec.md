# git-integration Specification Delta

## MODIFIED Requirements

### Requirement: Batched screening commits

Screening decisions MUST be appended to the event log immediately but committed
in batches, one batch per reviewer: a commit is created when the user ends a
session, when 200 decisions accumulate, or after 15 minutes of inactivity,
whichever comes first. A batch gets a generated summary message and MUST NOT
wait for a prompt.

In the web interface a session ends when the reviewer presses Finish session,
requests any page other than the screening and re-screening screens, or the
server stops (an interrupt, or the inactivity exit). `strata serve` MUST also
commit, when it starts, the decisions an earlier server recorded and did not
commit. A reviewer's pending batch MUST be committed before any other operation
commits, so that it is never part of another commit.

A decision that changes the same reviewer's earlier decision for the record at
the stage MUST carry a rationale. The web interface MUST ask for it when the
decision is made and refuse the decision without it; the rationale is recorded
in the event (its note) and the batch's message MUST list each changed decision
with it. A changed decision that reaches the log without one (written by an
older version) MUST still be committed, listed as having no reason recorded.

#### Scenario: 200 decisions

- **WHEN** a reviewer records their 200th uncommitted decision
- **THEN** a commit is created with a generated message such as `screen(title-abstract): screen 200 records (183 exclude, 17 include)`

#### Scenario: Batch contains a change of mind

- **GIVEN** a record a reviewer previously decided `include`
- **WHEN** the reviewer decides it `exclude` in the browser without a reason
- **THEN** the decision is refused and the page asks why it changed
- **AND WHEN** the reviewer gives a reason and the batch is committed
- **THEN** the commit message lists the record, `include -> exclude`, and the reason

#### Scenario: Leaving the screening screen

- **GIVEN** a reviewer has recorded decisions in the browser that are not committed
- **WHEN** they open the dashboard
- **THEN** the decisions are committed as one batch under their name before the page is drawn, and the working tree is clean

#### Scenario: A server that was killed

- **GIVEN** screening decisions on disk that a killed `strata serve` never committed
- **WHEN** `strata serve` starts again
- **THEN** it commits them, as a batch of their reviewer's own, before it serves a page
