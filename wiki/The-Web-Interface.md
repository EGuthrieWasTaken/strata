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
