# portability-and-i18n Specification

## Purpose

Cross-platform support (Linux, macOS, Windows) with the platform pitfalls that
must be handled, Unicode throughout, and internationalisation rules for strings,
dates, and decimal separators.

Rationale and worked examples: [design.md](design.md).

## Requirements

### Requirement: Supported platforms

`strata` MUST support Linux, macOS (Intel and Apple Silicon), and Windows 10+,
all tested in CI on every commit. Git 2.23+ MUST be required and checked by
`strata doctor`.

#### Scenario: Old git

- **WHEN** `strata doctor` runs with git 2.20 installed
- **THEN** it reports that git 2.23 or newer is required

### Requirement: Windows pitfalls are handled

`strata` MUST handle path length limits (extended paths or short generated
paths), `CRLF` from `core.autocrlf` (forced to LF via `.gitattributes`),
case-insensitive filesystems (never relying on two paths differing only by
case), and reserved filenames (`CON`, `PRN`, `NUL`, `AUX`), which no record id
or study slug may ever become.

#### Scenario: Checkout with autocrlf

- **GIVEN** a Windows user with `core.autocrlf = true`
- **WHEN** they clone a review repository
- **THEN** event files are checked out with LF endings and verify cleanly

### Requirement: Unicode throughout

Non-Latin author names, titles, and abstracts MUST be handled as ordinary
input. Filenames derived from user data MUST be sanitised, and ids MUST be
restricted to `[a-z0-9_]`. Nothing in the UI may assume English or left-to-right
text.

#### Scenario: CJK title

- **WHEN** a record with a Japanese title is imported, screened, and displayed
- **THEN** the title round-trips unchanged and displays correctly

### Requirement: Internationalisation

All user-facing strings MUST be externalised, even though only English ships
initially. Dates in output MUST be ISO 8601; dates in prose follow the locale.
Numbers in generated files MUST always use `.` as the decimal separator;
numbers in displayed prose follow the locale. Import MUST detect and handle
`,`-decimal CSVs.

#### Scenario: European CSV

- **WHEN** a CSV export using `,` as its decimal separator is imported
- **THEN** numeric fields are parsed correctly

#### Scenario: Generated file under a German locale

- **WHEN** derived files are generated with a `de_DE` locale active
- **THEN** every number uses `.` as the decimal separator
