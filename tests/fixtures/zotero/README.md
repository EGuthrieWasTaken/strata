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

## Provenance and what these do not prove

Everything here is **hand-written from the published Zotero API v3 documentation**, not captured
from a running Zotero. The bibliographic metadata is the project's usual running example (Cepeda et
al. 2008, Roediger & Karpicke 2006) plus invented records; nothing is copied from a real library.
They pin the shape `strata` reads; they cannot show that a particular Zotero release serves that
shape. That needs a person with Zotero running: capture a library from it, check `library.json`
against the capture, and add a `profile.json` for any further major version. Until that has been
done, task 5.1 of `add-zotero-integration` stays open.
