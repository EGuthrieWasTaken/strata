# Proposal: Make the web UI a point-and-click front end (M6)

## Why

`strata serve` is described as "the primary surface for screening, adjudication, and criteria
editing", and for those it is. For everything around them it is a viewer: a reviewer cannot record a
search, import an export file, correct a record, add a criterion, log a full-text outcome, or group
reports into studies without dropping to the command line. The dashboard even tells them "Pending
searches awaiting an export file" and offers no way to supply one.

That is the opposite of goal G4 (collaboration without git literacy), and it blocks two things
already planned:

- **Hosted instances** (`add-hosted-team-deployment`) promise that a team can work "without any
  member running a local `git` command". A hosted user has no shell and no filesystem, so a file
  upload is the only way literature can get in. That change does not currently plan one.
- **The usability session** left open in M2 (three non-git users complete a screening session
  unaided) can only cover the middle of a review while the beginning needs a terminal.

The motivating workflow: record a search and date it, drag the spreadsheet or RIS file the database
produced onto it, see what would be imported, confirm, and have the file and its parsed records
committed with the search it came from.

Roadmap milestone: M6, "Hardening and adoption" ([docs/roadmap.md](../../../docs/roadmap.md)). It
also closes a gap in M5.1's acceptance criteria for hosted use.

## What Changes

### Built in this change

- **Searches and imports in the browser**: a searches list, a record-a-search form (database,
  platform, date defaulting to today, query, hits, notes, who ran it, rationale), a search page, and
  a re-run flow that creates a superseding search rather than editing one. Export files (RIS, BibTeX,
  CSL-JSON, PubMed/MEDLINE, EndNote XML, CSV/TSV, Excel, plain-text lists) are attached with a file
  picker that drag-and-drop enhances. Every upload goes through a review step (the pipeline's
  dry run: format, rows read, new, matched, rejected with reasons; column mapping for CSVs; sheet
  choice for workbooks) and is committed only on confirmation. Imports that did not come from a
  database search (`--via` registry, website, organisation, contact, citation searching) get the
  same flow.
- **One operations layer under both surfaces.** The commit assembly for `search add` and `import`
  lives inside `cli/main.py` today, so the web UI could only copy it. It moves into
  `strata.core.operations` and both the CLI and the web call it, which is what makes "the same
  action from either surface produces the same commit" testable rather than hoped for.
- **Upload handling as a security surface** (new capability `web-uploads`): size and count limits
  enforced before the body is parsed, client file names never used as paths, staged files kept under
  `.strata/tmp/`, opaque batch ids, expiry, and the existing session, `Origin` and CSRF gates applied
  ahead of any byte being written. No full-text PDFs are accepted.
- **The remaining stage gaps that have a direct CLI equivalent and a clear form shape**, delivered as
  later task groups: correct a record field (`strata fix`), add a criterion (`criteria add`; the
  editor can edit and retire but not add), assign reviewers (`strata assign`), work the full-text
  retrieval queue (`strata retrieve`, outcomes only, no files), and group or split reports into
  studies (`strata studies`, with suggestions and evidence shown).
- **`repo_lock` becomes usable.** It is specified (`openspec:architecture#concurrency-and-locking`)
  and implemented, but nothing calls it, and as written a crashed process leaves a lock behind that
  blocks every later write. The shared operations take it, so it first learns to reclaim a lock
  whose holder has exited.

### Assessed and deliberately not built here

| Gap | Why not now |
|---|---|
| `sync` | A button that works until there is a conflict is worse than none; the conflict screen belongs with `add-hosted-team-deployment` (task 3.2), which also needs it. |
| Writing and running analyses, `report` sections, `export` downloads | Authoring an analysis specification is a form-design problem of its own, and downloads need streaming and archive handling. Better as a follow-up change, once this one has settled the write-path conventions. |
| `actor`, `config`, `init`, `clone`, `doctor`, `verify` | They change who people are, or run before a server exists. Accounts and identity are the hosted change's job. |
| `audit`, `irr` | Read-only reports; cheap, but they add nothing to the write path. A views change can take them. |
| Zotero as an import source | Waits for `add-zotero-integration`; the import screen is built so a source can be added without reshaping it. |
| Uploading full texts | `openspec:copyright-and-licensing` forbids committing them, and the retrieval screen records outcomes and identifiers only. |
| MCP write tools | Unchanged. The MCP server stays read-only; no path here records a screening or criteria decision without a person. |

### Not altered

Identity, normalisation, canonical serialisation, the fold, and the staleness rules are untouched.
No new event types, no new fields, **no repository schema version bump**.

## Capabilities

### New Capabilities

- `web-uploads`: how the web UI accepts files: limits, staging, file-name handling, expiry,
  refusal of full texts, and the order in which security checks run.

### Modified Capabilities

- `web-ui`: new write screens (searches, imports, record fixes, criterion add, assignment,
  retrieval, study grouping), the rule that every write screen is equivalent to its CLI command,
  and drag-and-drop as a progressive enhancement over an ordinary file input.
- `architecture`: mutating operations are shared services in `core` that the CLI and web call, and
  the advisory lock recovers from a holder that has exited.

## Impact

- New: `src/strata/core/operations.py`; `src/strata/web/search_routes.py` (searches and imports),
  with the later groups in further route modules; templates and a small `static/dropzone.js`
  (the JavaScript budget stays well under the spec's 50 KB).
- Changed: `cli/main.py` (`search add`, `import`, then `fix`, `criteria add`, `assign`, `retrieve`,
  `studies` call the shared operations; their output and commits are unchanged),
  `core/repo.py` (`repo_lock`), `web/app.py` (upload limits in the security middleware),
  dashboard and records templates (links).
- New option on `strata serve`: `--max-upload-mb`.
- No new runtime dependency (`python-multipart` is already required).
- Wiki: `The-Web-Interface`, `Searching-and-Importing`, and `Known-Limitations` change, along with
  the cheat sheet; `scripts/check_wiki.py` must stay green.
- `add-hosted-team-deployment` depends on this change for browser imports; a task here adds that
  note to its design.
