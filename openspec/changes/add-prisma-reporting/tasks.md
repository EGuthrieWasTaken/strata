# Tasks

## 1. Counts

- [ ] 1.1 Generate `derived/counts.json` including `marked_ineligible_by_automation` and per-`via` partitions
- [ ] 1.2 Assert every reconciliation identity and fail with `E_COUNT_RECONCILE` naming the violated one

## 2. Flow diagram and checklist

- [ ] 2.1 Implement `strata prisma --format svg|pdf|png|json --columns one|both`
- [ ] 2.2 Emit the `PRISMA2020` R package input shape
- [ ] 2.3 Collapse beyond six exclusion reasons and emit the full table alongside
- [ ] 2.4 Require `--allow-stale` and watermark drafts while any decision is stale
- [ ] 2.5 Regenerate and byte-compare the diagram in `strata verify`
- [ ] 2.6 Implement `strata report checklist [--status]` with the three item states
- [ ] 2.7 Verify all labels and wording against the official PRISMA 2020 materials; add CC BY 4.0 attribution

## 3. Manuscript sections

- [ ] 3.1 Implement `strata report methods|results|characteristics|amendments|rob`
- [ ] 3.2 Implement `strata report manuscript --format docx|latex|md|html` via pandoc
- [ ] 3.3 Enforce the generated-prose rules (commit hash, precision, no causal or significance language, guardrail caveats, no Discussion)
- [ ] 3.4 Add conflict-of-interest and funding metadata to `strata.toml` (items 25–26)

## 4. Exports

- [ ] 4.1 Implement `strata export bibliography --format bibtex|csl|ris --set ...`
- [ ] 4.2 Implement `strata export package`, containing no full texts and including the data licence

## 5. Surfaces

- [ ] 5.1 Add the CLI commands and their `--json` output
- [ ] 5.2 Add the live `/prisma` web screen

## 6. Tests (suite additions, `docs/spec/15-roadmap.md` M5)

- [ ] 6.1 Property test P11 over randomly generated review histories
- [ ] 6.2 E2E-03 end to end
- [ ] 6.3 A check that the reproducibility package contains no full texts
- [ ] 6.4 Methodologist review of generated Methods text (manual release gate)
