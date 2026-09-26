# Design: Reporting and PRISMA

## Context

Every count and date needed for reporting already exists in the event log and
the `Strata-` commit trailers (`event-log`, `git-integration` specs). What is
missing is the generator. Full reasoning: `docs/spec/09-reporting.md`.

## Goals / Non-Goals

**Goals:**

- A flow diagram whose arithmetic always closes, or a loud failure naming the
  broken identity.
- Methods text a methodologist judges publishable without correction.
- Item 24c (protocol amendments) generated truthfully from the history.

**Non-Goals:**

- PRISMA extensions (PRISMA-S, PRISMA-ScR, PRISMA-IPD) — post-1.0.
- GRADE certainty assessment (item 22) — flagged as author work.
- Any generated Discussion or Conclusion.

## Decisions

- **Counts are derived, never typed**, and the generator asserts every
  reconciliation identity rather than trusting the arithmetic.
- **`marked_ineligible_by_automation` exists at 0 in v1** because the PRISMA
  2020 diagram has a box for it and adding a field later would be a schema bump.
- **Generated prose is a draft for the author**, marked with its commit hash,
  and never makes causal or significance claims; guardrail caveats are
  carried into the text automatically.
- **The line is held at Methods and Results** (`docs/spec/16-open-questions.md`
  Q8): a Discussion is an argument, and a tool that drafts arguments makes the
  literature worse.

## Risks / Trade-offs

- PRISMA box labels and checklist wording reproduced from memory may differ
  from the official template; verification against prisma-statement.org is a
  release task.
