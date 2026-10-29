# Design

## Context

Motivation and scope are in [proposal.md](proposal.md); the requirements are in `specs/`. What shapes
the approach is what the code does today:

- **Where commits are assembled.** `strata search add` and `strata import` build their
  `StructuredCommit`, stage paths, regenerate `derived/counts.json` and commit inside `cli/main.py`.
  The web routes that write (adjudication, criteria edit/retire, dedup, extraction) each hand-roll
  their own copy. Five such sites exist in the CLI and four in the web package. Adding searches and
  imports to the web a fifth way would deepen the drift
  `openspec:architecture#presentation-layers-contain-no-domain-logic` forbids.
- **The security middleware** (`web/app.py`) runs `Host`, `Origin`, inactivity, session, then, for a
  mutating request whose content type contains `form`, reads the whole form and compares a
  `csrf_token` field to the session token. It applies Starlette's default form limits, which cap
  non-file fields at 1 MB but not file size. `python-multipart` is already a dependency. The CSP is
  `script-src 'self'; form-action 'self'`, so enhancement scripts are static files.
- **The import pipeline** takes a path and copies it unmodified to `imports/<id>/raw/<name>`, so the
  file *name* matters. `import_file(..., dry_run=True)` is the review step; it requires an existing
  search id when one is named. Import is idempotent by digest.
- **`repo_lock`** exists and nothing calls it (`grep` finds only the definition). It is an
  `O_EXCL` file holding a PID, unlinked on clean exit, so a killed process leaves a lock that blocks
  every later write until a person deletes it.
- **Search records are immutable.** A re-run is a new file with `supersedes`. There is no command
  that supplies a missing (`PENDING`) query to an existing search.

## Goals / Non-Goals

**Goals:**

- A person can take a review from "I ran a search" to "its records are in the pool" without a terminal.
- CLI and web writes are the same code path, provably.
- Upload handling that is safe by construction and reviewed as its own capability.
- Every screen works without JavaScript; JavaScript only makes the same form more convenient.

**Non-Goals:**

- No new event types, record fields or schema version; no change to import, dedup or staleness
  behaviour.
- No consolidation of the existing hand-rolled web commit sites (adjudication, dedup, extraction,
  criteria edit/retire). Only operations this change adds, or that the CLI shares with them, move.
- No persistent navigation redesign; links are added where a person would look for them.
- No progress bar, resumable or chunked upload.
- Nothing from the "assessed and not built" table in the proposal.

## Decisions

### D1. Shared operations live in `core/operations.py`

An operation takes the repository, its parameters, and a rationale the caller has already obtained. It
takes the lock, writes, regenerates derived views, builds the `StructuredCommit`, stages, commits, and
returns a result. The CLI keeps prompting and printing; the web keeps forms and templates. A
`commit=False` flag serves `--no-commit`, and a `rationale_problem(repo, text, always=...)` check lets
both surfaces refuse before writing, which is the convention
`openspec:git-integration#eliciting-the-rationale` already sets for the CLI.

`core` already hosts command back ends (`core/sync.py`, `core/init.py`, `core/doctor.py`), and
`core/status.py` already imports `protocol`, so this adds no new dependency direction and leaves the
module list in `openspec:architecture` untouched.

*Rejected:* a new top-level `services/` package (needs a change to the module list for no gain);
having the web call the Typer command through `CliRunner` (couples the browser to terminal output and
exit codes); leaving the logic in `cli/main.py` and copying it (the status quo).

*Order of work:* `search add` and `import` move first, each with a snapshot test of the command's
stdout, exit code, files and commit message taken before the move. `fix`, `criteria add`, `assign`,
`retrieve` and `studies` move with their screens.

### D2. A search and its export are two commits, as on the command line

Submitting a search with files produces a `search-add` commit and then one `import` commit per
confirmed file. The raw file ends up in `imports/<id>/raw/`, tied to the search by the import's
manifest and its `Strata-Search` trailer, and listed in the search's `export_files` as the name the
person uploaded.

This is the reading of "attach to the commit containing the results" this design commits to; it is
the one decision here worth checking against what was meant. A single combined commit was rejected
because it needs a new commit operation that `strata log`, the history screen and the provenance
timeline would have to learn, because it makes "revert this import" impossible without also reverting
the search, and because it would make the web and the CLI record different histories for the same
action, which D1 exists to prevent.

`export_files` is written when the search is recorded, so it names every file uploaded with the form
even if one is later discarded or fails review. That is accurate: it is what the search produced, not
what was imported. Files added later from the search page are linked by their import and do not edit
the search.

### D3. Record the search first, then review, then import

```
POST /searches            multipart: search fields + 0..n files + rationale
  -> operations.record_search            (commit 1; lock held only for this)
  -> stage files                         (.strata/tmp/uploads/<batch>/)
  -> 303 /searches/<id>/review/<batch>

GET  /searches/<id>/review/<batch>       dry run per file, read-only, no lock
POST /searches/<id>/review/<batch>       confirm: mapping, sheet, rationale
  -> operations.import_files             (one commit per file)
  -> 303 /searches/<id>                  per-file results
```

Recording first matches the command line, and the pipeline's dry run needs an existing search.
Abandoning the review leaves a search recorded with no export, which the dashboard already reports
as awaiting one, exactly as when someone runs `strata search add` and stops.

*Rejected:* a dry run with no search (changes the pipeline's contract that exactly one of search or
method is given); holding the search uncommitted until confirmation (a half-written state that
survives a crashed server and has no CLI equivalent).

The same review and confirm steps serve the "attach more files" form on a search page and the
`/import` screen for other methods; only the first step differs.

### D4. Limits are enforced before parsing, using the declared length

The middleware, after the session, `Host` and `Origin` checks and before it reads the form, looks at a
multipart request's `Content-Length`: missing means 411, over the limit means 413, each with a message
naming the limit. The form is then parsed with explicit file-count and field-size limits. The declared
length can be trusted because uvicorn rejects a body longer than it declares.

The framework spools a large part to the operating system's temporary directory while parsing, which
happens before the CSRF field can be compared, since the token travels in the form. That cannot be
avoided without moving the token into the URL (which leaks through logs). It is acceptable because
the session cookie is `SameSite=Strict` and the `Origin` check has already passed, and because the
repository itself is not touched until the token is verified and the file is copied into staging.

*Rejected:* a CSRF token in the query string for uploads; a custom streaming parser that writes
straight into staging (more code in the most sensitive path, for a saving of one copy).

### D5. Staging store and file names (`web/uploads.py`)

Batches live under `.strata/tmp/uploads/<batch-id>/` (already git-ignored). The id is
`secrets.token_urlsafe(16)`, checked against a strict pattern before it is ever joined to a path. A
`batch.json` records original names, sizes, the receiving time and the search, so the server needs no
in-memory state. A purge removes batches older than an hour on every upload request and everything at
startup.

The name sanitiser is a pure function: it takes the last component after splitting on both `/` and
`\`, normalises Unicode, drops control characters, leading dots and trailing dots or spaces, replaces
characters outside a conservative set, truncates, refuses Windows device names (`CON`, `NUL`,
`COM1`...) by prefixing, keeps the extension (format detection depends on it), and de-duplicates within
a batch with a numeric suffix. It is covered by a Hypothesis property: for any input the result is
non-empty, contains no separator, does not start with a dot, and resolves inside the batch directory.

### D6. Review runs the real parser, in a worker thread

The review page calls the pipeline's dry run. A 50,000-record file takes about as long to review as to
import (the roadmap target is under a minute), and confirming repeats the parse. That is accepted in
return for a review that cannot disagree with the import. Both run in sync route handlers, so Starlette
uses its thread pool and the event loop (and the `/healthz` probe) stays responsive. The review page
says how long the last file took. Caching a parse between review and confirm was rejected: it adds
state, and the determinism guarantees rest on there being one parse path.

The lock is taken only for the writing step.

### D7. Mapping and sheet choice reuse the CLI's meaning

A CSV or TSV that matches no platform profile fails the dry run with the pipeline's own error. The
review then shows the file's header row and a select per target field (title, authors, year, DOI...),
turns the selection into the same mapping string `--map` takes, and re-runs the dry run. Parsing that
string moves from `cli/main.py` into `ingest` so both surfaces share it. A workbook's sheet names come
from a small read-only helper next to the xlsx parser. Both helpers are domain code and belong in
`ingest`, not in the routes.

### D8. Drag and drop is a few hundred lines of static JavaScript

`static/dropzone.js` (about 3 KB; the whole UI stays far below the spec's 50 KB) finds
`[data-dropzone]` wrappers around a real `<input type="file" multiple>`. On drop it assigns the
dropped files to the input, lists them (name, size) in the page and in the existing live region, and
marks the zone with text as well as colour. It ignores drops that carry no files, and folders (checked
through the entry API where the browser offers it). It never submits, never calls `fetch` or
`XMLHttpRequest`, and holds no token; submission is the ordinary form post, so every server-side
check is the one that already runs.

*Rejected:* uploading with `fetch` for a progress bar. It would need a second request shape, would
not work without JavaScript, and would reimplement the validation the form post already gets.

### D9. Who ran a search

The form's "run by" select defaults to the signed-in actor and lists other active actors, because the
CLI's `--by` names the person who ran the search, and the `Actor` trailer follows it. The importer is
always the signed-in actor. This keeps parity with the CLI. On a hosted instance, where the signed-in
user is a real account, restricting that select belongs to `add-hosted-team-deployment`.

### D10. The lock becomes an OS lock

`repo_lock` is rewritten on `fcntl.flock` (POSIX) and `msvcrt.locking` (Windows) over a persistent
`.strata/lock`, with the holder's PID written into it for the timeout message. The kernel releases the
lock when its holder dies, so a crashed process cannot strand it. If the file still names a PID when
the lock is acquired, the previous holder did not exit cleanly, and that is reported.

*Rejected:* probing whether the recorded PID is alive (races, PID reuse, different on each platform,
and a dependency or `ctypes` on Windows). The timeout, message and 30-second wait are unchanged.

### D11. Details of the later groups

- **Correct a record**: a form on `/records/<id>` listing only the fields `strata fix` allows.
- **Add a criterion**: `/criteria/new`. The impact preview the editor shows cannot be reused as it
  stands, because it needs a criterion that already exists. The page states that a new criterion is
  recorded as tightened and links to the criteria list; building a true preview is an open question.
- **Assign**: stage, actors from the configured list, optional filter validated by the same filter
  parser, with the count of records matched shown before saving.
- **Retrieve**: outcomes only. The `--path` option is deliberately not offered.
- **Studies**: suggestions are computed on view and never applied without a submitted choice.

## Risks / Trade-offs

- **[Moving the CLI onto shared operations changes the CLI]** → Snapshot tests of output, exit codes,
  files and commit messages are written first and must pass unchanged after each move.
- **[Switching `repo_lock` to OS locks, then taking it everywhere, is a behaviour change on all three
  platforms]** → It is exercised by a multi-process test on the full OS matrix, including a holder
  killed with SIGKILL (and terminated on Windows). Network filesystems that fake `flock` are
  documented as unsupported for the working copy, as git itself advises.
- **[Large uploads hold a request open for as long as the import takes]** → Documented; the limit
  defaults to 100 MB; the review step says how long parsing took. A background job runner is out of
  scope.
- **[The unconfirmed-search state]** → Reported by the dashboard; consistent with the CLI.
- **[The client-side drop code is untestable in the Python suite]** → Everything it does is also done
  by the no-JS form, which the suite exercises; a Playwright smoke test marked `browser` is run
  nightly where the browser is installed, plus a manual checklist for releases. The project does not
  take Playwright as a required development dependency.
- **[A user uploads a file in the wrong format and a half-recorded search results]** → The review step
  catches it; the search page offers "add files" so recovery needs no terminal.
- **[`run by` lets one person record a search as another]** → Parity with `--by`; revisited for
  hosted use.

## Migration Plan

1. Land the shared-operations move for `search add` and `import` with snapshot tests, then the lock
   change, then upload plumbing, then the screens. Each is its own pull request against an unchanged
   specification until the screens arrive.
2. No data migration. Repositories written through the web are indistinguishable from those written
   through the CLI.
3. Rollback is removing the routes; nothing they write is in a format the CLI cannot read.

## Open Questions

- **Supplying a `PENDING` query.** Search files are immutable and the CLI has no command that fills
  one in, so today the only route is a superseding search, which counts as a second search. Whether
  filling a missing query is a correction (and may edit the file) or a new version is a protocol
  question for the project lead. This change builds nothing web-only; the screen offers what the CLI
  offers.
- **An impact preview for a new criterion.** Worth building if the staleness engine can answer "what
  would adding this make stale" without an existing criterion id.
- **The default upload limit.** 100 MB comfortably holds a 50,000-record RIS file. It is a setting, so
  the number can move.
- **Whether to take the lock around the existing web write routes too.** They share the problem the
  lock solves but are outside this change's scope.
