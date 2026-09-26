# Proposal: Zotero integration (M6)

## Why

`strata` deliberately refuses to store PDFs and identifies documents by DOI,
which leaves a hole exactly the shape of Zotero: holding the documents, citing
while writing, and shared group libraries. Integrating with Zotero removes the
last practical reason to keep a parallel folder of PDFs, and reaches users
where they already are.

> **Zotero owns the documents. `strata` owns the decisions.**

Roadmap milestone: M6 (`docs/spec/15-roadmap.md`). Design detail:
`docs/spec/17-zotero-integration.md`.

## What Changes

- `strata zotero link|pull|push|status|open`.
- Local HTTP API transport (preferred) with capability probing and fallback to
  Web API v3; API keys only in the OS keychain.
- A committed identity mapping `integrations/zotero.ndjson` using the record
  canonical-key ladder.
- Zotero collections as an import source (with `--search` and `--via`), and
  included studies pushed to a collection for citation.
- The retrieval queue resolves full texts through Zotero when linked.
- A generic `ReferenceManager` boundary so other managers are plugins.

## Capabilities

### New Capabilities

- `zotero-integration`: transports, credential handling, identity mapping,
  pull/push semantics, retrieval through Zotero, and the generic
  reference-manager boundary.

### Modified Capabilities

(none — Zotero is optional; every existing workflow is unchanged without it)

## Impact

- New `integrations/` directory in review repositories.
- New optional dependency: `keyring`.
- Post-1.0 items (mirroring screening state as tags; annotations as extraction
  source locators) are out of scope for this change.
