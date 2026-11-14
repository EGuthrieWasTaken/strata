# Zotero fixtures

Test fixtures for `openspec:zotero-integration` (task 5.1: integration tests pinned per Zotero major
version). `tests/zotero_fake.py` serves them as the Zotero API v3 would.

- `library.json` is what the API serves: a personal library, a group library, collections, items
  with their CSL-JSON, attachments and item templates. API v3 payloads are the same across Zotero
  major versions, so there is one.
- `<major>/profile.json` pins what that major version's *local server* does, which is what differs:

  | Major | Local API |
  |---|---|
  | `7` | Serves the read-only local API at `127.0.0.1:23119/api`, once the person has switched it on in Settings |
  | `6` | Has the connector server only: `/api/...` is a 404, so the Web API is the only way in |

The integration tests run once per major version, so a change in what one version's server does
shows up as a failing test for that version only.

## What was captured from a running Zotero

`captured/10/` holds raw requests and responses from Zotero 10.0.8 and `api.zotero.org` (read its
`README.md`; `docs/zotero-real-run.md` says what they showed). `10/profile.json`, the item templates in
`library.json` and the fake's write replies and error texts follow those captures, and
`tests/unit/test_zotero_real_captures.py` replays them through `strata`'s own readers. The `6` and `7`
profiles, and the items in `library.json`, are still as described below.

## Provenance and what these do not prove

Everything here is **hand-written from the published Zotero API v3 documentation**, not captured
from a running Zotero. The bibliographic metadata is the project's usual running example (Cepeda et
al. 2008, Roediger & Karpicke 2006) plus invented records; nothing is copied from a real library.
They pin the shape `strata` reads; they cannot show that a particular Zotero release serves that
shape. That needs a person with Zotero running: capture a library from it, check `library.json`
against the capture, and add a `profile.json` for any further major version. Until that has been
done, task 5.1 of `add-zotero-integration` stays open.
