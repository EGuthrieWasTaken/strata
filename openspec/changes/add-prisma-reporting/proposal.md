# Proposal: Reporting and PRISMA (M5)

## Why

A review's output is a manuscript, and large parts of it — the flow diagram,
the checklist, Methods, Results, the characteristics table, and above all the
protocol-amendment section — are mechanically derivable from what the
repository already knows. Transcribing them by hand is a documented source of
mismatch between what a review says it did and what it did. M5 generates them
from the event log and commit trailers, and `1.0.0` ships here.

Roadmap milestone: M5 (`docs/spec/15-roadmap.md`). Design detail:
`docs/spec/09-reporting.md`.

## What Changes

- `derived/counts.json` with enforced reconciliation identities
  (`E_COUNT_RECONCILE`).
- The PRISMA 2020 flow diagram (`strata prisma`), one- and two-column, in SVG,
  PDF, PNG, and JSON (including the `PRISMA2020` R package input shape).
- The 27-item checklist with auto-filled, auto-located, and author states.
- Generated Methods, Results, characteristics, and amendments sections, and
  manuscript export via pandoc, under strict rules for generated prose.
- Bibliography export by set, and the reproducibility package.
- Conflict-of-interest and funding metadata in `strata.toml` (open question Q7).

## Capabilities

### New Capabilities

- `prisma-reporting`: counts and reconciliation, the flow diagram, and the
  checklist.
- `manuscript-generation`: generated manuscript sections and their prose
  rules, bibliography export, and the reproducibility package.

### Modified Capabilities

- `cli`: adds the reporting and export command group.
- `web-ui`: adds the live flow-diagram screen.

## Impact

- New module: `strata/report/` (flow, checklist, prose, exports).
- Adds a pandoc dependency for manuscript export (optional at runtime).
- The PRISMA 2020 wording must be verified against the official template before
  shipping; generated output carries the CC BY 4.0 attribution.
- Property test P11 (count reconciliation) and E2E-03 become gates.
