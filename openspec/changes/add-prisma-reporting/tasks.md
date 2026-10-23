# Tasks

## 1. Counts

- [x] 1.1 Generate `derived/counts.json` including `marked_ineligible_by_automation` and per-`via` partitions
- [x] 1.2 Assert every reconciliation identity and fail with `E_COUNT_RECONCILE` naming the violated one

## 2. Flow diagram and checklist

- [x] 2.1 Implement `strata prisma --format svg|pdf|png|json --columns one|both`
- [x] 2.2 Emit the `PRISMA2020` R package input shape
- [x] 2.3 Collapse beyond six exclusion reasons and emit the full table alongside
- [x] 2.4 Require `--allow-stale` and watermark drafts while any decision is stale
- [x] 2.5 Regenerate and byte-compare the diagram in `strata verify`
- [x] 2.6 Implement `strata report checklist [--status]` with the three item states
- [ ] 2.7 Verify all labels and wording against the official PRISMA 2020 materials; add CC BY 4.0 attribution

## 3. Manuscript sections

- [x] 3.1 Implement `strata report methods|results|characteristics|amendments|rob`
- [x] 3.2 Implement `strata report manuscript --format docx|latex|md|html` via pandoc
- [x] 3.3 Enforce the generated-prose rules (commit hash, precision, no causal or significance language, guardrail caveats, no Discussion)
- [x] 3.4 Add conflict-of-interest and funding metadata to `strata.toml` (items 25–26)

## 4. Exports

- [x] 4.1 Implement `strata export bibliography --format bibtex|csl|ris --set ...`
- [x] 4.2 Implement `strata export package`, containing no full texts and including the data licence

## 5. Surfaces

- [x] 5.1 Add the CLI commands and their `--json` output
- [x] 5.2 Add the live `/prisma` web screen

## 6. Tests (suite additions, docs/roadmap.md M5)

- [x] 6.1 Property test P11 over randomly generated review histories
- [x] 6.2 E2E-03 end to end
- [x] 6.3 A check that the reproducibility package contains no full texts
- [ ] 6.4 Methodologist review of generated Methods text (manual release gate)

## Notes

- 2.7 is partly done. The flow-diagram labels were compared with the template that ships in the
  `PRISMA2020` R package (its `data` keys and box labels), and the output carries the CC BY 4.0
  attribution. The 27-item checklist wording could not be compared with the official template from
  the build environment, so the generated checklist says in its header that the wording is not yet
  verified (`WORDING_VERIFIED = False` in `report/checklist.py`). Compare it with
  https://www.prisma-statement.org/ and flip the flag.
- 6.4 is a manual release gate: a methodologist reads the generated Methods text. It has not been done.
- 2.5: `strata verify` regenerates `reports/prisma.svg` in both column layouts and warns
  (`W_DIAGRAM_STALE`) when the committed file matches neither, since a diagram is out of date after
  any later decision until it is drawn again.
