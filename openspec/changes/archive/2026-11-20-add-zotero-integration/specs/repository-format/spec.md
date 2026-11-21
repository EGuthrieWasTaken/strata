# repository-format Specification Delta

## ADDED Requirements

### Requirement: The integrations directory

`strata` MUST create a review's `integrations/` directory only when a reference
manager is linked, holding one append-only, committed mapping file per manager
(`integrations/zotero.ndjson`). It is authoritative, but optional: a review
without it is complete, and no core workflow reads it.

#### Scenario: A review never linked to Zotero

- **WHEN** a review has never run `strata zotero link`
- **THEN** it has no `integrations/` directory, and `strata verify` reports nothing about one
