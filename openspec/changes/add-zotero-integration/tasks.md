# Tasks

## 1. Boundary and transports

- [ ] 1.1 Define the generic `ReferenceManager` interface (resolve, pull, push, open)
- [ ] 1.2 Implement the local HTTP API client with capability probing
- [ ] 1.3 Implement the Web API v3 client with `Backoff`/`Retry-After` handling
- [ ] 1.4 Store API keys via `keyring`; fall back to an environment variable with a not-persisted notice

## 2. Identity mapping

- [ ] 2.1 Write `integrations/zotero.ndjson` matching items by the canonical-key ladder
- [ ] 2.2 Report unmatched items; degrade stale links to "full text unavailable"

## 3. Commands

- [ ] 3.1 `strata zotero link` (detect, authenticate, choose library, check write permission)
- [ ] 3.2 `strata zotero pull --collection ... --search ...` as an import source with `--via`
- [ ] 3.3 `strata zotero push --set included --collection ...` with optimistic concurrency
- [ ] 3.4 `strata zotero status` and `strata zotero open <record-id>`

## 4. Retrieval

- [ ] 4.1 Resolve attachments in the retrieval queue and record the item key in the manifest

## 5. Tests

- [ ] 5.1 Integration tests pinned per Zotero major version
- [ ] 5.2 A test that core workflows run with Zotero absent
- [ ] 5.3 A test that a push never deletes or overwrites an item `strata` did not create
