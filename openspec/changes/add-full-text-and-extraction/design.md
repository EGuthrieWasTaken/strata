# Design: Full text, study grouping, and data extraction

## Context

M0–M2 shipped the event log, identity, screening, and staleness. Reports,
studies, and effects exist in the domain model (`domain-model` spec) and their
event types are catalogued (`event-log` spec), but nothing yet produces them.
The full reasoning behind each decision below is in
`docs/spec/07-workflow-extraction.md`.

## Goals / Non-Goals

**Goals:**

- A complete review can be conducted through to an analysis-ready dataset.
- Every extracted value can answer "where did this number come from?".
- Dual extraction reconciliation records every decision.

**Non-Goals:**

- Storing or redistributing PDFs (see `copyright-and-licensing`).
- Automatic study grouping — heuristics only suggest.
- Pooling or effect-size inference beyond displaying the computed effect while
  typing (M4).

## Decisions

- **Identify documents by identifier and version, never by content hash.**
  Annotating a PDF changes its bytes without changing the document, so a hash
  check would report disagreement between two copies of the same paper in the
  ordinary case. `version` plus a per-version `locator` is both more robust and
  more informative. A `sha256` MAY be recorded as advisory metadata only.
- **Adding a required extraction field makes prior extractions incomplete, not
  stale.** Missing data is reported and queued (`strata extract --missing`)
  rather than invalidating completed work.
- **Store entered and normalised quantity values together.** "1 week" alone is
  unanalysable; 168 hours alone is unverifiable against the paper.
- **Data-quality guards warn, never block**, and acknowledgements are recorded
  so they are auditable and do not nag.
- **RoB is structurally identical to extraction** (instrument, per-reviewer
  assessment, reconciliation, consensus) and is specified separately only
  because the instruments are standardised and shipped.

## Risks / Trade-offs

- RoB 2 and ROBINS-I licence terms must be checked before shipping their
  definitions (`copyright-and-licensing`).
- The GRIM/statcheck-style consistency check can produce false alarms on
  rounded reporting; it is a warning with an acknowledgement path for this
  reason.
