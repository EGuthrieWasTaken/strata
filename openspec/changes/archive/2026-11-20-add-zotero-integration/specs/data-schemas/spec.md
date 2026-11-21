# data-schemas Specification Delta

## ADDED Requirements

### Requirement: Reference-manager fields

The import manifest, a full-text manifest entry and `strata.toml` MUST each be
able to record a link to a reference manager through a closed object in its
schema, and none of these objects MAY hold an API key.

#### Scenario: A pull records its collection

- **WHEN** `strata zotero pull` imports a collection
- **THEN** the import manifest has a `collection` object (`manager`, `library`, `key`, `name`) and the pull date is its `imported`

#### Scenario: A full text held in Zotero

- **WHEN** a report's full text is recorded as held in Zotero
- **THEN** its full-text manifest entry has a `zotero` object (`library`, `item_key`) instead of a local path

#### Scenario: A key in the manifest is refused

- **WHEN** `strata.toml` has a `[zotero]` table with a `key` entry
- **THEN** validation of the manifest fails, because the table admits only `library`, `transport` (`auto`, `local` or `web`) and `write`
