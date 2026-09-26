# zotero-integration Specification

## Purpose

An optional integration in which Zotero owns the documents and `strata` owns
the decisions: pulling collections as import sources, resolving full texts,
pushing included studies for citation, and mapping identities between the two
systems without ever letting either overwrite the other's domain.

## ADDED Requirements

### Requirement: Optional and isolated

`strata` MUST remain fully functional with Zotero absent and MUST NOT make
Zotero a dependency of any core workflow. The integration MUST sit behind a
generic `ReferenceManager` boundary (resolve, pull, push, open) so another
reference manager is a plugin rather than a rewrite.

#### Scenario: Zotero not installed

- **WHEN** a user screens, extracts, and analyses without Zotero installed
- **THEN** no command fails or warns because Zotero is missing

### Requirement: Transport selection

The client MUST prefer Zotero's local HTTP API on `127.0.0.1:23119`, MUST probe
its capabilities rather than assume a shape, and MUST degrade to the Web API v3
(`api.zotero.org`) on mismatch or when group libraries require it.

#### Scenario: Desktop app running

- **WHEN** `strata zotero link` runs while Zotero desktop is running with a compatible local API
- **THEN** the local API is used and no API key is requested

### Requirement: API keys are never stored in the repository

A Web API key MUST be stored in the operating system keychain via `keyring`,
never in `strata.toml` or the repository. If no keychain is available, `strata`
MUST read the key from an environment variable and MUST say that it is not being
persisted.

#### Scenario: No keychain

- **GIVEN** a system with no available keychain
- **WHEN** the user links a group library
- **THEN** the key is read from the environment, a not-persisted notice is shown, and nothing is written to disk

### Requirement: Identity mapping

`integrations/zotero.ndjson` MUST map records to Zotero items (`record`,
`library`, `item_key`, `item_version`, `linked`, `via`), matching by the same
canonical-key ladder as record identity (DOI, then PMID, then the
title/year/first-author signature). Items matching nothing above the dedup
review threshold MUST be reported, never guessed. A stale `item_key` MUST
degrade to "full text unavailable", never to an error that blocks screening.

#### Scenario: Item deleted in Zotero

- **GIVEN** a mapped item that was deleted in Zotero
- **WHEN** the record is opened for screening
- **THEN** screening proceeds and the full text is reported unavailable

### Requirement: Append-only meets mutable

Every pull that changes a record MUST write ordinary `record-amend` events.
`strata` MUST NOT delete or overwrite a Zotero item it did not create; pushes
create or update, never remove. Zotero's per-item `version` MUST be used for
optimistic concurrency: a push that would clobber a newer server version is
refused and reported. Conflicts MUST resolve in favour of Zotero for
bibliographic metadata and `strata` for anything decision-shaped.

#### Scenario: Newer server version

- **GIVEN** an item edited in Zotero after `strata` last saw it
- **WHEN** `strata zotero push` would update it
- **THEN** the push of that item is refused and reported

#### Scenario: Title corrected in Zotero

- **WHEN** a pull brings a corrected title for a mapped record
- **THEN** a `record-amend` event records the change

### Requirement: Commands

`strata` MUST provide `zotero link`, `zotero pull --collection C --search S`,
`zotero push --set included --collection C`, `zotero status` (mapped, unmapped,
and stale links), and `zotero open <record-id>`. A pull MUST behave as an import
source: it requires a `--search` id, records the collection name and pull date
for PRISMA reporting, and MUST be tagged with the correct `--via` (a hand-built
collection is other-methods, not a database search).

#### Scenario: Pulling a hand-built collection

- **WHEN** a manually curated collection is pulled
- **THEN** its records are counted in the other-methods column of the flow diagram

### Requirement: Retrieval through Zotero

When a Zotero link exists, the retrieval queue MUST show whether an attachment
is present and offer to open it in Zotero, and the manifest entry MUST record
the Zotero item key alongside the DOI instead of a local path.

#### Scenario: Attachment present

- **WHEN** a report with a Zotero PDF attachment is reached in `strata retrieve`
- **THEN** the user can open it in Zotero, and the manifest records the DOI and item key
