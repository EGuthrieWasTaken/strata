# M6 ("Hardening and adoption") — implementation notes

Modelled on [`m5-plan.md`](m5-plan.md). M6 is ongoing; this file records what has been built so far and
what is deliberately partial.

## Status

| Change | What | Status |
|---|---|---|
| `add-review-repository-ci` | `strata init --ci`, the reusable workflow `.github/workflows/review-ci.yml`, the `actions/verify` composite action, `strata ci amendment` and `strata ci comment` | written and tested locally; 5 of 8 tasks open until it runs on GitHub (see below) |
| `add-web-ui-write-surfaces` | Write screens in the browser: record a dated search and attach its export by file chooser or drag and drop with a review before anything is imported; correct a record; add a criterion; assign reviewers; record retrieval outcomes; group and split studies. A shared operations layer under the command line and the web | all tasks written and tested; the full local gate is green (2,889 tests, coverage 94.96 %, diff coverage 96 %, determinism identical) and the pull-request gate has passed in CI on Linux, macOS and Windows (task 7.3); the manual gate (task 7.4: someone who has never used the command line does it unaided) has not been run by a person |
| `add-zotero-integration` | `strata zotero link\|pull\|push\|status\|open`, the local and Web API clients, the identity mapping `integrations/zotero.ndjson`, full texts through Zotero in `retrieve` and `screen`, a keychain-or-environment key | all tasks but 5.1 written and tested against a stand-in for Zotero 6 and 7; **never run against a real Zotero** (see below), so 5.1 is open |
| `add-ai-participation` | A per-review AI policy (off by default), agents as registered actors, the `agent` envelope key, suggestions with blinding, MCP write tools, a ledger, computed disclosure, `strata ai revoke`, `strata audit --ai`, schema format 2 and `strata migrate` | groups 1 to 4 written and tested locally; open: the CLI refactor of tasks 3.1 and 3.2 and the methodologist's read of the disclosure (5.4); the three-platform runs (1.4, 4.5, 5.3) passed in CI on the pull request that merged it; see below |
| `add-distribution-and-adoption` | task 2.4: EndNote XML, Excel and plain-text citation-list import | done; the rest (PyPI/binaries/Homebrew, Covidence/Rayyan/EPPI imports, worked example, translations) not started. The nightly `cold-install` job (task 4.2) runs on all three platforms but only installs the package and runs `strata --help`; it does not yet run the quickstart its step name promises |

## add-review-repository-ci

- **What a review team gets.** `strata init my-review --ci [--ci-ref REF] [--methodologist LOGIN]` writes
  `.github/workflows/strata.yml` into the first commit. On every pull request that workflow runs
  `strata verify` (the check fails on any violation), comments what the change does to the review
  (records entering and leaving the pool, decisions invalidated, screening conflicts opened, analyses made
  stale) and, when `protocol/criteria.yaml` changed as data, labels the pull request `protocol-amendment`
  and asks the methodologist to review it.
- **`status --json` grew two fields per stage** (`included`, `stale_included`), additive, so the comment can
  say how many *included* papers sit behind invalidated decisions. It says "could leave the pool": what
  re-screening decides is not known until it happens.
- **Fork pull requests** get the verify check but not the comment, label or review request, because the
  trigger is `pull_request` (a read-only token for forks), not `pull_request_target`.
- **How it was checked.** Unit tests render the comment from fixture status documents; integration tests
  run `strata init --ci`, `strata ci amendment` and `strata ci comment` on real repositories, check the
  generated workflow against the reusable workflow's inputs and permissions, require third-party actions to
  be pinned to commits, and execute the reusable workflow's `run:` steps with a fake `gh`. actionlint 1.7.12
  accepts both workflow files.

### Partial or deliberately left for later

- **Never run on GitHub.** Nothing here has run on an Actions runner: the real `gh` behaviour, the
  permissions the called workflow gets from the caller, `GITHUB_ACTION_PATH` in the composite action and the
  `uv tool install git+https://…@<ref>` line are as written, not as observed. Open a pull request against a
  scratch review repository with `--ci-ref <branch>` to try it.
- **Nothing is tagged.** The default ref in an installed workflow is `v<version>`, which exists only after a
  release is tagged (`release.yml`); until then pass `--ci-ref`.
- **Required check.** Making `strata verify` a required status check is a branch-protection setting in the
  review repository; `init --ci` does not (and cannot) set it.
- **GitHub only.** The helper commands are provider-neutral; only the workflow files are GitHub Actions.

## add-distribution-and-adoption, task 2.4: the three deferred parsers

- **EndNote XML** (`ingest/parsers/endnote_xml.py`): each `<record>` is parsed on its own (it runs to the
  next `<record>`, so one that never closes cannot swallow its neighbours); an `&` that starts no valid
  entity is escaped and HTML entities are unescaped afterwards; a record containing a DOCTYPE or entity
  declaration is rejected and declarations outside the records are never applied.
- **Excel** (`ingest/parsers/xlsx.py`): standard library only. Caps: 50 MB file, 200 MB unpacked, 250,000
  rows, 512 columns, 100,000 characters per cell. A formula's cached value is read, never evaluated; dates
  stored as numbers arrive as Excel's serial numbers. The sheet becomes TSV text and goes through the TSV
  column mapping, so `--map` and the platform profiles work unchanged. Encrypted workbooks and legacy
  `.xls` are refused with advice.
- **Plain-text citation list** (`ingest/parsers/citation_list.py`): numbered or paragraph-separated
  references in Vancouver (`Authors. Title. Journal. 2019;12(3):45-67.`) and APA (`Authors (2019). Title.
  Journal, 12(3), 45-67.`) layouts, plus DOI and PMID wherever they appear. Anything else is rejected with
  its entry. Records carry `strata.flags: ["best-effort-parse"]` and are never auto-merged.
- **Found by fuzzing**: a corrupt member header made `zipfile` raise `BadZipFile`/`ValueError`; a row
  number of a billion would have yielded a billion blank rows; both now end in a clean refusal.
- **Not done**: the Covidence, Rayyan and EPPI-Reviewer migration imports (2.1-2.3), which need real export
  samples this project does not have; the XLS (legacy) format; reading dates formatted as dates.

## add-zotero-integration: what was built and what was found

- **Layout.** `strata.integrations.reference_manager` is the generic boundary (resolve, pull, push, open) and
  imports nothing else. `strata.integrations.zotero` implements it: `http` (the one place a socket is
  opened; loopback never goes through a proxy), `api` (`Backoff` and `Retry-After`; a wait over two minutes
  is refused, not slept), `probe` (is the local API there and shaped as read), `connect` (local first, Web
  for writes or on mismatch), `credentials`, `mapping`, `matching` (the canonical-key ladder), `manager`,
  `operations` (what each command does) and `retrieval`. The command line only gathers arguments and
  presents results.
- **Never run against a real Zotero.** Everything is tested against `tests/zotero_fake.py`, which serves
  `tests/fixtures/zotero/` the way the API v3 documentation says Zotero does, for Zotero 6 (no local API) and
  Zotero 7 (read-only local API). The assumptions are listed in the change's `tasks.md`. Until a person has
  run `strata zotero link` against a running Zotero 7 and a real Web API key and compared a capture with
  `library.json`, task 5.1 stays open.
- **The rules, and the test that holds each.** Core workflows reach neither Zotero nor the keychain
  (`test_every_core_workflow_runs_with_zotero_absent_and_never_mentions_it`); a push sends only a
  collection list for an item it did not create and never a DELETE
  (`test_a_push_never_deletes_and_never_sends_more_than_membership_for_an_existing_item`, and the same
  through `link --web` and `push` in `test_zotero_operations.py`); an item edited since `strata` last saw
  it is refused, including in the instant between the check and the write (Zotero's own per-object 412); no
  key reaches the repository or its history (`test_link_never_puts_the_api_key_in_the_repository`).
- **Defects found on the way**, each now fixed: the `strata retrieve` menu had never shown its key letters
  (Rich dropped `[f]`, `[u]`, `[n]` as markup), which would have hidden the new `o` and `z`; `strata import`
  validated the import manifest after writing the records, so a manifest it could not record left a
  half-made import; and a first version of `link` and `pull` demanded a rationale before knowing whether
  they had anything to commit, refusing a harmless rerun.
- **Decisions to confirm.** A pull takes exactly one of `--search` and `--via`, as `strata import` does (the
  specification says both "requires a `--search` id" and "tagged with the correct `--via`"). Zotero never
  *removes* a field a record has; a pull only adds or corrects. A push never writes the fields of an
  existing item, even one `strata` created, because Zotero wins on bibliographic metadata.
- **Changes to existing capabilities** the proposal did not list (import manifest `collection`, full-text
  manifest `zotero`, `[zotero]` in `strata.toml`, `integrations/*.ndjson merge=union`) are named in the
  change's `tasks.md` for `/opsx:update`.
- **Not done.** An on-disk cache of items by version; Zotero state in the web interface; mirroring
  screening state as tags and reading PDF annotations (post-1.0 in the design).

## add-zotero-integration: manual checks with a real Zotero

None of these has been run.

- [ ] **Zotero 7, local API on**: `strata zotero link` says "through the local API", asks for no key, and
      matches the records the library holds; with the setting off it names the setting; with Zotero closed it
      says Zotero is not running and (with a key) falls back to the Web API.
- [ ] **A collection of a real size** (a few thousand items): `strata zotero pull` finishes, and a second
      pull changes nothing.
- [ ] **A group library**: `link --library groups/<id> --web` with a key that can write, and one that
      cannot, report the permission at link time; a push to the group adds to the collection.
- [ ] **A push over an edited item**: edit an item in Zotero after linking, push, and see that one item
      refused and the rest added; pull it, push again, and see it added.
- [ ] **Attachments**: a library item with a PDF, one with only a snapshot, one with a link, one with
      nothing: the queue's lines match, `o` opens the PDF in Zotero, and `strata zotero open` does the same.
- [ ] **A keychain**: on macOS, Windows and Linux with a Secret Service, the key is asked for once and then
      found; on a machine with none, `STRATA_ZOTERO_API_KEY` works and the not-stored notice appears.
- [ ] **Rate limits**: a pull from a large library through the Web API waits when Zotero says `Backoff`
      or `Retry-After`.

## add-web-ui-write-surfaces: what was built and what was found

- **One implementation under two surfaces.** `strata.core.operations` holds the operations that write and
  commit (`record_search`, `import_file`, `amend_record`, `add_criterion`, `assign_reviewers`,
  `record_retrieval`, `group_reports`, `split_report`); the command line and the web screens only gather
  arguments, ask for a rationale and present the result. Pin tests written *before* each command was moved
  (`test_cli_search_import_snapshots.py`, `test_cli_record_ops_snapshots.py`, `test_cli_m3_snapshots.py`) hold
  the command line's text, files and commit messages exactly; equivalence tests then run each action through
  both surfaces on identical reviews and compare the commit.
- **Defects found on the way**, each now fixed with a test that failed first:
  - Every form in the web interface was refused by a real browser: the `Referrer-Policy: no-referrer` header
    made browsers send `Origin: null`, which the origin check rejects. Test clients never showed it; a real
    Chromium did. The policy is now `same-origin`.
  - A web dedup merge left `derived/counts.json` stale (the identified and duplicate counts did not move)
    until a command-line operation next regenerated it.
  - `strata import` and `strata search add` wrote their files and then crashed on a commit subject over 72
    characters when a file or database name was long, leaving the work uncommitted.
  - The dashboard's tables overflowed a 320 px screen. The tables on the pages this change added now stack as
    labelled cards at that width. The older tables elsewhere were checked later by the page tests (below):
    they did overflow, and now scroll inside their own box.
  - The repository lock was a file whose existence meant "held": a killed `strata` locked everyone out until
    the file was deleted, and nothing took it. It is now an operating-system lock. Its tests run on
    Windows and macOS as well as Linux in CI, and pass.
- **Known gaps, deliberate.** Dismissing a study-grouping suggestion ("keep separate", "keep as one") is
  command line only. The interactive sessions of `strata retrieve` and `strata studies` stay on the command
  line. `strata verify --fast` (the pre-commit hook) does not check derived drift, and `strata verify --fix`
  regenerates derived files but does not re-link chains or truncate partial lines; both are in
  [`Known-Limitations`](../wiki/Known-Limitations.md).
- **Follow-up, after review: `strata fix`.** It could not correct authors or years, re-importing a corrected
  export did not repair a record (a DOI matched the old record unchanged; without one the row became a second
  record), a corrected DOI left the identity the record is matched by as it was, and a value the record
  already had was still recorded. Now: authors and years are editable, identifiers are normalised as an
  import normalises them, an empty value removes a field, a no-op is not recorded, and a correction that
  changes the canonical key makes the new key's id an alias (the mechanism `record-identity` already
  described, and the import pipeline now follows). Not done: `strata dedup` is not run for you after a
  correction, and an alias is not made when a correction lands on another record's identity (it is named
  instead).
- **Follow-up, after review: `strata assign`, `strata verify`.** `strata assign` now refuses a handle that is
  not an active actor and lists the eligible ones. `strata verify` now reports `E_DERIVED_DRIFT`, which the
  specification had required since M1 and no one had implemented (`docs/m1-plan.md` records it as "still
  unimplemented"). Implementing it found that `strata init`, `import`, `dedup` and `fix` left derived files
  wrong; the commands now regenerate every derived view.

## add-web-ui-write-surfaces: found by the page tests

`scripts/seed_review.py` builds three reviews (a blank one, the Quickstart complete, and one with two
reviewers, a conflict, stale decisions and a record made of hostile markup) in about fifteen seconds, and
`tests/browser/test_pages_browser.py` walks every screen of them in Chromium. Run against the code as merged
it failed on four things; each is fixed, and `tests/unit/test_web_static_accessibility.py` holds the fixes in
the pull-request gate, where the browser tests do not run:

- **The screening progress bar never filled.** It set its width with a `style=` attribute and the
  Content-Security-Policy is `style-src 'self'`, so a real browser dropped it. It is now a native `<progress>`.
- **The drop target's border was 1.6:1 against the page in light and 1.9:1 in dark** (3:1 is required). It
  uses a new `--border-strong`.
- **Tables pushed the page sideways**: `/records` and `/history` at 320 px (200-400 px too wide),
  `/adjudicate`, `/extract/<study>`, and `/analysis/<id>`, whose study table was 539 px too wide even on a
  1024 px screen. Tables that do not stack as cards now scroll inside a keyboard-focusable box.
- **A title with no spaces pushed the page sideways** (a DOI, a URL, markup): the screening card and a record's
  page were 210 px too wide at 320 px. Words now break anywhere when they must.

What it found and did not need to fix: markup in a title or abstract (`<script>`, `<img onerror>`, a closing
`</main>`) is shown as text on the records table, a record's page and the screening card, and runs nothing.

Still open: the tables on `/records` and `/history` scroll sideways at 320 px rather than stacking into labelled
cards as the newer tables do; a table that stacks reads better on a phone.
Each scroll box is also a tab stop whether or not its table overflows, so a keyboard user passes through one
more stop per table; making it a stop only when it overflows needs a few lines of script.


## add-web-ui-write-surfaces: manual checks for the new screens

The browser test in `tests/browser` (Node and Playwright, skipped where they are not installed) drives
Chromium through reaching the file chooser by keyboard, dropping files, posting the form, reviewing and
importing, and checks for script and Content-Security-Policy errors and for sideways scrolling at 320 px.
`tests/browser/test_pages_browser.py` (same requirements, run in Chromium over reviews built by
`scripts/seed_review.py`) now judges what a script can: reflow at 320 px and 640 px on every screen,
contrast in light and dark, reduced motion, the flow with JavaScript off, and that markup in a record runs
nothing. Items it covers are ticked below and say so. A person still has to check what a script cannot judge.
**None of the others has been run by a person yet**, and
neither has task 7.4, the gate for the whole change: someone who has never used the command line records a
search and imports its export in the browser, unaided. Record the outcome here when it is done.

- [ ] **Keyboard only**, in a real browser: reach every control of `/searches/new`, the review page and the
      results page with Tab and Shift-Tab, choose files with Enter or Space on the file control, submit with
      Enter. Focus is visible on every control, and the order follows the page.
- [ ] **Screen reader** (NVDA or VoiceOver): choosing or dropping files is announced ("2 files chosen: ..."),
      the review table's columns are read with their headings, the "already imported" and error messages are
      announced, and the "Only files can be dropped here" message is heard after dropping text.
- [ ] **200 % zoom and 320 px width** *(sideways scrolling: covered by script for every screen at 320 px and 640 px; whether anything is cut off or hard to read still wants eyes)*: nothing is cut off or needs sideways scrolling on `/`, `/searches`, a
      search page, `/searches/new`, the review page and the results page; the tables read as labelled cards.
- [x] **Reduced motion** (`prefers-reduced-motion: reduce`): the drop target changes with no animation. *(by script, not by a person: `test_reduced_motion_stops_the_drop_target_transitioning` finds no transition or animation under `reduce`, and finds the drop target transitioning without the preference, so the check is not vacuous)*
- [x] **Dark mode** (`prefers-color-scheme: dark`): the drop target, its dragging state, the warning flags and
      the error messages all keep their contrast (4.5:1 for text, 3:1 for the border). *(by script, not by a person: `test_contrast_holds_in_light_and_dark` measures 4.5:1 for text and 3:1 for the drop target's border (also while dragging), error boxes, warning flags and the screening buttons in both schemes; it found the drop target at 1.6:1 light and 1.9:1 dark, now 4.5:1 and 5.4:1)*
- [ ] **Colour is never the only signal**: with colour removed (a greyscale filter), a search with no query, a
      search with no export, a file that cannot be imported and the dragging state are each still
      distinguishable by an icon or by words.
- [x] **JavaScript disabled**: record a search with a file, review, and import, using only the ordinary file
      chooser; nothing is missing but the drop box. *(by script, not by a person: `test_a_search_can_be_recorded_imported_and_screened_without_javascript`)*
- [ ] **Firefox and Safari** (the browser test uses Chromium): the same flow, in particular that a form post
      is accepted (the referrer policy was `no-referrer`, which makes browsers send `Origin: null`).



## add-ai-participation: what was built and what was found

`strata` ships no model and makes no network call; this change is the accounting for the ones a review
brings. Everything is off by default and a review that never enables it stays in format 1 and behaves as it
did.

### What was built

- **Format 2 and `strata migrate`** (`core/migrate.py`): forward-only, idempotent, one commit with the
  person's rationale, a step table the next bump will reuse. `strata ai enable` runs it in the same commit.
  A build limited to format 1 refuses a format 2 review (`E_SCHEMA_TOO_NEW`).
- **The policy and agents** (`core/agents.py`): `[ai]` and `[ai.policy]`, eleven kinds of work, three modes;
  agent actors (`kind`, `model`) registered with `strata actor add --kind agent --model`, matched on the
  model name exactly; `E_CONFIG` rules in `core/manifest.py`; `strata ai enable|policy`.
- **The `agent` envelope key** between `actor` and `seq`, covered by the digest, with its own keys sorted like
  every canonical object. A person's event serialises byte for byte as before (a golden line produced by the
  pre-change serialiser pins it). Attribution is carried by `events.agent_scope`, so no write path an agent
  can reach can record an unattributed event, and an agent's write refuses an event under any other handle.
- **Suggestions** (`protocol/suggestions.py`, `core/agent_ops.py`): `dry_run` on the real operations so a
  suggestion is validated exactly as the real one would be; adopt runs the operation as the person with their
  rationale and links it in the same commit; reject keeps the reason; supersession; blinding; the web screen.
- **MCP** (`mcpserver/server.py`): reads always, 17 write tools only when AI is enabled and the person is
  known; policy checked per call; commits authored by the agent and committed by the person with trailers;
  confined file arguments; instructions that state the policy.
- **The ledger and disclosure** (`core/ledger.py`, `report/disclosure.py`): one source for `strata ai report`,
  `strata status`, `strata audit --ai`, the Methods text and checklist items 8, 9 and 11.
- **`strata ai revoke`**, reusing the stale queue with the reason `agent-revoked`.

### Things found on the way

- **The fold counted unassigned actors.** `resolve_screening` reduced every actor's events and compared their
  number with the number assigned, contrary to the written rule (`opinions = latest event per assigned
  actor`), and the default assignment was every `screener` and `lead`. An unassigned agent would have been a
  free second reviewer and a registered agent with the role `screener` a reviewer by default. Both are fixed
  for everyone; `strata verify` warns (`W_UNASSIGNED_OPINION`) about a record an existing unassigned opinion
  used to help resolve, and the CHANGELOG says so.
- **`strata serve --actor` and the analysis actor could name an agent**, which would have written an agent's
  work under its handle with no attribution. Both now refuse an agent.
- **`strata why` did not list screening decisions** although its specification says it should. It now does,
  once a record is decided (so as not to unblind a reviewer), with the AI label where it applies.
- **A suggestion visible in `list --by` could not be shown by `show`.** Caught by running the commands for the
  wiki; `show` takes `--by` too.

### Deviations from the tasks as written, and why

- **`invoked_by` must be a registered person, not an *active* one**, in `strata verify` (task 1.7). A person
  deactivated after invoking an agent must not turn their past events invalid. The server still requires an
  active, non-observer person at the time of the call.
- **The ledger is `core/ledger.py`, not `core/agents.py`** (task 4.1): it reads the suggestion fold, which
  imports `agents`, so it lives beside it.
- **An agent that is deactivated is refused by `actor deactivate`** whether or not it has history (task 1.3):
  one door, `strata ai revoke`, which also puts its counted decisions back in the queue.
- **Previews for count-mode criteria changes** are recorded in the commit trailer `Strata-Impact` rather than
  in the criteria event, whose schema is fixed.

### Partial or deliberately left for later

- **Tasks 3.1 and 3.2 are not done.** The command line still assembles the screening, adjudication,
  extraction, risk-of-bias, criteria-edit, criteria-retire, deduplication, analysis and report commits itself.
  Agents reach those operations through `core/agent_ops.py`, which calls the same protocol functions and
  commits with `commit_domain_work`, so a command and a tool record the same event body (tested), but they do
  not yet share the commit code. Only the PRISMA diagram was moved onto `core/operations.py`.
- **`strata report` is not offered to agents** (generating the Methods, Results and checklist text); the
  reserved-operations test names it so it cannot be forgotten.
- **Three platforms: done.** The pull request that merged this change passed the `test` matrix on Linux,
  macOS and Windows, the coverage floors and diff coverage, `determinism`, `traceability`, `docs`, CodeQL
  and the container jobs (1.4, 4.5, 5.3). The `determinism` job compares hash seeds on Linux only, by
  design; the cross-platform byte-identity claim is carried by the committed golden lines.
- **The project's pinned OpenSpec (1.13.2) was not run**; the change validates with the installed 1.16.0.
- **The model name is the agent's own claim**, and an agent with a shell bypasses the policy: both are stated
  in the wiki and in `Known-Limitations`, and neither can be fixed from here.

### What the local gate measured

On Linux only: `ruff` and `mypy --strict` are clean. The whole suite passed (3,614 tests, 95.02 % total
coverage) before the last round of tests, which was added to close the diff-coverage gap. A targeted run of
the 537 tests that exercise this change then measured diff coverage of 99 % against the base (CI needs 95 %).
The whole suite was not run again after that round, which also removed two properties nothing used
(`Ledger.suggestions` and `PrismaRendered.draft`); CI was the check on the final tree, and it passed.

### Manual gate (task 5.4)

**Not done, and not claimed.** A methodologist reads the generated disclosure for (a) a review that used
suggestions and (b) a review that used a counted reviewer, and judges whether it is accurate and sufficient.
Record the outcome here when it has been done.

- [ ] Suggestions only: the Methods paragraph and checklist items 8, 9 and 11 for a review like the one in
      `tests/unit/test_ledger_and_disclosure.py` (1,200 suggestions, 1,050 adopted, 150 rejected).
- [ ] A counted reviewer: the same, for a review in which an assigned model screened records as a second
      reviewer, including the agreement sentences and "two people and one AI model".
- [ ] Wording a reviewer would be uncomfortable putting under their name (for example the caveat that the
      model name is the model's own report), and anything a journal might ask for that is missing.
