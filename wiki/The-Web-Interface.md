# The web interface

`strata serve` opens the same review in your browser. It is the same folder and the same commits as the
command line; there is no separate account, database or cloud. Use whichever you prefer for each task, or
both.

```
strata serve --actor ada
```

```
strata serve listening on http://127.0.0.1:52734/?token=...  (actor: ada)
```

It opens your default browser at that address (`--no-browser` to suppress). `--actor` says who you are
screening as; it is required if the review has more than one actor. Stop it with Ctrl+C.

## What is in it

| Screen | Address | For |
|---|---|---|
| Dashboard | `/` | The same as `strata status`: where each stage stands and what to do next |
| Screening | `/screen/title-abstract`, `/screen/full-text` | One record at a time with the criteria numbered beside it; keyboard-driven |
| Re-screening | `/rescreen/<stage>` | The stale queue, with your previous decision and why it is stale |
| Adjudication | `/adjudicate/<stage>` | Conflicts, with both opinions side by side |
| Criteria | `/criteria` | Edit or retire a criterion, with a **live impact preview** (how many decisions the change would put in doubt) *before* you save |
| Duplicates | `/dedup` | The review queue for doubtful duplicates |
| Records | `/records`, `/records/<id>` | A searchable table (the same `--filter` language) and a record's full detail and provenance |
| History | `/history` | The domain-level log: who did what, and why |
| Extraction | `/extract`, `/extract/<study>` | The coding form, with the effect size shown as you type; reconciliation at `/extract/<study>/reconcile` |
| Risk of bias | `/rob`, `/rob/<study>` | Domain-by-domain assessment with the algorithm's suggestion |
| Analyses | `/analysis`, `/analysis/<id>` | The committed results and plots, and whether they are stale |
| PRISMA | `/prisma` | The flow diagram |

Retrieval and study grouping are command-line only so far.

## A tour

The screenshots below are from the spacing-effect example review used in the [Quickstart](Quickstart).

**The dashboard** answers "where am I and what next?", the same as `strata status`.

![The dashboard: each stage with its counts, stale decisions and the suggested next step](https://raw.githubusercontent.com/wiki/EGuthrieWasTaken/strata/images/web-dashboard.png)

**The criteria page** lists every criterion with its current version. Edit and Retire are buttons beside each one.

![The criteria page listing inclusion and exclusion criteria with Edit and Retire buttons](https://raw.githubusercontent.com/wiki/EGuthrieWasTaken/strata/images/web-criteria.png)

**The impact preview.** Fill in the new wording, choose the direction, give a reason and press **Preview**.
Nothing is saved: the page lists the decisions that *would* go stale, each with the rule that put it in doubt
(see [Staleness](Staleness)). Only **Save and commit** records the change. The Preview button needs the reason
filled in first; it is a required field.

![The criteria editor with the impact preview listing ten decisions that would become stale](https://raw.githubusercontent.com/wiki/EGuthrieWasTaken/strata/images/web-criteria-preview.png)

**Re-screening** shows the stale queue: your earlier decision, why it is stale, and the buttons to include,
exclude, mark maybe or **keep your previous decision** (`k`).

![The re-screening queue showing a stale decision with the reason it went stale](https://raw.githubusercontent.com/wiki/EGuthrieWasTaken/strata/images/web-rescreen.png)

**Records** is a searchable table using the same [filter language](Filter-Language) as `strata records --filter`.

![The records table with a filter box](https://raw.githubusercontent.com/wiki/EGuthrieWasTaken/strata/images/web-records.png)

**History** lists every commit with the operation and who made it (the same data as `strata log`), and can be
filtered by stage or actor.

![The history page listing each commit with its operation and actor](https://raw.githubusercontent.com/wiki/EGuthrieWasTaken/strata/images/web-history.png)

**Extraction** is the coding form for one study. Data-quality warnings come first, and each must be
acknowledged with a reason; below them every field has a box for the value and one for where in the paper it
came from. The effect size is worked out as you type.

![The extraction form for one study with data-quality warnings and the fields to fill in](https://raw.githubusercontent.com/wiki/EGuthrieWasTaken/strata/images/web-extract.png)

**Analyses** shows committed results, the warnings the guardrails raised (and whether you acknowledged them),
the plots, and flags any result that is out of date.

![An analysis page showing guardrail warnings, the pooled estimate and heterogeneity](https://raw.githubusercontent.com/wiki/EGuthrieWasTaken/strata/images/web-analysis.png)

**PRISMA** draws the flow diagram from the review's own counts. While anything is still stale or undecided it
is stamped **DRAFT**, with the reason in the banner above it.

![The PRISMA flow diagram, marked as a draft because screening is incomplete](https://raw.githubusercontent.com/wiki/EGuthrieWasTaken/strata/images/web-prisma.png)

## Screening from the keyboard

The screening screen is built to be driven without a mouse:

| Key | Does |
|---|---|
| `i`, `e`, `m` | include, exclude, maybe (on the re-screening screen `k` keeps your previous decision) |
| `1` to `9` | tick the criterion with that number. When exclusions must cite a reason, ticking one while excluding records the exclusion at once |
| `,` | jump to the note field (the other keys are ignored while you type) |
| `s` | skip for now |
| `u` | undo the last decision |

The page works with JavaScript switched off (it just reloads between records, and you click the buttons) and is
designed for screen readers: states are shown with text and an icon, never colour alone.

## Safe by design

Any web page in your browser can send requests to `127.0.0.1`, so `strata serve`:

- listens **only on your own computer** by default;
- generates a random **session token** at startup, delivered in the address it prints, kept in a cookie that
  other sites cannot read or send;
- accepts changes only as `POST` requests carrying a **CSRF token**, and checks the `Origin` and `Host` of
  every request (defeating DNS-rebinding);
- escapes everything it displays (an abstract containing `<script>` is shown as text);
- **exits after 60 minutes of inactivity** (`--inactivity-timeout SECONDS` changes it).

**Files the browser sends are held to the same standard.** `strata serve` refuses an upload larger than **100
MB** (`--max-upload-mb N` changes it) from the size the browser declares, before reading any of it, and refuses
one that does not declare a size, more than 20 files at once, and any ordinary form over 1 MB. A file name
from the browser is never used as a path: it is cleaned (folders, odd characters and device names such as
`CON` are removed) and kept only as a label. An uploaded file waits in a private folder inside the review
(`.strata/tmp/uploads/`) until you confirm it, is deleted when you confirm or discard it, when the server
starts, and after an hour, and is never committed. Only the bibliographic exports `strata import` understands
are taken; a PDF is refused, because `strata` does not store full texts.

`--host 0.0.0.0` (to reach it from another machine) is refused unless you also give `--token`; if you put it
behind a proxy or a published container port, tell it the address people will use with `--public-url`. This is a
tool for you or your team on a trusted network, not a public website. See [Running in a
container](Running-in-a-Container) for the container case.

## What it writes

Screening in the browser appends the same decisions to the same files as the command line and commits them
with the same trailers, so `strata log`, `strata why` and `strata sync` see no difference. A screening session
is committed when you leave the screen.

## Also available to AI assistants (read only)

`strata mcp` runs a **read-only** [Model Context Protocol](https://modelcontextprotocol.io/) server over
standard input and output, exposing status, provenance, log, records, criteria diffs and the impact preview of
a criteria change, to an MCP-aware assistant you point at a review (`strata -C /path/to/review mcp`). It can
read; nothing it offers can write.
