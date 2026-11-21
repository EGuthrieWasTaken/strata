# git-integration Specification Delta

## ADDED Requirements

### Requirement: Integration mapping files merge by union

The `.gitattributes` of a review linked to a reference manager MUST give
`integrations/*.ndjson` the `merge=union` driver, added by the first link if
`strata init` did not write it, so that two collaborators linking at once never
conflict: a changed link is a new row, never an edited one.

#### Scenario: Two people link at once

- **GIVEN** two clones that each ran `strata zotero link` and appended rows to `integrations/zotero.ndjson`
- **WHEN** one merges the other's branch
- **THEN** the file holds both sets of rows and the merge does not conflict
