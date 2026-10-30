# Spec Delta

## ADDED Requirements

### Requirement: Search and import screens

The web UI MUST provide `/searches`, `/searches/new`, `/searches/<id>` and `/import`. Each action on them MUST record exactly what `strata search add` or `strata import` records for the same input, and a search MUST be recorded with the date it was run, defaulting to today.

#### Scenario: Record a search and attach its export

- **GIVEN** a signed-in actor `ada` and an RIS file exported from MEDLINE
- **WHEN** she submits `/searches/new` with database `MEDLINE`, platform `Ovid`, the query, a rationale, and the file, and then confirms the review of the file
- **THEN** `protocol/searches/S-01-medline.yaml` exists with `executed` set to today and `export_files` naming the file
- **AND** the raw file is stored under `imports/<id>/raw/` and its records are in the pool
- **AND** the commits carry the same `Strata-Op`, `Strata-Search`, `Strata-Import` and `Strata-Actor` trailers the command line writes

#### Scenario: Record a search with no export yet

- **WHEN** a search is submitted with no query and no file
- **THEN** it is recorded with `query: "PENDING"` and flagged on `/searches`, on the dashboard and on its own page as missing its query (PRISMA item 7)

#### Scenario: Date of an earlier run

- **WHEN** a search is submitted with a date other than today
- **THEN** that date is recorded as `executed`

#### Scenario: Re-running a search

- **GIVEN** `S-01-medline`
- **WHEN** the person chooses to re-run it from its page
- **THEN** `/searches/new` is pre-filled from it, and saving creates a new search with `supersedes: "S-01-medline"`
- **AND** `S-01-medline.yaml` is unchanged

#### Scenario: Notices lead somewhere

- **GIVEN** a search with no export imported yet, and another recorded without its query
- **WHEN** the dashboard is shown
- **THEN** one notice names the first and another names the second, and each name links to that search's page, where a file can be added

### Requirement: Review before importing

Nothing uploaded MUST be imported until the person has seen, for each file, what would happen (the detected format, rows read, records that would be new or matched, and rows rejected with their reasons) and confirmed. Review MUST NOT change the repository.

#### Scenario: Review shows the dry run

- **WHEN** a file is uploaded to a search
- **THEN** the review shows what `strata import --dry-run` reports for that file
- **AND** `git status` shows no change in the repository

#### Scenario: Confirm imports each file separately

- **WHEN** two files are uploaded together and confirmed
- **THEN** each is its own import and its own commit, as with the command line

#### Scenario: Same file twice

- **GIVEN** a file already imported
- **WHEN** it is uploaded again
- **THEN** the review says it was already imported, names the earlier import, and confirming makes no change and no commit

#### Scenario: Rejected rows are listed

- **GIVEN** an export in which three rows cannot be used
- **WHEN** it is reviewed
- **THEN** each rejected row is listed with its reason and the rest are offered for import

#### Scenario: Columns not recognised

- **GIVEN** a CSV whose columns match no known platform
- **WHEN** it is reviewed
- **THEN** the person must map the title, authors and identifier columns before the file can be confirmed, and the chosen mapping is applied as `--map` would apply it

#### Scenario: Workbook with several sheets

- **WHEN** an Excel workbook with several sheets is reviewed
- **THEN** the person chooses the sheet, and the first is preselected

#### Scenario: File that cannot be imported

- **GIVEN** a search was recorded together with a file whose content cannot be read, such as a corrupt workbook
- **WHEN** the file is reviewed
- **THEN** the reason is shown and the file cannot be confirmed
- **AND** the search stays recorded, as it would after `strata search add` followed by a failed `strata import`

#### Scenario: File that is not an export at all

- **WHEN** a search is submitted with a file `strata import` would not recognise as an export, such as a PDF
- **THEN** the whole submission is refused with the reason, and no search is recorded and nothing is kept

### Requirement: Imports from other methods

`/import` MUST import an upload that did not come from a database search, taking one of the methods `strata import --via` accepts, and the records MUST be counted under that method in the PRISMA numbers.

#### Scenario: Registry results

- **WHEN** a file is imported at `/import` with the method `registry`
- **THEN** the records are counted as found through registries, as with `strata import --via registry`

#### Scenario: Neither a search nor a method

- **WHEN** an import is submitted naming no search and no method
- **THEN** it is refused for the reason `strata import` gives and nothing is recorded

### Requirement: Correcting a record

`/records/<id>` MUST let a person correct an editable metadata field with a rationale, recording exactly what `strata fix` records. A field that `strata fix` refuses MUST be refused with the same reason.

#### Scenario: Fixing a title

- **WHEN** a person corrects the title of a record with a rationale
- **THEN** a `record-amend` event is recorded and `/records/<id>` shows the old and new values in its provenance timeline

#### Scenario: Field that is not editable

- **WHEN** a request names a field `strata fix` does not allow, such as `id`
- **THEN** it is refused with the reason `strata fix` gives and nothing is recorded

### Requirement: Adding a criterion

`/criteria` MUST let a person add a criterion with its kind, label, definition, the stages it applies at, and a rationale, recording exactly what `strata criteria add` records, and MUST state before saving that a new criterion is recorded as `tightened`.

#### Scenario: Adding an exclusion criterion

- **WHEN** an exclusion criterion is added at title/abstract with a rationale
- **THEN** a `criteria-add` event is recorded and the criteria version advances
- **AND** the effect on existing decisions is exactly what `strata criteria add` produces for the same criterion

#### Scenario: Missing rationale

- **WHEN** the form is submitted without a rationale
- **THEN** it is refused and `protocol/criteria.yaml` is unchanged

### Requirement: Assigning reviewers

`/assign/<stage>` MUST let a person assign configured actors to the records at a stage, optionally limited by a filter expression, recording exactly what `strata assign` records.

#### Scenario: Assign two reviewers to all records

- **WHEN** two actors are assigned to every record at title/abstract
- **THEN** the assignment is recorded as `strata assign` would record it and both actors' screening queues contain the records

#### Scenario: Bad filter

- **WHEN** the filter expression does not parse
- **THEN** the page shows the parser's message and nothing is recorded

### Requirement: Full-text retrieval screen

`/retrieve` MUST list the reports sought for retrieval and let a person record an outcome, source, version and reason for each, recording exactly what `strata retrieve` records. It MUST NOT accept a file or a path on the server.

#### Scenario: Recording a retrieved report

- **WHEN** an outcome of `retrieved` with a source and a version is recorded for a report
- **THEN** the same retrieval event the command line writes is appended and the report leaves the outstanding list

#### Scenario: Not retrieved needs a reason

- **WHEN** an outcome of `not-retrieved` is submitted without a reason
- **THEN** it is refused for the reason `strata retrieve` gives and nothing is recorded

#### Scenario: No file field

- **WHEN** `/retrieve` is viewed
- **THEN** it offers no control for uploading a document

### Requirement: Study grouping screen

`/studies` MUST show the included reports grouped into studies with the suggestions `strata studies` shows and their evidence, and MUST let a person group or split reports with a rationale, recording exactly what `strata studies` records. A suggestion MUST NOT be applied without a person choosing it.

#### Scenario: Accepting a suggestion

- **GIVEN** two reports with a shared trial registration number are suggested as one study
- **WHEN** a person accepts the suggestion with a rationale
- **THEN** a grouping decision is recorded and the study count falls by one

#### Scenario: Nothing is applied automatically

- **WHEN** `/studies` is viewed and left
- **THEN** no event is recorded

#### Scenario: Splitting a report

- **WHEN** a person splits a report into two studies with a rationale
- **THEN** the split is recorded as `strata studies --split` would record it

### Requirement: Write screens match the command line

Every web screen that records something MUST call the same operation as the command it mirrors, so that the same inputs on identical repositories produce the same events, files and commit messages apart from ids and timestamps.

#### Scenario: One search from two surfaces

- **GIVEN** two identical repositories
- **WHEN** the same search is recorded once with `strata search add` and once at `/searches/new`
- **THEN** the search files are byte-identical and the commit messages and trailers are identical

#### Scenario: One import from two surfaces

- **GIVEN** two identical repositories and the same export file
- **WHEN** it is imported once with `strata import` and once through the web UI
- **THEN** the records, import manifests, events and derived counts are identical apart from ids and timestamps

### Requirement: Rationale on every write screen

A form that records something MUST ask for a rationale wherever the command line requires one, and MUST refuse a missing or rejected rationale before writing anything.

#### Scenario: Missing rationale

- **GIVEN** `git.require_rationale` is set
- **WHEN** a search is submitted with no rationale
- **THEN** it is refused, nothing is written, and `strata status` reports a clean working tree

#### Scenario: Rationale that is not one

- **WHEN** the rationale is `update`
- **THEN** it is refused with the message the command line gives for it

#### Scenario: Rationale optional

- **GIVEN** `git.require_rationale` is false
- **WHEN** a search is submitted with no rationale
- **THEN** it is recorded and the commit has no body

### Requirement: Drag and drop is an enhancement

Choosing files for upload MUST work with an ordinary file control, by keyboard, and with JavaScript disabled. Dragging files onto the control MAY be offered in addition, and MUST announce the files it has taken, show its state in text as well as colour, and respect reduced-motion preferences.

#### Scenario: JavaScript disabled

- **WHEN** a search and its export are submitted with JavaScript disabled
- **THEN** each step completes through a full page load

#### Scenario: Keyboard only

- **WHEN** a person uses only the keyboard
- **THEN** they can reach the file control, choose files, and submit

#### Scenario: Dropping files

- **WHEN** a person drops two files onto the drop target
- **THEN** both are attached to the form, a live region announces their names and sizes, and the form is submitted by the same button as without drag and drop

#### Scenario: Dropping something that is not a file

- **WHEN** selected text or a folder is dropped
- **THEN** it is ignored and the drop target says so
