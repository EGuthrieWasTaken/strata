# Captures from a running Zotero 10.0.8

Raw requests and responses from a real Zotero (desktop 10.0.8 on Arch Linux, KDE/Wayland; API v3,
schema 44 on the local server, 42 on `api.zotero.org`), taken against a **throwaway** zotero.org
account whose library `strata` seeded for the purpose. Read `docs/zotero-real-run.md` for what they
show; this file only says how to read them.

## Layout

| Path | What |
|---|---|
| `local/` | the desktop app's local API at `127.0.0.1:23119` (no key). `personal/` reads, `write/` write attempts, `read/` refused reads, `root*.json` the `/api/` ping |
| `web/` | `api.zotero.org` with a write-capable key. `personal/` reads and templates, `write/` writes and refusals, `keys-current*.json` |
| `seed/` | the requests that built the library (collections, 11 items, 3 attachments and a scratch item, file uploads, the two edits made "outside strata") |
| `strata-runs/` | the output of every `strata` command run against this library, `review-state/` (the mapping file and `[zotero]` table the link produced) and `library-diffs.txt` (what strata changed in the library) |
| `profile.observed.json` | what this version's local server does, in the shape of `../<major>/profile.json` |

`local/group/` and `web/group/` are the same questions asked of the throwaway account's group library
(`strata-ci-group`, id 6762415, owned by that account); `seed-group/` is how it was seeded and
`strata-runs/group/` the `strata` runs against it. The group was created on zotero.org by the person
running this, after the first pass, and was empty until `strata` seeded it.

## One file

```json
{
  "request":  { "method", "url", "headers", "body" },
  "response": { "status", "reason", "http_version", "headers": [[name, value], ...],
                "body_encoding": "json" | "text", "body" },
  "note": "why this request was sent",
  "transport_error": "only if no response came back"
}
```

`reason` is Zotero's own: the local server sends the literal string `undefined` for some statuses
(302, 401, 428). Header order and case are as received; `http_version` is what Python's `http.client`
saw, which is what `strata`'s `urllib` transport sees (the Web API is HTTP/2 to a browser or `curl`).

## What was redacted

- the Web API key (anywhere it appeared, including the `key` field of `keys/current`) -> `REDACTED`
- the signed `files.zotero.net` download address in a `302` -> `REDACTED-SIGNED-TOKEN`
- the signed storage upload form fields and upload key of a file upload -> `REDACTED`
- the home directory in `file://` addresses -> `/home/USER`
- email addresses -> `REDACTED-EMAIL` (none turned up)

The numeric user id (22585168), the username `strata-review` and `Zotero-Server-ID` were left in.

## Caveats

- Item keys, versions and timestamps are specific to this library and this day; a second capture
  will differ in all of them. The *shapes* are what matter.
- The local server's item versions are unrelated to the Web API's (the same item is version 14
  locally and 4 on the Web); compare shapes, not numbers.
- The PDF and HTML "attachments" are tiny stand-ins generated locally; they are not the papers.
- The `strata-scratch` collection and its items exist only so write probes against the local API had
  something harmless to aim at.
