# Design: Zotero integration

## Context

Zotero is free software, widely installed by the target users, and good at the
three jobs `strata` has declined: holding PDFs, citing while writing, and group
libraries.

## Goals / Non-Goals

**Goals:**

- Pull a collection as an import source, resolve full texts during screening
  and extraction, push included studies to a collection for citation.
- Never make Zotero a dependency of any core workflow.

**Non-Goals:**

- Two-way live sync (pull and push are explicit operations).
- Mirroring screening state as Zotero tags, and pulling annotations as
  extraction sources (post-1.0; the annotation API lacks stability guarantees).

## Decisions

- **Local HTTP API first** (`127.0.0.1:23119`): no key, never leaves the
  machine, fits offline-by-default. Probe capabilities rather than assume a
  shape; fall back to Web API v3 on mismatch.
- **Keys live in the OS keychain**, never in `strata.toml` or the repository; a
  key committed to a shared review repository is an irreversible leak.
- **Zotero is mutable, `strata` is append-only.** Pulls that change a record are
  ordinary `record-amend` events; pushes create or update but never remove;
  Zotero's item `version` gives optimistic concurrency; Zotero wins on
  bibliographic metadata, `strata` on anything decision-shaped.
- **A stale mapping degrades** to "full text unavailable", never to an error
  that blocks screening.

## Risks / Trade-offs

- Local API shape changes between Zotero versions: capability probe, Web API
  fallback, integration tests pinned per Zotero major version.
- Web API rate limits: honour `Backoff` and `Retry-After`, batch, cache by item
  version.
- Group-library permissions: check write permission at `link` time, not at
  push time.

## Reference: identity mapping and retrieval

`integrations/zotero.ndjson`:

```json
{"record":"rec_3kq8v1r0zx2m4a7b","library":"users/12345","item_key":"AB3D9XYZ","item_version":8842,"linked":"2026-03-28","via":"doi"}
```

The retrieval queue with a Zotero link:

```
$ strata retrieve

  204 reports sought. 8 outstanding. Zotero: 196 attachments found.

  rpt_3kq8v1r0zx2m4a7b  Cepeda et al. (2008)
    doi:10.1111/j.1467-9280.2008.02209.x
    Zotero: PDF attachment present (version of record)

    [o] open in Zotero   [n] not retrievable   [s] skip
```

## Reference: scope beyond this change

| Direction | Feature | Milestone |
|---|---|---|
| Zotero → `strata` | Import a collection or saved search as records | M6 (this change) |
| Zotero → `strata` | Resolve and open the full text during screening and extraction | M6 (this change) |
| `strata` → Zotero | Push included studies to a collection for citation | M6 (this change) |
| `strata` → Zotero | Mirror screening state as Zotero tags/collections | post-1.0 |
| Zotero → `strata` | Pull PDF annotations as extraction source locators | post-1.0 |

Annotations as extraction sources is the most valuable post-1.0 item and the
most speculative: highlighting "148 participants completed the delayed test" in
the PDF would supply the source locator for `n_total` for free, but it depends
on annotation APIs outside Zotero's stability guarantees. Prototype before
committing to it.

The same `ReferenceManager` boundary (resolve, pull, push, open) should serve
Mendeley, EndNote, and Paperpile as plugins.
