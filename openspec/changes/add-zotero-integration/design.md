# Design: Zotero integration

## Context

Zotero is free software, widely installed by the target users, and good at the
three jobs `strata` has declined: holding PDFs, citing while writing, and group
libraries. Full reasoning and risks: `docs/spec/17-zotero-integration.md`.

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
