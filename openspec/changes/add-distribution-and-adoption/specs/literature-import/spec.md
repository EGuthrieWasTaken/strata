# literature-import Specification Delta

## ADDED Requirements

### Requirement: Migration imports from incumbent tools

`strata import` MUST accept exports from Covidence, Rayyan, and EPPI-Reviewer,
providing an explicit migration path off those tools. Screening decisions
carried in such exports MUST be attributed to a declared actor and marked
`imported: true`, because their independence cannot be verified.

#### Scenario: Migrating a Rayyan project

- **WHEN** a Rayyan export with include/exclude labels is imported
- **THEN** its records are imported with provenance and its decisions are recorded as `imported: true`

### Requirement: Workbook and best-effort formats

`strata import` MUST read an `.xlsx` workbook without evaluating anything in it: from the first
sheet, or the sheet named by `--sheet` (a name or a position), with the cached value of a formula
standing in for the formula, and MUST refuse a workbook that exceeds fixed limits on file size,
unpacked size, rows, columns or cell length, that declares XML entities, or that is encrypted or a
legacy `.xls`, naming the reason. The sheet is then mapped like a TSV export, and the manifest
records the sheet that was read.

A format whose fields can only be inferred (a plain-text citation list) MUST mark every record it
creates with the `best-effort-parse` flag in `strata.flags`, and deduplication MUST NOT merge a
flagged record automatically: a pair involving one goes to the review queue however well it scores.

#### Scenario: Second sheet of a workbook

- **WHEN** `strata import export.xlsx --sheet Other --map title=Title` is run on a workbook with two sheets
- **THEN** only the sheet named `Other` is imported and the manifest names it

#### Scenario: A workbook that is a zip bomb

- **WHEN** an `.xlsx` whose parts expand beyond the limit is imported
- **THEN** the import is refused with a message naming the limit and nothing is written

#### Scenario: Duplicate of a citation-list record

- **GIVEN** a record from a plain-text citation list and another record that scores 1.0 against it
- **WHEN** deduplication runs
- **THEN** the pair is in the review queue and neither record is absorbed

