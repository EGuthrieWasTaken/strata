# Spec Delta

## Purpose

How `strata serve` accepts files from a browser: the limits on what it will read, where an upload waits
before a person confirms it, how a client-supplied file name is treated, and which files it refuses. An
upload is the one place the web UI reads bytes an attacker could choose, so it is specified on its own.

## ADDED Requirements

### Requirement: Upload limits

Every route that accepts a file MUST enforce a maximum request size, a maximum number of files per
request, and a maximum size for each non-file form field, before the body is parsed and before any byte
is written to disk. The default request size is 100 MB and MUST be adjustable with
`strata serve --max-upload-mb`. A request over a limit, or one that declares no length, MUST be refused
with a message naming the limit.

#### Scenario: Request over the size limit

- **GIVEN** the default limit
- **WHEN** a browser submits a 150 MB file to an upload route
- **THEN** the request is refused with a message naming the 100 MB limit
- **AND** nothing is written under `.strata/tmp/` or anywhere else in the repository

#### Scenario: Request that declares no length

- **WHEN** an upload arrives with chunked transfer encoding and no content length
- **THEN** it is refused with a message that the size could not be checked

#### Scenario: Too many files

- **WHEN** a single request carries more files than the per-request limit
- **THEN** it is refused and nothing is staged

#### Scenario: Limit raised

- **GIVEN** the server was started with `--max-upload-mb 300`
- **WHEN** a browser submits a 150 MB file
- **THEN** the request is accepted for review

### Requirement: Security checks come first

An upload request MUST pass the session, `Host`, `Origin`, and size checks before its body is read, and
the CSRF check before anything is staged. A request that fails any check MUST leave no file and no
staging directory behind.

#### Scenario: Foreign origin

- **WHEN** an upload carries an `Origin` header that does not name this server
- **THEN** it is refused before its body is read

#### Scenario: No session

- **WHEN** an upload arrives without the session cookie or token
- **THEN** it is refused and nothing is staged

#### Scenario: Missing CSRF token

- **GIVEN** a valid session
- **WHEN** an upload arrives without the CSRF token
- **THEN** it is refused and nothing is staged

### Requirement: File names are not trusted

A name supplied by the browser MUST be used only as a display label and, once sanitised, as the stored
file name. It MUST NOT form any part of a path outside its staging directory. Path separators, control
characters, leading dots, and reserved device names MUST be removed or replaced, a name that sanitises to
nothing MUST be given a generated one, and two files with one name in a request MUST both be kept.

#### Scenario: Traversal in the name

- **WHEN** a file is uploaded as `../../protocol/criteria.yaml`
- **THEN** it is staged as a file named `criteria.yaml` inside its own batch directory
- **AND** `protocol/criteria.yaml` is unchanged

#### Scenario: Reserved or empty name

- **WHEN** a file is uploaded as `CON.ris`, or as a name made only of dots and separators
- **THEN** it is staged under a safe name that keeps the extension where it had one

#### Scenario: Two files with one name

- **WHEN** two files named `export.ris` are uploaded together
- **THEN** both are staged under different names and both are offered for review

### Requirement: Staged until confirmed

An uploaded file MUST NOT reach the repository's tracked tree until a person confirms it. Until then it
MUST live under `.strata/tmp/` in a directory named by a server-generated batch id that cannot be guessed.
Confirming and discarding MUST refer to a batch by that id and never by a path, and an id that is
malformed, unknown, or expired MUST be refused.

#### Scenario: Review, then confirm

- **WHEN** a file is uploaded and the person confirms the review
- **THEN** the file is imported from its staging directory and the batch is removed

#### Scenario: Discard

- **WHEN** the person discards a reviewed upload
- **THEN** the batch is removed and the repository is unchanged

#### Scenario: Forged batch reference

- **WHEN** a confirmation names a batch id containing a path separator, or one the server never issued
- **THEN** it is refused and no file outside the staging area is read

### Requirement: Staged files expire

Staged files MUST be deleted when their batch is confirmed or discarded, when `strata serve` starts, and
when they are more than an hour old. They MUST never be committed.

#### Scenario: Server restart

- **GIVEN** a batch was uploaded and never confirmed
- **WHEN** `strata serve` is started again
- **THEN** the batch no longer exists

#### Scenario: Old batch

- **GIVEN** a batch that was staged more than an hour ago
- **WHEN** its confirmation is submitted
- **THEN** it is refused as expired and the person is asked to upload the file again

#### Scenario: Working tree stays clean

- **WHEN** a file is staged and not yet confirmed
- **THEN** `strata status` reports the working tree as clean

### Requirement: Only bibliographic exports

The literature upload screens MUST accept only the formats `strata import` accepts
(`openspec:literature-import#supported-import-formats`), recognised by the same detection the command
line uses and not by the content type the browser declares. A PDF or other document MUST be refused
with an explanation that `strata` does not store full texts.

#### Scenario: A PDF dropped on a search

- **WHEN** a PDF is uploaded to a search
- **THEN** it is refused, the message says full texts are tracked by identifier and not stored, and nothing is staged

#### Scenario: Browser mislabels a real export

- **WHEN** a valid RIS file is uploaded with a declared content type of `application/pdf`
- **THEN** it is accepted for review, because detection reads the file

#### Scenario: Same answer as the command line

- **GIVEN** a file `strata import` rejects as an unsupported format
- **WHEN** it is uploaded to the web UI
- **THEN** the web UI refuses it with the same reason
