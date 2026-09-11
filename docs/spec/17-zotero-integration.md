# 17 — Zotero integration *(normative where marked; post-1.0 scope)*

## 1. Why this is the right integration to build

Zotero is free software, is already installed by a large share of the target
users, and is genuinely good at three jobs `epic` has deliberately declined to
do:

1. **Holding the PDFs.** Storage, sync, full-text indexing, and a built-in reader
   with highlights and notes. `epic` refuses to commit full texts
   ([13 §6](13-nonfunctional.md)) and identifies documents by DOI rather than by
   bytes ([07 §1.1](07-workflow-extraction.md)) — which leaves an obvious hole
   exactly the shape of Zotero.
2. **Citing while writing.** The Word, LibreOffice, and Google Docs plugins are
   how reviewers actually insert citations into a manuscript.
3. **Group libraries.** A shared, permissioned library that a team may already be
   using for the project.

The division of labour is clean, and worth stating as the design principle:

> **Zotero owns the documents. `epic` owns the decisions.**

`epic` never stores a PDF; Zotero never stores a screening decision. The link
between them is an identifier.

This also removes the last practical reason a reviewer would keep a parallel
folder of PDFs, which is where full-text provenance usually goes to die.

## 2. Scope

| Direction | Feature | Milestone |
|---|---|---|
| Zotero → `epic` | Import a collection or saved search as records | M6 |
| Zotero → `epic` | Resolve and open the full text during screening and extraction | M6 |
| `epic` → Zotero | Push included studies to a collection for citation | M6 |
| `epic` → Zotero | Mirror screening state as Zotero tags/collections | post-1.0 |
| Zotero → `epic` | Pull PDF annotations as extraction source locators | post-1.0 |

None of this is required for a complete review. `epic` MUST remain fully
functional with Zotero absent, and MUST NOT make Zotero a dependency of any core
workflow.

## 3. Transport

Two paths, detected in this order:

**Local HTTP API** (preferred). Zotero exposes a local endpoint on
`127.0.0.1:23119` when the desktop application is running. It requires no API
key, never leaves the machine, and works with the user's existing local library —
which fits `epic`'s offline-by-default posture ([13 §4](13-nonfunctional.md)).
Its shape has changed across Zotero versions, so the client MUST probe for
capability rather than assume, and MUST degrade to the Web API on mismatch.

**Web API v3** (`api.zotero.org`). Needed for group libraries and for users who
do not have the desktop application running. Requires an API key.

*(normative)* An API key MUST be stored in the operating system keychain via
`keyring`, never in `epic.toml` and never in the repository. If no keychain is
available, `epic` MUST read it from an environment variable and MUST say that it
is not being persisted. A key accidentally committed to a shared review
repository is a real and irreversible leak.

## 4. Identity mapping *(normative)*

```
integrations/zotero.ndjson
```

```json
{"record":"rec_3kq8v1r0zx2m4a7b","library":"users/12345","item_key":"AB3D9XYZ","item_version":8842,"linked":"2026-03-28","via":"doi"}
```

Matching a Zotero item to an `epic` record uses the same canonical-key ladder as
record identity ([01 §3.1](01-domain-model.md)): DOI, then PMID, then the
title/year/first-author signature. Items that match nothing above the dedup
review threshold are reported, never guessed at.

The mapping file is committed and is authoritative-but-advisory: a stale
`item_key` (the item was deleted in Zotero) MUST degrade to "full text
unavailable", never to an error that blocks screening.

**Zotero is mutable; `epic` is append-only.** The two cannot be kept in
lock-step, and pretending otherwise would produce silent data loss. Therefore:

- Every pull that changes a record writes ordinary `record-amend` events, so the
  change is visible in history like any other.
- `epic` MUST NOT delete or overwrite a Zotero item it did not create. Pushes
  create or update; they never remove.
- Zotero's per-item `version` is stored and used for optimistic concurrency: a
  push that would clobber a newer server version is refused and reported.
- Conflicts are resolved in favour of **Zotero for bibliographic metadata** and
  **`epic` for anything decision-shaped**. Neither system is ever authoritative
  over the other's domain.

## 5. Commands

```
epic zotero link                       # authenticate / detect, choose a library
epic zotero pull --collection "Spacing review" --search S-05-zotero
epic zotero push --set included --collection "Spacing review / Included"
epic zotero status                     # mapped, unmapped, stale links
epic zotero open <record-id>           # open the full text in Zotero's reader
```

`epic zotero pull` is an import source like any other
([05 §2](05-workflow-import.md)): it requires a `--search` id, records the
collection name and pull date for PRISMA reporting, and MUST be tagged
`--via` appropriately — a Zotero collection assembled by hand is
`other-methods`, not a database search, and putting it in the wrong column of the
flow diagram would misreport the review.

## 6. Retrieval through Zotero

When a Zotero link exists, the retrieval queue ([07 §1](07-workflow-extraction.md))
changes shape usefully:

```
$ epic retrieve

  204 reports sought. 8 outstanding. Zotero: 196 attachments found.

  rpt_3kq8v1r0zx2m4a7b  Cepeda et al. (2008)
    doi:10.1111/j.1467-9280.2008.02209.x
    Zotero: PDF attachment present (version of record)

    [o] open in Zotero   [n] not retrievable   [s] skip
```

The manifest entry then records the Zotero item key alongside the DOI instead of
a local path. The user never files a PDF by hand, and the provenance chain is
still complete, because it was always the identifier doing the work.

## 7. Annotations as extraction sources *(post-1.0)*

Zotero 7 stores highlights and notes as first-class items with page positions.
Pulling them would let a reviewer highlight "148 participants completed the
delayed test" in the PDF and have `epic` offer it as the source locator for the
`n_total` field — turning the source-locator requirement in
[07 §3.4](07-workflow-extraction.md) from a chore into a by-product of reading.

This is the most valuable item on the post-1.0 list and the most speculative:
it depends on annotation APIs that are not covered by Zotero's stability
guarantees. Prototype before committing to it.

## 8. Risks

| Risk | Mitigation |
|---|---|
| Local API shape changes between Zotero versions | Capability probe; fall back to Web API; integration tests pinned per Zotero major version |
| Web API rate limits (backoff headers on 429/503) | Honour `Backoff` and `Retry-After`; batch requests; cache by item version |
| Users expect two-way live sync | Documentation states plainly that pull and push are explicit operations, not a background sync |
| A group library's permissions silently block a push | Check write permission at `link` time, not at push time |
| Integration rot outliving maintainer attention | The integration is optional and isolated behind the `Enricher`-style boundary ([12 §5](12-architecture.md)); if it breaks, nothing in the core workflow does |

## 9. Other reference managers

The same interface should serve Mendeley, EndNote, and Paperpile. Only Zotero is
specified because it is free software, has a documented API, and is what the
target users mostly use. The integration boundary MUST be defined generically
(`ReferenceManager`: resolve, pull, push, open) so a second implementation is a
plugin rather than a rewrite.
