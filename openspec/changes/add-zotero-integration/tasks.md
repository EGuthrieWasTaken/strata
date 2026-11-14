# Tasks

## 1. Boundary and transports

- [x] 1.1 Define the generic `ReferenceManager` interface (resolve, pull, push, open)
- [x] 1.2 Implement the local HTTP API client with capability probing
- [x] 1.3 Implement the Web API v3 client with `Backoff`/`Retry-After` handling
- [x] 1.4 Store API keys via `keyring`; fall back to an environment variable with a not-persisted notice

## 2. Identity mapping

- [x] 2.1 Write `integrations/zotero.ndjson` matching items by the canonical-key ladder
- [x] 2.2 Report unmatched items; degrade stale links to "full text unavailable"

## 3. Commands

- [x] 3.1 `strata zotero link` (detect, authenticate, choose library, check write permission)
- [x] 3.2 `strata zotero pull --collection ... --search ...` as an import source with `--via`
- [x] 3.3 `strata zotero push --set included --collection ...` with optimistic concurrency
- [x] 3.4 `strata zotero status` and `strata zotero open <record-id>`

## 4. Retrieval

- [x] 4.1 Resolve attachments in the retrieval queue and record the item key in the manifest

## 5. Tests

- [ ] 5.1 Integration tests pinned per Zotero major version
- [x] 5.2 A test that core workflows run with Zotero absent
- [x] 5.3 A test that a push never deletes or overwrites an item `strata` did not create

## Notes

Written and tested locally, never run against a real Zotero: task 5.1 stays open for that.

- **What "tested" means here.** Every test talks to `tests/zotero_fake.py`, an in-process stand-in for
  Zotero written from the published API v3 documentation, with fixtures in `tests/fixtures/zotero/`. They
  run once for Zotero 6 (no local API) and once for Zotero 7 (read-only local API). Nobody has watched a
  running Zotero answer. 5.1 is open because its point is to pin what real versions serve; these pins are
  assumptions until `library.json` is checked against a capture from a running Zotero (see the fixtures'
  README).
- **Run against a real Zotero 10.0.8 on 13-14 November 2026** (`docs/zotero-real-run.md`, captures in
  `tests/fixtures/zotero/captured/10/`). The Web API path worked end to end; the local API path did not.
  What that run found wrong is fixed and held by `tests/unit/test_zotero_real_captures.py`, which replays
  the captured responses through `strata`'s own readers:
  - the local API sends `csljson` as a string holding a one-element list (read by
    `integrations/zotero/csl.py`; the probe now checks the shape it reads, not just the key);
  - the desktop app's item versions are its own, so a local read records `item_version` 0 and a push
    does not refuse on it;
  - a PMID in `extra` never comes back as CSL `PMID`: pushes use the native `PMID`/`PMCID` fields where
    the item type has them, and reads take `PMID:`/`PMCID:` lines out of CSL `note`;
  - `date-parts` arrive as strings for a date Zotero could not parse (`11/1984`), which stopped a whole
    pull; they are coerced;
  - `strata zotero open` went through the browser and did nothing until a prompt was approved; it now
    hands the link to the operating system (`xdg-open`, `open`, `os.startfile`);
  - the fake's write replies, error texts, templates and `itemKey` behaviour are corrected to the
    captures, and there is a `10/profile.json`.
  **5.1 is still open** for one reason: only Zotero 10 has been seen. The `6` and `7` profiles are still
  assumptions; either capture those versions or drop them from the task. Also not done: a pinned Zotero
  in CI (the plan is a nightly job against the throwaway account for the Web API, and a Zotero under
  `xvfb` for the local one). The local API of Zotero 10 does take writes, with an authorisation granted
  in the app; `strata` still writes through the Web API only. An edited item that is already in the
  target collection is reported "already there", not "refused", because nothing would be written to it.
- **Assumed about Zotero before that run** (see the run's table for each verdict)**:** the local API at `127.0.0.1:23119/api` serves
  `users/0/items/top?include=data,csljson` as the Web API does and is read-only; the setting that switches
  it on is under Settings > Advanced; `GET /keys/current` reports a key's write access per library;
  `POST /items` with `key` and `version` per object updates only the named properties and reports a version
  mismatch as a per-object 412; `GET /items/new?itemType=` serves item templates; an attachment's `linkMode`
  of `linked_url` means no file; `zotero://select/...` and `zotero://open-pdf/...` open an item and a PDF.
- **Read `--search`/`--via` as "exactly one".** The spec says a pull "requires a `--search` id" and is also
  "tagged with the correct `--via`", and `strata import` requires exactly one of the two. A pull follows
  `strata import`: `--search` for a collection that holds a recorded database search's results, `--via`
  for a hand-built collection.
- **The local API is read-only,** so `zotero push` always goes through the Web API, and `zotero link`
  without `--web` records a read-only link and says how to make it writable. The write check at link time
  therefore needs a key; the local-API link asks for none.
- **Pushes only add to a collection** items `strata` did not create; they never write an existing item's
  fields (Zotero wins on bibliographic metadata) and never delete.
- **Built but not in a task.** Pulls correct a linked record's bibliographic fields from Zotero but never
  remove one; `strata screen` at a full-text stage and `strata retrieve` show where the full text is in
  Zotero and degrade to "full text unavailable"/"not reachable" rather than fail.
- **Changes to existing capabilities** that this change makes and the proposal did not list: an optional
  `collection` object in the import manifest (`literature-import`/`data-schemas`), an optional `zotero`
  object in a full-text manifest entry (`full-text-retrieval`), a `[zotero]` table in `strata.toml`
  (`data-schemas#project-manifest`), `integrations/*.ndjson merge=union` in `.gitattributes` and the
  `integrations/` directory (`git-integration`, `repository-format`). Fold them into the specs with
  `/opsx:update` before archiving.
- **Not built:** an on-disk cache of items by version (the design mentions caching as a rate-limit
  mitigation; batching and `Backoff`/`Retry-After` are done). Full-text screening in the web interface does
  not show Zotero's state.
