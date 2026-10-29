# Tasks

Each group lands its own tests and wiki changes (`openspec:test-suite#every-change-carries-its-tests`;
the wiki is updated in the same pull request as the screen it describes). Groups 1 to 4 are the
searches-and-imports core and are independently useful; groups 5 and 6 each ship on their own after
that.

## 1. Shared operations for searches and imports

- [x] 1.1 Before touching `cli/main.py`, add snapshot tests that pin `strata search add` and `strata import` as they are (stdout, exit code, written files, commit message and trailers; `--no-commit`, `--dry-run`, `--json`, and a multi-file import where the second file fails); verify they pass on the unmodified code
- [x] 1.2 Add `core/operations.py` with `record_search`, `import_files` and `rationale_problem`, moving commit assembly out of the two commands, and make both commands call them; verify the 1.1 snapshots pass unchanged and `ruff` and `mypy --strict` are clean
- [x] 1.3 Move parsing of the `--map` string out of `cli/main.py` into `ingest`, and add read-only helpers that return a CSV or TSV header with its detected platform profile and a workbook's sheet names; verify with unit tests, including the malformed fixtures from the existing fuzz corpus
- [x] 1.4 Add the equivalence test for the operations layer: the same search and the same import through `strata` and through `operations` leave identical files and commit messages once ids and timestamps are normalised; verify it passes and fails when a trailer is changed

## 2. The repository lock

- [x] 2.1 Rewrite `repo_lock` on OS-level locks (`fcntl.flock`, `msvcrt.locking`) over a persistent `.strata/lock` that records the holder's PID, keeping the 30-second timeout and the message that names the holder, and reporting a lock left by a process that did not exit cleanly; verify with unit tests for contention, the timeout message, and a holder killed with SIGKILL (terminated on Windows) after which the lock can be taken and the reclaim is reported
- [x] 2.2 Add a multi-process test in which a CLI import and a second writer run against one repository at the same time; verify both commits land and the test passes on the Linux, macOS and Windows jobs
- [x] 2.3 Take the lock in `record_search` and `import_files` for the write only, never for a dry run; verify with the 2.2 test and a check that `--dry-run` and a review leave no `.strata/lock` holder behind
- [x] 2.4 Document the lock in the wiki's recovery page (what the message means, that a crashed process no longer needs a manual cleanup, and that network drives are unsupported for a working copy) and in the CHANGELOG; verify `scripts/check_wiki.py` passes

## 3. Upload handling (`web-uploads`)

- [x] 3.1 Add `strata serve --max-upload-mb` (default 100) and carry it in the app state; verify with a CLI test of the default, an override and a non-positive value, and regenerate the command reference with `scripts/build_wiki_reference.py`
- [x] 3.2 In the security middleware, refuse a multipart request with no length (411) or over the limit (413) before the form is read, naming the limit, and pass explicit file-count and field-size limits when parsing; verify with tests for an oversize file, a chunked request, too many files and a raised limit, each asserting nothing exists under `.strata/tmp/` and the repository is clean
- [x] 3.3 Verify the order of checks for a multipart request: a foreign `Origin`, no session, and a missing CSRF token each leave nothing staged (extend `tests/integration/test_web_security.py`)
- [x] 3.4 Add `web/uploads.py` with the file-name sanitiser; verify with unit cases (traversal, both separators, reserved device names, empty and dot-only names, Unicode, over-long names, duplicates in one request) and a Hypothesis property that any input gives a non-empty name with no separator, no leading dot, that resolves inside the batch directory
- [x] 3.5 Add the staging store (batch ids, `batch.json`, create, open, discard, purge by age and at startup); verify with tests for a forged id containing separators, an unknown id, an expired id, a purge at start-up, and that `strata status` reports a clean tree while a batch is staged
- [x] 3.6 Refuse anything `strata import` does not recognise, using the same detection, and explain for PDFs that full texts are not stored; verify against the golden parser fixtures (accepted exactly when the CLI accepts them) and a PDF
- [x] 3.7 Document upload limits in the wiki's web interface page and `Known-Limitations` (the limit, no progress bar, parse time on large files); verify `scripts/check_wiki.py` passes

## 4. Searches and imports in the browser

- [x] 4.1 Add `/searches` and `/searches/<id>` (date, hits, query status, attached files, imports and their counts) and link them from the dashboard, the records page and the pending-search notice; verify with tests for rendering, the pending flag, the notice linking to the search, and a query and notes containing `<script>` being escaped
- [x] 4.2 Add `/searches/new` (database, platform, date defaulting to today, query, hits, notes, run by, peer reviewer, rationale, optional files; pre-filled with `supersedes` when re-running) posting to `operations.record_search`; verify with tests for today's date, an earlier date, a missing query recorded as `PENDING`, a superseding search leaving the earlier file unchanged, a duplicate id shown as an error, and a missing rationale writing nothing
- [x] 4.3 Add the review page, running the dry run for each staged file and showing format, rows read, new, matched and rejected rows with reasons, the "already imported" case, the header-and-select mapping control for unrecognised CSVs, and the sheet chooser for workbooks; verify each scenario under "Review before importing" with a test, and that review leaves `git status` clean
- [x] 4.4 Add confirmation, calling `operations.import_files` once per file and showing per-file results; verify that two files give two commits, that confirming twice does not import twice, and that a failing file leaves the search recorded
- [x] 4.5 Add `/import` for the methods `--via` accepts; verify the PRISMA counts for a registry import equal the command line's
- [x] 4.6 Add `static/dropzone.js`, its styles and the live-region announcements; verify the whole shipped JavaScript stays under 50 KB (a test), that no page needs it (the suite runs without it), a manual checklist (keyboard only, 200% zoom, 320 px width, reduced motion, screen reader announcement), and an optional Playwright smoke test marked `browser` that drops two files
- [x] 4.7 Add the equivalence tests for the web: one search and one import through the web and through the CLI give byte-identical search files and identical trailers, records, manifests, events and counts once ids and timestamps are normalised; and an end-to-end test that takes a repository from a recorded search to deduplicated records using only HTTP requests
- [x] 4.8 Update the wiki (`Searching-and-Importing` with an "in the web interface" section, `The-Web-Interface`, `Cheat-Sheet`, and the quickstart's note that the web interface can do this) and the CHANGELOG; verify `scripts/check_wiki.py` and `scripts/check_docs.py` pass

## 5. Record corrections, criterion add, assignment

- [ ] 5.1 Pin `strata fix` with a snapshot test, move it onto a shared operation, and add the correction form on `/records/<id>`; verify allowed and refused fields, the provenance timeline showing the change, and CLI equivalence
- [ ] 5.2 Pin `strata criteria add` with a snapshot test, move it onto a shared operation, and add `/criteria/new` stating that the criterion is recorded as tightened; verify a missing rationale writes nothing and that the criteria version and the stale set equal the command line's for the same criterion
- [ ] 5.3 Pin `strata assign` with a snapshot test, move it onto a shared operation, and add `/assign/<stage>` showing how many records a filter matches before saving; verify a bad filter shows the parser's message and records nothing, and that assigned reviewers' queues contain the records
- [ ] 5.4 Update the wiki pages for these screens and the CHANGELOG; verify `scripts/check_wiki.py` passes

## 6. Full-text retrieval and study grouping

- [ ] 6.1 Pin `strata retrieve` with a snapshot test, move it onto a shared operation, and add `/retrieve` with the outcome form and no file or path control; verify `retrieved` needs a source, `not-retrieved` needs a reason, the page has no upload control, and the event equals the command line's
- [ ] 6.2 Pin `strata studies` with a snapshot test, move it onto a shared operation, and add `/studies` showing suggestions with evidence and the group and split forms; verify that viewing and leaving records no event, that accepting a suggestion lowers the study count, that a split is recorded as the command records it, and that a rationale is required
- [ ] 6.3 Update `Retrieving-Full-Texts`, `Grouping-Reports-into-Studies`, `Known-Limitations` and the CHANGELOG; verify `scripts/check_wiki.py` passes

## 7. Integration and close-out

- [ ] 7.1 Verify `openspec validate add-web-ui-write-surfaces --strict` passes with no warning from this change, and that no `openspec:` reference in code, tests or docs fails `scripts/check_docs.py`
- [ ] 7.2 Add a note to `openspec/changes/add-hosted-team-deployment/design.md` that browser imports come from this change, and update `README.md` (status), `docs/roadmap.md` (M6 and M5.1) and `docs/m6-plan.md`; verify the documentation checks pass
- [ ] 7.3 Run the full local gate (`ruff`, `mypy --strict`, `pytest` with the coverage floors and diff coverage, and the determinism check) and verify it is green on Linux, macOS and Windows in CI
- [ ] 7.4 Have someone who has never used the command line record a search and import its export in the browser, unaided, and record the outcome in `docs/m6-plan.md` (a manual gate, like the M2 usability session; it is not claimed until a person has done it)

## Workflow follow-up

- Archive the change after review, and confirm `openspec/specs/web-ui`, `architecture` and the new `web-uploads` capability read correctly.
- Open follow-up changes for the rows the proposal deferred (analysis authoring and running, report and export downloads, a conflict screen for `sync`, read-only audit and agreement views) when their time comes.
