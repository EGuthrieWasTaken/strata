# Chrome pass: going through `strata serve` by hand, with Claude in Chrome

*For the person running this.* Start Claude Code on your own machine with the Chrome extension connected
(`claude --chrome`), in a checkout of this repository on the branch you want to test, and say:

> Read `docs/chrome-pass.md` and do what it says.

It builds three scratch reviews (about fifteen seconds), serves them locally and clicks through them. It
writes `chrome-pass-results.md` next to them and changes nothing in your checkout. Bring that file back to the
maintainer session, which ticks off what it supports. Part H, optional, does the same for a hosted instance
(`strata host`) with two Chrome profiles.

*Revised after the first pass.* The first run ([`chrome-pass-results.md`](chrome-pass-results.md), on commit
`ceb67a9`) showed that several expectations in the earlier version were wrong, not the product. This version
corrects the record counts (W3 imports a record, which K2 and W6 forgot), what the digit keys do, what V7 and
D4 can show, the claim that `localhost` is refused, the order of the last two checks, and the shared session
cookie, and it asks for the console to be read from the first page. Two parts changed letter: the check that
breaks the PRISMA page is now Part F, and the optional sample exports are Part G.

*Revised again after the fixes for #83 to #91.* The nine issues the first pass filed are fixed, so the checks
that used to say "known: #N" now say what a fixed build shows: screening decisions are committed when you
leave the screen (K2), a digit ticks a reason and only `e` excludes (K2), a split report no longer stops the
flow diagram (Part F), each server keeps its own session cookie, the record page and History give the reason
and the date (W4, V5), the stale counts say what they count (D3), and Part H covers the hosted instance.

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

- **Stay on `127.0.0.1`.** Open only the servers you start. Sign in nowhere, except in Part G and only when
  the person tells you to.
- **Use the URL a server prints, exactly** (it has `127.0.0.1`, a port and `?token=...`). Opening it sets the
  session cookie; after that you can go by path. **Cookies ignore ports**, so the four servers below share one
  cookie jar and the one you opened last replaces the others' cookie (known: #85). Every time you switch to
  another server, open that server's token URL again before going by path.
- **Start reading the console on the very first page of Part A.** Your console tool may collect only from its
  first call, so make that call before you do anything else, and read it again after every page (C1).
- **Attaching files.** If your upload tool can read only certain folders, copy `~/strata-chrome-pass/exports/*`
  unchanged into one it can read (check with `sha256sum`) and say so. If your JavaScript tool refuses pages
  whose address has a query string, use plain paths after the first token visit.
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

## Issues fixed since the first pass

The first pass filed these; each is fixed, and the check named beside it now expects the fixed behaviour. If
you still see the old behaviour, that is a FAIL: quote what you see.

| Issue | Where you check it |
|---|---|
| #83 Local `strata serve` never committed screening decisions | K2, W5 |
| #84 Splitting a report made `/prisma` refuse to draw | Part F |
| #85 The session cookie was shared by every server on one host | whenever you switch server, X1 |
| #86 A digit key recorded an exclusion at once; skip and counter quirks | K2 |
| #87 Record page and History showed neither why nor when; counts disagreed | W4, W6, V5 |
| #88 Stale counts, assignments and analysis freshness were reported inconsistently | V7, D3, D4 |
| #89 `/records` and `/history` scrolled sideways rather than stacking | L1 |
| #90 Messages named internal settings and error codes | K2, D2, D5 |
| #91 The hosted UI was not covered | Part H |

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

(Pick other ports if one is taken.) Open each printed URL in a tab of its own. Each server keeps a session
cookie named after its port, so after the first visit you can go to any of the four by plain path, in any order.

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
| **N1** | Work through the task using only what is on screen. Time yourself. | MEDLINE: 8 rows, 7 new, 1 matched an existing record. Embase: 3 new. Duplicates: 2 pairs merged. The dashboard then shows 10 records (it counts the two merged duplicates; `/records` lists 8) and 8 to screen. |

Keep a **confusion log** as you go: every pause, every label you had to guess at, every message that did not
say what to do next, every place the page did something you did not expect, and every time you looked at the
wiki. For each: the page, what you were trying to do, what you expected, what happened, and whether it was a
blocker, confusing, or a nit. Also say how many steps it took and whether you trust that the result is right.

## Part B. The write screens (continue on `blank`)

| ID | Do | Expect |
|---|---|---|
| **W1** | Record a third search (CINAHL, EBSCO, hits 0) with the query box **empty** and no file. | Recorded; the dashboard and `/searches` say in words that its query is missing ("Missing (PRISMA item 7)") and that it has no export yet. |
| **W2** | Record a search and attach `spacing-medline.ris` again. | The review page recognises the file as already imported ("Already imported as ... Importing it again changes nothing") and offers nothing to import. (The page's first sentence says nothing has been imported yet, which is about this batch, and is followed by "Already imported as ...": say whether that reads as a contradiction.) |
| **W3** | Record a search and attach `full-text.pdf`. Then another with `broken.ris`. | The PDF is refused with a message that says why, in an error box, and no search is recorded. `broken.ris` reaches the review page: 3 rows read, 1 new, 2 rejected, and the two rejected rows are listed with the reason "missing or empty title"; nothing is imported until you confirm, and confirming imports only the one usable record. `blank` then shows 9 records on the dashboard, with "11 imported, 2 merged as duplicates" beside the number. |
| **W4** | Open a record. Correct its title; correct its authors (`Family, Given; Family, Given`); correct the year to a different year; clear a field; enter a value the record already has. Each needs a reason except the last. | Each correction appears in the record's timeline as a sentence ("ada corrected the title: it was ... and is now ...") with its date and, under "Why:", the reason you typed; a cleared field reads "removed the ...". No event names in capitals, no `None`. The last changes nothing and asks for no reason. `git -C ~/strata-chrome-pass/blank log --oneline -8` shows one commit per real correction. |
| **K1** | On `/searches/new`, the review page and the results page, use **only the keyboard** (Tab, Shift-Tab, Enter, Space). | Every control is reachable; focus is clearly visible on each; the order follows the page; Enter submits. The file control is reached and activated from the keyboard. *(Maps to the "Keyboard only" check in `docs/m6-plan.md`.)* |
| **K2** | On `/screen/title-abstract` (9 records, now that W3 has imported one), screen with keys: `i` include, `e` exclude, `s` skip, `u` undo, `,` jump to the note, and `1` to `9` to tick the reason with that number (numbered as `strata screen` numbers them; an inclusion criterion reads "Not met: ..."). First press a digit **alone** and wait; then press `e` on a record with nothing ticked. Then exclude "Sleep and memory consolidation in rats" (tick "Not human", press `e`) and the narrative review (tick "Not an empirical study", press `e`), and include the rest. Use `s` once on the way. Use `u` once and choose a **different** decision for that record. When the others are done, go on to the skipped record. Then go to the dashboard. | A digit alone ticks its box and records **nothing** (the record stays; `git status` shows no new decision). `e` with nothing ticked stays on the record and says "Tick at least one reason first ..." beside the buttons. The heading counts decisions ("3 of 9" means two are decided; a skipped record is not counted), and a line under it says how many are decided and how many skipped. After `u` the page says what you decided before and that a different decision needs a reason; choosing differently without one is refused in words, with one it is recorded. The skipped record is **offered again** when the rest are done ("These are the records you skipped"), not "Nothing left to screen". On reaching the dashboard the decisions **are committed**: the working tree is clean, `git -C ~/strata-chrome-pass/blank log -1` shows `screen(title-abstract): screen N records (...)` and its body lists the changed decision with your reason, and `strata status` shows 9 resolved at title-abstract. (The "Finish session" button under the form does the same.) |
| **W5** | On `/criteria/new` add an exclusion "Not a classroom setting" at title-abstract with a reason. Then run `git -C ~/strata-chrome-pass/blank log --stat -3`. | The form says it is recorded as **tightened**; after saving, the dashboard shows title-abstract decisions as **stale**: 7 (the seven includes; the two exclusions are not stale), and `strata status` agrees. The screening decisions from K2 were already committed when you left the screening screen, in a commit of their own (`screen(title-abstract): ...`, trailer `Strata-Actor: ada`), and the `criteria-add` commit holds no `events/screen` file. |
| **W6** | Last in this part: open the CINAHL search's own page (from W1) and attach `later.ris` there; review; import. | The review page says nothing has been imported yet and shows 2 rows, 2 new, 0 matched; after you confirm, the file shows as imported, the "no export" warning goes from that search, and the dashboard shows 11 records ("13 imported, 2 merged as duplicates"); `/records` lists the same 11 and says 2 more were merged and are not listed. |

## Part C. The finished review (`pipeline`; read before you write)

| ID | Do | Expect |
|---|---|---|
| **V1** | Compare the dashboard with `uv run strata -C ~/strata-chrome-pass/pipeline status`. | Same numbers: 10 records, 2 searches, criteria v4, title-abstract 8 resolved, full-text 5 resolved and 3 unscreened, extraction 4/4, one analysis. |
| **V2** | Open `/prisma`. | The counts table reads: identified 11, removed before screening 3, screened 8, excluded 2, reports sought 6, not retrieved 1, assessed 5, excluded 1 (reason "Spacing manipulated"), studies included 4. A line says the reconciliation identities hold. The diagram (open the SVG too) renders legibly, with no overlapping text, and is **not** stamped DRAFT. Switch to two columns and back. |
| **V3** | Open `/analysis/primary`. | Pooled SMD 0.476 (95% CI 0.147 to 0.805), 4 studies; warnings `k-lt-5` (acknowledged) and `hk-truncation`; leave-one-out has 4 rows. Open the forest plot: one row per study, a pooled diamond and a prediction interval, labels readable. Open the funnel plot and look at its outline (the black lines from the apex) and the shaded bands: **do all of them stay inside the box bounded by the two axes?** Say exactly what you see. (An earlier build drew the two lines out past both axes and into the margins.) The wide table of values scrolls inside its own box without moving the page. |
| **V4** | `/criteria/INC-02/edit`: change the definition and the direction, give a reason, press **Preview** (not Save). | The page lists the decisions that *would* go stale, each with its rule. Nothing is saved: criteria stay at v4 on the dashboard and `git -C ~/strata-chrome-pass/pipeline status --short` prints nothing. The address bar stays `/criteria/INC-02/edit` with **no** `?` part: neither your reason nor the session token may appear in it. Choosing another direction previews again by itself. |
| **V5** | Read `/records`, one record's page, and `/history`. | A reader can tell who did what, when and why: `/history` has When, Who, What and Why columns, and the record's provenance is sentences with dates (times are in UTC and say so). Filter the records table with `year >= 2018` and with a deliberately broken filter: the second shows the parser's message. |
| **V6** | `/extract`, one study's form, `/rob` and one study's assessment. | Pages load; the effect size shown matches the Quickstart's (Haddad & Ito 2019: yi 0.5276). |

Then, last in this review, because it changes it:

| ID | Do | Expect |
|---|---|---|
| **V7** | Repeat V4 but press **Save and commit**. | The number of decisions that become stale afterwards (dashboard and `strata status`) **equals** the number the preview listed. `/prisma` says DRAFT with the reason ("11 decision(s) are stale"). `/analysis` and `/analysis/primary` still read "current" (an analysis's freshness follows its inputs) and now say so: both explain what "current" means and carry a warning that 11 screening decisions are stale, so the results are provisional. |

## Part D. Two reviewers (`dual`)

Use the `sam` tab (8803) unless a check says `ada` (8804).

| ID | Do | Expect |
|---|---|---|
| **D1** | Dashboard as `sam`. | Warnings for the search missing its query (S-01-cinahl) and the two searches with no export. Title-abstract row: 5 resolved, 0 unscreened, 2 partial, 1 conflict, 4 stale; "Next: strata adjudicate". |
| **D2** | `/adjudicate/title-abstract` as `sam`, then as `ada`. | As `sam`: both opinions are shown (ada INCLUDE, sam EXCLUDE with EXC-01) and the page says, in a notice, that he can read the disagreement but not settle it (the setting is named in small print beneath), with a link back to the dashboard. As `ada`: it lets you resolve the conflict with a reason; after you do, the conflict count is 0. |
| **D3** | `/rescreen/title-abstract` as `sam`: for the first record press `k`, for the next press `i`. | The page shows the previous decision and why it is stale ("criterion-added"). `k` keeps the previous decision, `i` replaces it; `i` on a record whose previous decision was not include asks for a reason first ("Why the change?"). The heading counts **your** stale decisions ("4 of your decisions", then 3, ...) and the line under it says so; the dashboard's "Stale records" column counts records for the whole review, says so under the table, and its link reads "Rescreen N of your decisions". The two numbers need not match: say whether the page makes that clear. |
| **D4** | `/assign/title-abstract` as `ada`: type the filter `year >= 2018` and press **Check how many match**; then a broken filter (`year >>= 2018 and`); then assign `sam` to the records the valid filter matches, with a reason. | The valid filter shows "4 of 8 records match (nothing saved yet)" and saves nothing. The broken one shows the parser's message. Assigning is one commit and the page says "Assignment recorded". The confirmation names what was assigned ("4 records at title-abstract are now assigned to sam, and to nobody else"); "Who has what" shows Assigned, Decided and Waiting per reviewer (ada's Assigned falls by 4); "Assignments made at this stage" lists the assignment with its date, who made it and the filter. With the broken filter there is no Assign form, only a note to correct the filter. |
| **D5** | `/retrieve`: record one report as retrieved and one as not retrieved. Try "not retrieved" without a reason. | "Not retrieved" without a reason is refused in words ("Choose why the report could not be retrieved, under “Why not” ..."), not with a list of stored codes. Each recorded outcome appears on the page. |
| **D6** | **Hostile record.** As `sam`, open `/screen/title-abstract` and the record "Payload test ..." (find it on `/records` and open its page too). | Its title and abstract are displayed **as literal text**, including `<script>` and `<img ...>`; nothing runs; the browser tab's title is still the page's own ("title-abstract screening · strata"), not `PWNED`; the page has one heading and is not broken by the `</main>` in the abstract. |

## Part E. Across everything

| ID | Do | Expect |
|---|---|---|
| **C1** | After **every** page you open, read the browser console, starting with the very first page of Part A (see the rules: your console tool may collect only from its first call). | No errors. Write down any, with the page. (A 422 after attaching `full-text.pdf` in W3 is the server refusing it, and is expected.) |
| **L1** | Make the window as narrow as it will go and visit `/`, `/searches`, `/searches/new`, `/records`, a record, `/history`, `/criteria`, `/screen/title-abstract`, `/adjudicate/title-abstract`, `/analysis/primary`, `/prisma`. Try 200 % zoom as well if your tools can. (Chrome does not go below about 616 px wide: if that is all you can reach, say so; the page tests cover 320 px and 200 % zoom.) | The page itself never scrolls sideways; `/records` and `/history` stack into labelled cards when narrow; a wide table of numbers (`/analysis/primary`) scrolls **inside its own box**, which is a tab stop only while it has something to scroll. No word in a table is broken in the middle ("Yea/r"). Nothing is cut off, overlapped or unreadable. If you can run JavaScript, `document.documentElement.scrollWidth - document.documentElement.clientWidth` is 0 on each. *(Maps to the "200 % zoom and 320 px width" check.)* |
| **G1** | If you can run JavaScript: `document.documentElement.style.filter = 'grayscale(1)'`, then look at `/searches` on `dual` and the screening buttons. Reload to undo. | Warnings, errors and states are still told apart by an icon or by words ("Missing", "No export yet", "Include", "Exclude"), not by colour alone. *(Maps to "Colour is never the only signal".)* |
| **X1** | Open `http://127.0.0.1:8801/` **without** the token, in a private window or after clearing the site's cookies. | It is refused with no review data shown, and the message says what to do (open the address `strata serve` printed, the one ending in `?token=...`). The same URL with `?token=...` works, and after that the plain path works. Then open the other three servers by plain path, in any order: none of them asks for its token again. (`localhost` is accepted too, with a cookie of its own.) |

## Part F. Last: grouping and splitting studies (`pipeline`)

Do this after everything else in `pipeline`, because it changes which studies the review has.

| ID | Do | Expect |
|---|---|---|
| **W9** | `/studies`: group two included reports into one study with a reason; then split a report into two studies with a reason. Then open `/prisma`. | Each needs a reason and is its own commit; the grouping shows on the page and `strata log` shows both. After the split the review has 4 included reports and 5 studies. `/prisma` **draws the diagram** (a report that describes two studies is a decision, not a counting error): "Studies included 5", "Reports of included studies 4", and the line under the table says every reconciliation identity holds. No red box. |

## Part G. Only if the person tells you to: sample exports from other tools

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

## Part H. Only if the person tells you to: a hosted instance (`strata host`)

`tests/browser/test_hosted_browser.py` drives all of this in Chromium on every pull request; this part is the
same ground by hand. It needs **two Chrome profiles** (or one profile and a Guest window): a profile has one
cookie jar, so only one person can be signed in to an instance in it at a time. If you have one profile only,
do the checks for one person, sign out, and do the other's; mark H5 `BLOCKED`.

```bash
uv run python scripts/seed_hosted.py ~/strata-chrome-pass-hosted
uv run strata host --data ~/strata-chrome-pass-hosted/data --public-url http://127.0.0.1:8765 --port 8765 --insecure-local-testing
```

The first prints the three accounts (`ada` the lead, `sam` a screener, `olive` an observer) and their
password. The instance has two projects cloned from bare remotes under `remotes/`: `spacing` (the `dual`
review) and `disputed` (the same, where the lead and a collaborator reworded EXC-01 differently). It accepts
plain HTTP because it was told to; never serve it to anyone else. Stay on `127.0.0.1:8765`.

| ID | Do | Expect |
|---|---|---|
| **H1** | Open `http://127.0.0.1:8765/p/spacing/records` signed out. Sign in as `ada`. | You are taken to the sign-in page and, after signing in, to the page you asked for. The header names you, your actor and role, and the project. |
| **H2** | As `ada`: the project list (`/`), a project's dashboard, **Sync**, **Members**. Make the window narrow on each. | Each loads, none scrolls sideways, and the dashboard and the header say when the project was last synced with its remote. Members lists the three people with their actors and roles. |
| **H3** | In the address bar, look at the address after every form you submit on these pages. If you can run JavaScript: `[...document.forms].filter(f => f.querySelector('[name=csrf_token]') && f.method !== 'post').length`. | No address ever carries `csrf_token`; the expression is 0 on every page. |
| **H4** | In the second profile sign in as `sam`. Open **Members**, and `/p/spacing/adjudicate/title-abstract`. Then sign in as `olive` instead and try to screen a record. | `sam` has no Members link, and both pages refuse him (the adjudication queue shows both sides of a disagreement, so on an instance it is for adjudicators and the lead). `olive` can read the screens and has nothing she can record. |
| **H5** | With `ada` in one profile and `sam` in the other: as `sam` open `/p/spacing/screen/title-abstract`, note the record, and open its page under Records. As `ada` open the same record. | `sam` is not shown `ada`'s decision on a record he has not screened; `ada` sees her own. Both stay signed in throughout. |
| **H6** | As `ada` open `/p/disputed/-/sync` and press **Sync now**. Read the page, then look at it as `sam`. Then, as `ada`, choose **Keep mine** and resolve. | The page says pushes are stopped and shows the conflict in the review's terms: the file (`protocol/criteria.yaml`), what differs (EXC-01's definition), and both versions side by side ("Mine (this instance)", "Theirs (the shared remote)"). Only `ada` is offered the form; `sam` is told a lead resolves it. After resolving, the conflict is gone and "Last pushed" has a time. |
| **H7** | Sign out. Then, signed out, give a wrong password six times for one user name. | Signing out returns you to the sign-in page, and a project address asks you to sign in again. The first wrong password says the user name or password is not right; by the sixth the page says there were too many failed sign-ins and to wait. |

Stop the instance when you have finished. Leave `~/strata-chrome-pass-hosted/` where it is.

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
