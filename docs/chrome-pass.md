# Chrome pass: going through `strata serve` by hand, with Claude in Chrome

*For the person running this.* Start Claude Code on your own machine with the Chrome extension connected
(`claude --chrome`), in a checkout of this repository on the branch you want to test, and say:

> Read `docs/chrome-pass.md` and do what it says.

It builds three scratch reviews (about fifteen seconds), serves them locally and clicks through them. It
writes `chrome-pass-results.md` next to them and changes nothing in your checkout. Bring that file back to the
maintainer session, which ticks off what it supports. The hosted instance is not covered here: it is not part
of this branch.

---

*Everything below is addressed to the agent doing the pass.*

## What you are doing, and what you are not

You are **checking, not fixing**. You drive a real Chrome through the web screens of `strata serve` and write
down exactly what happened. Do not edit anything under `src/`, `tests/`, `docs/` or `scripts/`, do not commit,
do not push, and do not open a pull request. If something is broken, record it with the steps to see it and
move on.

Some checks cannot be satisfied by you, and you must never record them as passed: the usability sessions with
people who have not used the tool (`openspec:test-suite#usability-testing`), the unaided first-time-user gate
(`add-web-ui-write-surfaces` task 7.4), a screen reader, Firefox and Safari, and a methodologist's reading of
generated text. Part A is a *dry run* that finds problems before real people spend their time on them. It is
not the gate.

Rules for yourself:

- **Stay on `127.0.0.1`.** Open only the servers you start. Sign in nowhere, except in Part F and only when
  the person tells you to.
- **Use the URL a server prints, exactly** (it has `127.0.0.1`, a port and `?token=...`). Open it once per
  review to get the session cookie; after that you can go by path. `localhost` will be refused.
- **Never trigger a JavaScript dialog** (`alert`, `confirm`, `prompt`); it freezes the extension. The hostile
  record in Part D is built not to. If a dialog appears anyway, say so and stop that check.
- **If you cannot do a step with your tools, mark it `BLOCKED` and say why.** Do not fake it by editing the
  page, rewriting the DOM or posting forms from script. Reading the page, measuring it, resizing the window,
  reading the console and attaching a file through the extension's own upload are all fine, as far as your
  tools offer them.
- **Record what you saw, not what you expected.** Quote on-screen text exactly. A page that differs from this
  document is a finding (the document may be what is wrong; the maintainer decides).
- **Take a screenshot at every FAIL** and, if your tools can save one, save it under
  `~/strata-chrome-pass/screenshots/<check-id>.png`. Otherwise describe it.
- If a part is taking more than about twenty minutes, write down what you have and go on.

## Part 0. Setup

From the repository root (on Windows, use your shell's equivalent of `~`):

```bash
uv sync
uv run python scripts/seed_review.py ~/strata-chrome-pass
```

It prints the paths of `blank`, `pipeline`, `dual` and `exports`. If the folder exists from an earlier pass,
stop any servers and add `--force`. Then start four servers in the background (use your shell tool's
background mode, and read each one's first line of output for its URL):

```bash
uv run strata -C ~/strata-chrome-pass/blank    serve --no-browser --actor ada --port 8801 --inactivity-timeout 14400
uv run strata -C ~/strata-chrome-pass/pipeline serve --no-browser --actor ada --port 8802 --inactivity-timeout 14400
uv run strata -C ~/strata-chrome-pass/dual     serve --no-browser --actor sam --port 8803 --inactivity-timeout 14400
uv run strata -C ~/strata-chrome-pass/dual     serve --no-browser --actor ada --port 8804 --inactivity-timeout 14400
```

(Pick other ports if one is taken.) Open each printed URL in its own tab.

| Review | Served as | What it is |
|---|---|---|
| `blank` | `ada`, 8801 | Four criteria, nothing else. You will build it up. One reviewer. |
| `pipeline` | `ada`, 8802 | The wiki Quickstart, complete: 4 studies included, extracted, assessed, pooled; PRISMA drawn. Nothing stale. One reviewer. |
| `dual` | `sam`, 8803 and `ada`, 8804 | Two reviewers; 1 conflict; 4 stale decisions; 2 records `sam` has not screened; a search with no query; a search with no export; one record made of hostile markup. |

Create `~/strata-chrome-pass/chrome-pass-results.md` now with the template at the end of this file, and fill
it in as you go, so that nothing is lost if you are interrupted. Note at the top: the date, your operating
system, the Chrome version, `git rev-parse HEAD`, and which abilities you have (screenshot, click, keys,
run JavaScript, resize the window, attach a file, read the console).

You have a shell: use `uv run strata -C <review> status` and `git -C <review> log --oneline -5` to check what a
click really did. The server and the command line read the same files.

## Part A. A first-time user's dry run (do this first, on `blank`)

Do this **before** the other parts, because once you have seen the screens you are no longer a newcomer. Do
not open `src/`, `openspec/`, `tests/` or the other docs for this part. If you get stuck you may read the
section "Recording a search and importing its results" of [`wiki/The-Web-Interface.md`](../wiki/The-Web-Interface.md);
note each time you needed it and why.

Your task, as it would be given to a researcher who has never used the tool: *"This review is set up. Today
you searched MEDLINE (through Ovid) with the query `1. exp Learning/ 2. (spaced or distributed or massed)
adj3 practi*.ti,ab. 3. 1 and 2`, got 8 hits and exported them to `spacing-medline.ris`. You also searched
Embase (through Ovid) on 2 October 2026 with the query `spaced or distributed practice`, got 3 hits and
exported them to `spacing-embase.ris`. Both files are in `~/strata-chrome-pass/exports/`. Get both searches
and their results into the review, deal with any duplicates, and tell me how many records you have."*

| ID | Do | Expect |
|---|---|---|
| **N1** | Work through the task using only what is on screen. Time yourself. | MEDLINE: 8 rows, 7 new, 1 matched an existing record. Embase: 3 new. Duplicates: 2 pairs merged. The dashboard then shows 10 records and 8 to screen. |

Keep a **confusion log** as you go: every pause, every label you had to guess at, every message that did not
say what to do next, every place the page did something you did not expect, and every time you looked at the
wiki. For each: the page, what you were trying to do, what you expected, what happened, and whether it was a
blocker, confusing, or a nit. Also say how many steps it took and whether you trust that the result is right.

## Part B. The write screens (continue on `blank`)

| ID | Do | Expect |
|---|---|---|
| **W1** | Record a third search (CINAHL, EBSCO, hits 0) with the query box **empty** and no file. | Recorded; the dashboard and `/searches` say in words that its query is missing ("Missing (PRISMA item 7)") and that it has no export yet. |
| **W2** | Record a search and attach `spacing-medline.ris` again. | The review page recognises the file as already imported ("Already imported as ... Importing it again changes nothing") and offers nothing to import. |
| **W3** | Record a search and attach `full-text.pdf`. Then another with `broken.ris`. | The PDF is refused with a message that says why, in an error box, and no search is recorded. `broken.ris` reaches the review page: 3 rows read, 1 new, 2 rejected, and the two rejected rows are listed with the reason "missing or empty title"; nothing is imported until you confirm, and confirming imports only the one usable record. |
| **W4** | Open a record. Correct its title; correct its authors (`Family, Given; Family, Given`); correct the year to a different year; clear a field; enter a value the record already has. Each needs a reason except the last. | Each correction appears in the record's timeline with the old and the new value. The last changes nothing and asks for no reason. `git -C ~/strata-chrome-pass/blank log --oneline -8` shows one commit per real correction. |
| **K1** | On `/searches/new`, the review page and the results page, use **only the keyboard** (Tab, Shift-Tab, Enter, Space). | Every control is reachable; focus is clearly visible on each; the order follows the page; Enter submits. The file control is reached and activated from the keyboard. *(Maps to the "Keyboard only" check in `docs/m6-plan.md`.)* |
| **K2** | On `/screen/title-abstract` (8 records), screen with keys only: `i` include, `e` exclude, `1` to `9` tick a criterion, `,` jump to the note, `s` skip, `u` undo. Exclude "Sleep and memory consolidation in rats" with its criterion, exclude the narrative review with its criterion, include the rest, using `u` once and `s` once on the way (and come back to the skipped one). | Keys do what the wiki says; the progress bar visibly **advances** with each record (it did not before: it is now a native progress element); undo returns to the record; leaving the screen commits (`git log` shows a commit). Afterwards `strata status` shows 8 resolved at title-abstract. |
| **W5** | On `/criteria/new` add an exclusion "Not a classroom setting" at title-abstract with a reason. | The form says it is recorded as **tightened**; after saving, the dashboard shows some title-abstract decisions as **stale** and links to rescreen. Note how many; `strata status` must agree. |
| **W6** | Last in this part: open the CINAHL search's own page (from W1) and attach `later.ris` there; review; import. | The review page says nothing has been imported yet and shows 2 rows, 2 new, 0 matched; after you confirm, the file shows as imported, the "no export" warning goes from that search, and the dashboard shows 12 records. |

## Part C. The finished review (`pipeline`; read before you write)

| ID | Do | Expect |
|---|---|---|
| **V1** | Compare the dashboard with `uv run strata -C ~/strata-chrome-pass/pipeline status`. | Same numbers: 10 records, 2 searches, criteria v4, title-abstract 8 resolved, full-text 5 resolved and 3 unscreened, extraction 4/4, one analysis. |
| **V2** | Open `/prisma`. | The counts table reads: identified 11, removed before screening 3, screened 8, excluded 2, reports sought 6, not retrieved 1, assessed 5, excluded 1 (reason "Spacing manipulated"), studies included 4. A line says the reconciliation identities hold. The diagram (open the SVG too) renders legibly, with no overlapping text, and is **not** stamped DRAFT. Switch to two columns and back. |
| **V3** | Open `/analysis/primary`. | Pooled SMD 0.476 (95% CI 0.147 to 0.805), 4 studies; warnings `k-lt-5` (acknowledged) and `hk-truncation`; leave-one-out has 4 rows. Open the forest plot: one row per study, a pooled diamond and a prediction interval, labels readable. Open the funnel plot and look at its outline (the black lines from the apex) and the shaded bands: **do all of them stay inside the box bounded by the two axes?** Say exactly what you see. The wide table of values scrolls inside its own box without moving the page. |
| **V4** | `/criteria/INC-02/edit`: change the definition and the direction, give a reason, press **Preview** (not Save). | The page lists the decisions that *would* go stale, each with its rule. Nothing is saved: criteria stay at v4 on the dashboard and `git -C ~/strata-chrome-pass/pipeline status --short` prints nothing. |
| **V5** | Read `/records`, one record's page, and `/history`. | A reader can tell who did what and why. The record's provenance reads sensibly. Filter the records table with `year >= 2018` and with a deliberately broken filter: the second shows the parser's message. |
| **V6** | `/extract`, one study's form, `/rob` and one study's assessment. | Pages load; the effect size shown matches the Quickstart's (Haddad & Ito 2019: yi 0.5276). |

Then, last in this review, because they change it:

| ID | Do | Expect |
|---|---|---|
| **V7** | Repeat V4 but press **Save and commit**. | The number of decisions that become stale afterwards (dashboard and `strata status`) **equals** the number the preview listed. The analysis and PRISMA pages then say they are out of date or draft, with a reason. |
| **W9** | `/studies`: group two included reports into one study with a reason; then split it again with a reason. | Each needs a reason; each is its own commit; the grouping shows on the page and `strata log` shows both. |

## Part D. Two reviewers (`dual`)

Use the `sam` tab (8803) unless a check says `ada` (8804).

| ID | Do | Expect |
|---|---|---|
| **D1** | Dashboard as `sam`. | Warnings for the search missing its query (S-01-cinahl) and the two searches with no export. Title-abstract row: 5 resolved, 0 unscreened, 2 partial, 1 conflict, 4 stale; "Next: strata adjudicate". |
| **D2** | `/adjudicate/title-abstract` as `sam`, then as `ada`. | As `sam`: both opinions are shown (ada INCLUDE, sam EXCLUDE with EXC-01) and the page says `sam` is not an adjudicator and can only view. As `ada`: it lets you resolve the conflict with a reason; after you do, the conflict count is 0. |
| **D3** | `/rescreen/title-abstract` as `sam`: for the first record press `k`, for the next press `i`. | The page shows the previous decision and why it is stale ("criterion-added"). `k` keeps the previous decision, `i` replaces it; the stale count falls by one each time. |
| **D4** | `/assign/title-abstract` as `ada`: type a valid filter and press **Check how many match**; then a broken filter; then assign `sam` to a few records with a reason. | The valid filter shows "N of 8 records match" and saves nothing. The broken one shows the parser's message. Assigning is one commit. The "who is queued" table changes. |
| **D5** | `/retrieve`: record one report as retrieved and one as not retrieved. Try "not retrieved" without a reason. | "Not retrieved" without a reason is refused with a message. Each recorded outcome appears on the page. |
| **D6** | **Hostile record.** As `sam`, open `/screen/title-abstract` and the record "Payload test ..." (find it on `/records` and open its page too). | Its title and abstract are displayed **as literal text**, including `<script>` and `<img ...>`; nothing runs; the browser tab's title is still the page's own ("title-abstract screening · strata"), not `PWNED`; the page has one heading and is not broken by the `</main>` in the abstract. |

## Part E. Across everything

| ID | Do | Expect |
|---|---|---|
| **C1** | After **every** page you open, read the browser console. | No errors. Write down any, with the page. (A 422 after attaching `full-text.pdf` in W3 is the server refusing it, and is expected.) |
| **L1** | Make the window about 320 px wide (or use the narrowest your tools allow) and visit `/`, `/searches`, `/searches/new`, `/records`, a record, `/history`, `/criteria`, `/screen/title-abstract`, `/adjudicate/title-abstract`, `/analysis/primary`, `/prisma`. Then try 200 % zoom. | The page itself never scrolls sideways; a wide table may scroll **inside its own box**. Nothing is cut off, overlapped or unreadable. If you can run JavaScript, `document.documentElement.scrollWidth - document.documentElement.clientWidth` is 0 on each. *(Maps to the "200 % zoom and 320 px width" check.)* |
| **G1** | If you can run JavaScript: `document.documentElement.style.filter = 'grayscale(1)'`, then look at `/searches` on `dual` and the screening buttons. Reload to undo. | Warnings, errors and states are still told apart by an icon or by words ("Missing", "No export yet", "Include", "Exclude"), not by colour alone. *(Maps to "Colour is never the only signal".)* |
| **X1** | Open `http://127.0.0.1:8801/` **without** the token, in a private window or after clearing the site's cookies. | It is refused (no review data shown). The same URL with `?token=...` works, and after that the plain path works in that window. |

## Part F. Only if the person tells you to: sample exports from other tools

`add-distribution-and-adoption` tasks 2.1 to 2.3 (Covidence, Rayyan and EPPI-Reviewer imports) are blocked
because this project has no real export from any of them. Do this part **only** if the person says "go" in
this session, **only** in a browser they are already signed in to, and **only** for a review they name. These
exports can contain real study data and screening decisions.

- Ask which review to use, and prefer a small or throwaway one. Ask which formats to export.
- Save every export to `~/strata-samples/<tool>/`, never into this repository, and never upload, paste or
  send any of it anywhere.
- For each, write down: the menu path you used, the file name and type, the first ten lines (with titles and
  names replaced by `...`), the column or tag names, and what the tool says about screening decisions and
  duplicates.
- Stop and ask if you are asked to log in, to accept terms, to pay, or to change anything in that tool.

## When you have finished

Stop the four servers. Leave `~/strata-chrome-pass/` where it is. Tell the person where
`chrome-pass-results.md` is, and give them three lines: how many checks passed, failed and were blocked, and
the one or two findings that matter most.

## Results template

````markdown
# Chrome pass results

- Date, operating system, Chrome version:
- strata commit (`git rev-parse HEAD`):
- Abilities I had: screenshot / click / keys / run JavaScript / resize window / attach a file / read console
- Totals: PASS n · FAIL n · BLOCKED n · NOTE n

## Checks

| ID | Result (PASS / FAIL / BLOCKED / NOTE) | What I saw (quote on-screen text) | Evidence |
|---|---|---|---|
| N1 | | | |
| W1 | | | |

## Findings

1. **F1 · severity (blocker / major / minor / nit) · check ID · page**
   - Steps to see it:
   - Expected:
   - Actual:
   - Screenshot:

## Confusion log (Part A)

| Page | Trying to | Expected | Happened | Blocker / confusing / nit |
|---|---|---|---|---|

Steps taken: · Time taken: · Do I trust the result:

## Console messages

| Page | Message |
|---|---|

## Things I could not do, and why
````
