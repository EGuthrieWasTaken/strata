# The Zotero integration against a real Zotero

First run of `strata`'s Zotero integration (`openspec/changes/add-zotero-integration`) against a running
Zotero. Until now every test talked to `tests/zotero_fake.py`, written from the API documentation. This
records where real Zotero differs. Nothing under `src/` was changed. Raw evidence is in
`tests/fixtures/zotero/captured/10/` (read its `README.md` first).

## Summary

The findings that matter most (the Web API path worked end to end; the local API path did not):

1. **`strata zotero link` and `strata zotero pull` fail through the local API.** Zotero 10's local API
   serves each item's `csljson` as a JSON-encoded *string* (a one-element array, pretty-printed), not an
   object. `strata` reads only an object or a list, so it stops with "Zotero sent an item without its
   CSL-JSON". The capability probe still passes (it checks that the key is present, not its type), so
   `auto` picks the local API and then fails; there is no fallback. Through the Web API everything works.
2. **The local API is not read-only.** "Only the Web API can write" is wrong for Zotero 10.0.8. Writes are
   accepted behind a `Zotero-Server-ID` header (428 without) and a *local* API key obtained from
   `POST /api/local/authorize`, which asks the person in the app (401 without). Not exercised past the 401.
3. **PMIDs do not round-trip.** `strata push` writes a PMID into `extra` (`PMID: n`); Zotero's CSL-JSON
   exports that as `note`, never as `PMID`, so the PMID rung of the matching ladder cannot match an item
   whose PMID is in `extra`. This Zotero's journal articles have native `PMID` and `PMCID` fields, and those
   *do* come through as CSL `PMID`/`PMCID`.
4. **`strata zotero open` did not reach Zotero** on this Linux machine: it opens the link with Python's
   `webbrowser`, which chose Firefox. The same link through `xdg-open` made Zotero respond.
5. The group library (second pass) behaves as the personal one in everything above: Web API link, pull and
   push work, the local API fails on `csljson`, and a native `PMID` does match.
6. Smaller: pushing again after an outside edit to the *same* collection says "already there", not
   "refused" (the refusal only shows when the item is not yet in the target collection); `strata` made no
   change to the library beyond what it says; the Web API behaves as the fake assumed in most respects.

`tasks.md` 5.1 stays open: the fixtures need correcting before they can be called pinned to a version.

## Environment

| | |
|---|---|
| Zotero | 10.0.8 (`X-Zotero-Version`; Arch package `zotero-bin 10.0.8-1`), API v3, schema 44 locally and 42 on `api.zotero.org` |
| Profile | a separate throwaway profile (`strata-test`, its own data directory) signed in as `strata-review`, user id 22585168; the machine's other Zotero profile was not touched |
| OS | Arch Linux, kernel 7.2.14, KDE Plasma on Wayland |
| strata | 0.1.0 at `bd52ee4` (`main`), Python 3.14 |
| Date | 13-14 November 2026 |
| Key | a write-capable Web API key in `$STRATA_ZOTERO_API_KEY`; never printed or stored |

**Safety check.** `GET /keys/current` named the account `strata-review` (user 22585168). Both the desktop
app's `users/0/items/top` and the Web API's returned 0 items and 0 collections before seeding, so it is a
throwaway library and writes went ahead. The same call showed the key may write to the user library and
to "all groups". On the first pass **the account belonged to no group** (`GET /users/22585168/groups` was
`[]`), so group steps waited; a group was created afterwards, `strata-ci-group` (id 6762415, owned by
`strata-review`, 0 items), and the second pass below used it.

## What was seeded

Through the Web API (the local one refuses writes), in the personal library: collections `strata-test`
and `strata-scratch` (later `strata-pushed` and `strata-pushed-2`, created for the push tests), 11 items
of six types from real published records (journal articles, a book, a book section, a preprint, a
thesis, a report), DOIs on six, PMIDs (in `extra`) on five, neither on four; a linked-URL attachment, a
stored PDF, an HTML snapshot, a second stored PDF, and one scratch item that write probes against the
local API were aimed at. The second pass seeded the group the same way: collections `strata-test` and
`strata-pushed`, five items (three journal articles, a book, a preprint, a thesis, with native `PMID`
fields on the articles), a linked URL and a stored PDF. The files are tiny stand-ins generated locally. The desktop app picked all of it
up within seconds without a click on sync.

## Assumptions in `tasks.md`

| # | Assumed | Verdict | What really happens |
|---|---|---|---|
| 1a | the local API serves `users/0/items/top?include=data,csljson` as the Web API does | **wrong** | The URL works and `Total-Results`, `Link` and the item envelope (`key`, `version`, `library`, `links`, `meta`, `data`, `csljson`) are there, but `csljson` is a **string**: `"[\n\t{\n\t\t\"id\": \"http://zotero.org/users/22585168/items/BEITJ9RM\", ...}\n]"`. The Web API gives an object `{"id": "26075093/BEITJ9RM", ...}`. The local copy also has string year parts (`[["2008", 11]]`, the Web API's are numbers), and `data` holds only fields that are set (the Web API sends every field of the type, empty ones as `""`). `format=csljson` is likewise `text/plain` there and `{"items": [...]}` as `application/vnd.citationstyles.csl+json` on the Web. Item versions are unrelated: the same item is version 14 locally and 4 on the Web |
| 1b | ...and is read-only | **wrong** | Reads need nothing. Writes get `428 Zotero-Server-ID not provided`; with that header (the server hands its id out on every response) `401 API key required -- POST /api/local/authorize to obtain one` (with `WWW-Authenticate`), `401 Invalid or expired API key` for any key including the zotero.org one, `412 Zotero-Server-ID does not match this server` for a wrong id. A local key comes from `POST /api/local/authorize` with `{"appName": ...}`, which shows Allow / Always Allow / Deny in the app. I did not trigger that prompt, so what a *granted* write does is untested. All twelve write attempts (POST create, POST update, PUT, PATCH, DELETE, POST collection, POST with a write token, and five more with the server id, a wrong id, a bogus key and the zotero.org key) were refused and the library did not change. This is stated in the app's own source (`server_localAPI.js`), not only inferred |
| 2 | the setting that switches the local API on is under Settings > Advanced | **confirmed** (from the app's source and profile; not toggled live) | Settings > Advanced, in the **Miscellaneous** group, a checkbox labelled "Allow other applications on this computer to communicate with Zotero" (below "Report broken site translators"), with "Available at http://localhost:23119/api/" beneath it. It is bound to the preference `extensions.zotero.httpServer.localAPI.enabled`, which is in the profile's `prefs.js` as `true`, and is greyed out unless `extensions.zotero.httpServer.enabled` is on. When the preference is off every `/api/` request (including the `/api/` ping) is meant to answer `403 text/plain "Local API is not enabled"` (the fake's text is identical). That 403 was **not observed live**; it needs someone to toggle the box |
| 3 | `GET /keys/current` reports a key's write access per library | **confirmed for the user library; for groups only the "all groups" entry** | `{"key", "userID", "username", "displayName", "access": {"user": {"library", "files", "write"}, "groups": {"all": {"library", "write"}}}}`, unchanged after the account joined a group. The fake lacks `displayName` and `user.files`. A per-group entry (`groups.<id>`) appears only for a key made for specific groups, which was not available; a write to the group library through this key worked. The body **echoes the key**, so a capture must be redacted. No key or a wrong key: `403 Forbidden`. The local API has no `/api/keys/current` (404) |
| 4a | `POST /items` with `key` and `version` per object updates only the named properties | **confirmed** | An object with `key`, `version`, `collections` changed `collections` and the version and nothing else (compared field by field; `dateModified` did not move either) |
| 4b | ...and reports a version mismatch as a per-object 412 | **confirmed, with differences** | HTTP **200** with `failed: {"0": {"code": 412, "message": "Item has been modified since specified version (expected 1, found 4)"}}`. The entry has **no `key`** (the fake adds one) and the message does not name the item. Also seen: a version *newer* than the item's is not refused (an unchanged payload comes back `unchanged`), so only an older version conflicts; a missing `version` is `failed` 428 ("Either If-Unmodified-Since-Version or 'version' property must be provided..."); an unknown key is `failed` 404; a bad field is `failed` 400 ("Invalid property 'noSuchField'"). A stale `If-Unmodified-Since-Version` *header* fails the **whole request** with `412` and a `text/html` body. `successful` holds the full item object (the fake holds `{key, version}`), `success` maps slot to key (the fake leaves it empty) and `unchanged` maps slot to key. 51 objects: `413 Cannot add more than 50 items at a time` |
| 5 | `GET /items/new?itemType=` serves item templates | **confirmed on the Web API; not on the local one** | 200 with no key. Bad or missing type: `400`. The real templates have many fields the fake's do not (20 more on `journalArticle`; see below), and only `journalArticle` has `PMID`/`PMCID`. The local API answers 404, which does not matter because pushes go through the Web API |
| 6 | an attachment whose `linkMode` is `linked_url` means no file | **confirmed** | No `filename`, `md5`, `mtime` or `enclosure` link; the local `/file` is `400 Not a file attachment`, the Web `/file` is `404`. `strata retrieve --list` said `Zotero: none` for it. `imported_file` and `imported_url` do have a file. (`linked_file`, a path on disk, was not tried.) Note `imported_url`, an HTML snapshot, counts as `Zotero: files`, not none |
| 7a | `zotero://open-pdf/...` opens a PDF | **confirmed through the OS handler, not through `strata`** | `xdg-open zotero://open-pdf/library/items/<key>` made the running Zotero mark the attachment read (`lastRead` appeared and the item's version moved), which is what opening the attachment in Zotero's reader does. `strata zotero open` on the same link did nothing (see below) |
| 7b | `zotero://select/...` opens an item | **could not verify the effect** | `xdg-open` returned 0 and started no second Zotero (the running one took it), but selection in the item tree is not visible from the API and the screen was not inspected. The link `strata` prints is the form Zotero documents, and for a group `zotero://select/groups/6762415/items/<key>` and `zotero://open-pdf/groups/6762415/items/<key>`. For the group PDF `xdg-open` returned 0 but `lastRead` did **not** appear (it is not set for items in a group, or the open did not happen), so the group open is unverified |

## Fixture differences

### `tests/fixtures/zotero/library.json` and `zotero_fake.py` against the Web API

| Area | Fake | Real |
|---|---|---|
| item envelope | `key`, `version`, `library {type, id}`, `data`, `csljson` | also `links {self, alternate}` and `meta {creatorSummary, parsedDate, numChildren}`; `library` also has `name` and `links` |
| item `data` | `key`, `version`, `itemType`, `title`, `collections` | every field of the type (journal article: 40 incl. `creators`, `tags`, `relations`, `dateAdded`, `dateModified`, `PMID`, `PMCID`, `citationKey`, `section`, `partNumber`, `partTitle`), empty ones as `""` |
| `csljson.id` | `<user id>/<key>` | `<internal library id>/<key>` (26075093, not the user id 22585168); harmless, `strata` drops it |
| CSL fields | hand-written | `container-title`, `page`, `issued.date-parts` of numbers, `author`; `extra` -> `note`; native `PMID`/`PMCID` -> `PMID`/`PMCID`; a bare year is `[[2026]]` |
| collections | `{key, version: 1, data: {key, name}}` | also `library`, `links`, `meta {numCollections, numItems}`, and `data.parentCollection` (`false`), `data.relations` |
| attachment `data` | `key`, `itemType`, `parentItem`, `linkMode`, `contentType`, `title` | also `filename`, `md5`, `mtime`, `url`, `accessDate`, dates; `links.enclosure` for files; `meta` is `{}` or `{numChildren: false}` (locally `{numChildren: 0}`) |
| `linked_url` `contentType` | `application/pdf` | whatever was set (`text/html` here); Zotero does not derive it |
| write response | `successful {slot: {key, version}}`, `success {}`, `failed {slot: {key, code, message}}` | `successful {slot: <full item>}`, `success {slot: key}`, `failed {slot: {code, message}}` (no key) |
| 412 text | `Item KEY has been modified since specified version ...` | `Item has been modified since specified version ...` |
| non-JSON errors | `text/plain` | `text/html; charset=UTF-8` (`An API key is required for write requests.`, `Uploaded data must be a JSON array`, `Library has been modified since specified version (expected 1, found 21)`) |
| `>50` objects | `413 Too many items` | `413 Cannot add more than 50 items at a time` |
| `itemKey` with 51 keys | `400` | `200` and the **filter is dropped**: the whole library comes back (51 identical, nonexistent keys return `[]`, so the limit is on distinct keys). The local API does the same |
| write token | not modelled | optional; a 5-32 character token reused after a success is `412 Write token already used`; 10 characters is accepted |
| templates | `journalArticle` 16 fields, `document` 12 | `journalArticle` 36 (adds `ISSN`, `PMCID`, `PMID`, `accessDate`, `archive`, `archiveLocation`, `callNumber`, `citationKey`, `journalAbbreviation`, `libraryCatalog`, `partNumber`, `partTitle`, `place`, `publisher`, `rights`, `section`, `series`, `seriesText`, `seriesTitle`, `shortTitle`); `document` 23 against the fake's 12 (adds `DOI`, `type`, `place`, `shortTitle`, ...). `book`, `bookSection`, `preprint`, `thesis`, `report` have `DOI`, none has `PMID` |
| headers | `content-type`, `Total-Results`, `Last-Modified-Version` on writes | also `Zotero-API-Version: 3`, `Zotero-Schema-Version`, `Last-Modified-Version` on reads, `Link` (`next`, `last`, `alternate`) on lists |
| `Backoff`, `Retry-After`, 429/503 | modelled | never seen in the 133 captured requests |
| group listing | `{id, version, data {id, name}}` | `{id, version, links, meta, data}`. Web `meta` has `created`, `lastModified`, `numItems`, `isAdmin`; `data` has `owner`, `type`, `libraryEditing`, `libraryReading`, `fileEditing`, `description`, `url`. Local `meta` is `{numItems}` and `data` only `id`, `version`, `name`, `description` |
| group item envelope | `library {type, id}` | `library {type: "group", id, name, links}`; the Web API adds `meta.createdByUser {id, username, name, links}` to group items; locally `csljson` is still a string. Group writes behave as the personal ones (stale version: per-object 412 inside a 200; no key 403; 51 objects 413); local group writes 428, then 401 |

Fields real Zotero has that the fake lacks: everything in the right-hand column above. Fields the fake
has that real Zotero lacks: `failed[...].key`; the `application/pdf` type on a linked URL as something
Zotero would set; the 400 on more than 50 `itemKey`s. The status codes the fake gets right: 403 for no
key or a wrong key, 404 for a group the key cannot see, 413 on >50 objects, 400 for a bad item type, a
per-object 412 for a stale version.

### `7/profile.json` against the local server

| | 7 profile | Real 10.0.8 (`profile.observed.json`) |
|---|---|---|
| `local_api` | `true` | `true` |
| `local_api_needs_preference` | `true` | `true`; `403 "Local API is not enabled"` per the source |
| `local_api_writable` | `false`; writes are `501 Method Not Implemented` | writes are 428, then 401 (then possible once authorised) |
| status line | not modelled | `HTTP/1.0`, reason `undefined` on 302/401/428 |
| default page size | the fake's 25 | none locally (the Web API's is 25, maximum 100) |
| `itemKey=A,B` | the two items | the two items **and their child attachments** (Web API: only the two) |
| `/api/users/<other id>` | not modelled | `400 Only data for the logged-in user is available locally -- use userID 0 or 22585168`; the real id works |
| wrong `Zotero-API-Version` | not modelled | `501 API version not implemented: 2` |
| wrong `Zotero-Server-ID` | not modelled | `412`, even on a read |
| `/api/keys/current`, `/api/items/new` | not modelled | 404 |
| `/api/users/0/items/<key>/file` | not modelled | `302` to a `file://` path; `400` for a link; `/fulltext` `404` |
| `/api/` | not modelled | `200 text/plain "Nothing to see here."`, with `X-Zotero-Version`, `Zotero-API-Version: 3`, `Zotero-Schema-Version: 44`, `Zotero-Server-ID` |

No `6/profile.json` check was possible: there is no Zotero 6 here. The `profile.json` shape also has no
way to say "the item's `csljson` is a string" or "versions are local"; both would be new keys.

## `strata` commands

All run in a scratch review outside the clone (`strata init`, actor `tester`, a recorded MEDLINE search,
five records imported from a CSL-JSON file, one criterion). Full output is in `strata-runs/`.

| Command | Result |
|---|---|
| `zotero link --by tester` (local, no key) | **failed**, exit 1: `error: Zotero sent an item without its CSL-JSON (key '6HPCSR64'), which strata needs to read it`. Left nothing behind |
| `zotero link --by tester --web --library groups/777` (first pass, before the group existed) | `error: 'groups/777' is not one of your libraries: users/22585168 (My Library)` (exit 2), `strata.toml` unchanged |
| **group**: `zotero link --by tester --library groups/6762415` (local) | **failed** with the same CSL-JSON error (`key 'KJ9MJ46K'`) |
| **group**: `zotero link --by tester --web --library groups/6762415` | worked: 2 of 5 items matched, the other 3 listed. Then `pull --collection strata-test --via website`: 4 items, 2 new, 2 linked; `status` `4 of 7 records mapped`. The Pavlik record, which has only a PMID, **matched `via pmid`** (the item's native `PMID` reaches CSL-JSON), and the pull copied Roediger's PMID into the record |
| **group**: `push --collection strata-pushed`, two included records | `1 created, 1 added, 0 already there`; a second push `0 created, 0 added, 2 already there`. The group library lost nothing and the existing item only gained the collection (`strata-runs/group/library-diff.txt`) |
| **group**: `zotero open --print-only`, and open | `zotero://select/groups/6762415/items/6BQ4WRIB`, `zotero://open-pdf/groups/6762415/items/U5JR5IES`; `strata`'s own open and `xdg-open` both exited 0, and no effect could be seen (see 7b) |
| `zotero link --by tester --web --library users/22585168` | worked. 4 of 13 items matched: two by DOI, two by "signature" (title, year, first author); the other 9 listed. The Pavlik record, which had a PMID and no DOI, matched by signature, not by PMID |
| `zotero pull --collection strata-test --by tester --via website` | worked (it follows the link's transport, `web`): 10 items, 6 new records, 4 already linked, 11 corrections (mostly `language: None -> 'en'`; a DOI came back lower-cased: `strata`'s own normalising, Zotero keeps `...-898X...`) |
| `zotero status` | worked: `10 of 11 records mapped`, `no stale links` |
| same `status` and `pull` with `transport = "auto"` in a copy of the review | `status` worked; `pull` **failed** with the CSL-JSON error above. So `auto` takes the local API and then cannot read it |
| `zotero push --collection strata-pushed --by tester` before the collection existed | `error: no collection 'strata-pushed' in users/22585168; the collections are: strata-scratch, strata-test` (exit 1). Clear, but a push never creates the collection |
| the same push after creating it, with two included records | `pushed to 'strata-pushed': 1 created, 1 added, 0 already there`. The created item has the right type, creators, date, DOI and `extra: PMID: 21252317`; the existing one only gained the collection |
| outside edit to both pushed items, then the same push again | `pushed to 'strata-pushed': 0 created, 0 added, 2 already there` (exit 0): **not refused**, because membership is checked before the version |
| the same push to a collection neither item is in (`strata-pushed-2`) | refused twice, exit 5: `refused rec_6nkmc81132r4p6ag: edited in Zotero since strata last saw it (version 26 is now 29); pull it, then push again`, and the same for the other; nothing written |
| `zotero pull --collection strata-pushed --via website`, then that push | pull corrected both abstracts; push then `0 created, 2 added`. The recovery path works |
| `retrieve --list` | `Zotero: pdf` for two records with a stored PDF, `files` for one with only an HTML snapshot, `none` for one with only a linked URL and one with nothing |
| `zotero open <record> --print-only` | `zotero://select/library/items/BEITJ9RM`; `zotero://open-pdf/library/items/TI5GQH7I` for a record with a PDF |
| `zotero open <record>` | exit 0 and printed the link, but **Zotero did not respond** (the attachment's `lastRead` stayed empty for 8 s). `webbrowser.get()` here is `Mozilla firefox`, so the link goes to the browser, not to Zotero. `xdg-open` on the same link made Zotero open the PDF within 8 s |

**The outside edit was made through the Web API, not in the Zotero app.** The desktop interface could not
be driven from this session. For `strata` the effect is the same (the item's version moves) but it is not
the same path; someone should repeat that one step by hand.

## The library afterwards

Compared item by item before and after each `strata` write (`strata-runs/library-diffs.txt`): **nothing
deleted** (and the trash is empty), no item `strata` did not create changed except by gaining a
collection (`BEITJ9RM` gained `strata-pushed` and then `strata-pushed-2`); the one item `strata`
created (`UKWX94NM`) is complete. The only other changes to the library are mine (the seed, the two
outside edits, the probe items) and Zotero's own: opening a PDF set `lastRead` on the two attachments,
which also moved their versions. No key was stored in the keychain.

## Consequences for `strata`

Not changed here; for whoever picks them up.

- Read `csljson` as a string holding JSON on the local API (and probe for the shape you read, not just
  the key). Local item versions are not Web versions: a link made through the local API would store
  version 14 where a later Web push finds 4, and `push` would call the item "edited in Zotero". Keep
  them apart, or do not store a local version.
- Use the native `PMID`/`PMCID` fields when the item type has them (the template says), read PMIDs from
  `extra`/`note` too, and keep `extra` as the fallback.
- Decide whether an edited item that is already in the collection should be "already there" or "refused".
- `strata zotero open` should hand `zotero://` links to the OS handler (`xdg-open`, `open`,
  `os.startfile`), not to a browser.
- `local_api_writable: false` and "the local API is read-only" are wrong for Zotero 10; decide whether
  the local API is wanted for writes (it needs a per-app authorisation the person grants in Zotero).
- Correct the fixtures: the envelope, `csljson` shape, `failed` entries, templates, the `itemKey`
  behaviour, the writes of the local API, and add a `10` profile.

## Could not be tested

- **Per-group key entries** in `keys/current` (the key covers "all groups"), a group where the key
  may read but not write, and the effect of the group `zotero://` links.
- **The local API switched off** (needs someone to untick the box; the expected answer is above).
- **A granted local write** (needs a click on Allow in Zotero; `POST /api/local/authorize` was not called
  so no prompt appeared).
- **An edit made in the Zotero app** (stand-in used).
- **What `zotero://select` does** on screen.
- **Zotero 6**, and any other major version; macOS and Windows.
- **A key without write access**, or a second key; the fake's 403 "Write access denied" is unchecked.
- **`Backoff`, `Retry-After`, 429 and 503**: none arose.
- `linked_file` attachments, notes and annotations, nested collections, saved searches, `since`
  incremental reads, and libraries of more than a few dozen items (paging beyond one page).

## Notes on how this was run

- Requests were sent with a small Python script using `http.client`, which shows exactly what `strata`'s
  `urllib` transport receives. The Zotero API key went only to `api.zotero.org`, except one deliberate
  probe sending it to the local server at `127.0.0.1` to see it refused (it was; it stayed on this
  machine).
- Read-only questions about the setting were answered from the installed app's own source
  (`chrome/content/zotero/xpcom/server/server_localAPI.js`, `preferences_advanced.xhtml`), extracted
  from its read-only archive; this is what the app does, but it is not the same as watching it do it.
- The scratch review, the capture scripts and the intermediate library snapshots are not committed.
