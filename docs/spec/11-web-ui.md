# 11 — Local web interface *(normative)*

## 1. Why a web UI at all

Screening is a high-volume, click-heavy, visually dense task. Reading a 250-word
abstract in a terminal is worse than reading it in a browser, and Priya (the
doctoral student in [00 §5](00-overview.md)) will not adopt a tool that requires
her to live in a terminal. The web UI is not a second-class surface; for
screening, extraction, and adjudication it is the primary one.

It is, however, **strictly local**:

- `strata serve` binds to `127.0.0.1` on an ephemeral port by default and opens a
  browser. Binding to any other interface requires `--host` **and** `--token`,
  and the tool MUST print a warning explaining the exposure.
- There is no account system, no login, and no multi-tenancy. The person at the
  keyboard is the actor configured in `strata.toml`, selectable at startup when
  more than one actor is configured on the same machine.
- No data leaves the machine. No CDN, no analytics, no fonts fetched from a
  third party, no error reporting. All assets are bundled and served locally, so
  the UI works on a plane and in a hospital network that blocks everything.
- The server is stateless with respect to the repository: it reads and appends to
  the same event log the CLI uses, so a user can screen in the browser and commit
  from the terminal without conflict.

## 2. Screens

| Route | Purpose |
|---|---|
| `/` | Dashboard — the `strata status` content, with actions as links |
| `/screen/<stage>` | The screening surface |
| `/rescreen` | The stale queue, with prior decisions shown |
| `/adjudicate` | Conflict resolution |
| `/dedup` | Duplicate review queue |
| `/records` | Searchable, filterable record table |
| `/records/<id>` | Record detail with the `strata why` provenance timeline |
| `/criteria` | Criteria editor, with live impact preview |
| `/extract/<study>` | The coding form |
| `/extract/<study>/reconcile` | Field-by-field reconciliation |
| `/rob/<study>` | Risk-of-bias instrument |
| `/analysis/<id>` | Results, plots, and guardrail warnings |
| `/prisma` | The flow diagram, live |
| `/history` | Domain-level history from commit trailers |

## 3. The screening surface

The one screen that must be excellent.

```
+--------------------------------------------------------------------------+
|  Title/abstract screening            1,482 of 2,918      18.4 s/record    |
|  [##############################............]  51%       ~7.6 h remaining |
+--------------------------------------------------------------------------+
|                                                                          |
|  Spacing effects in learning: A temporal ridgeline of optimal retention   |
|  Cepeda, Vul, Rohrer, Wixted & Pashler · Psychological Science · 2008     |
|                                                                          |
|  We investigated the effects of distributed practice on retention of      |
|  verbal material in 1,354 adult participants across four *retention       |
|  interval* conditions ranging from 1 day to 1 year...                     |
|                                                                          |
|  [ i ] Include        [ e ] Exclude        [ m ] Maybe                    |
|                                                                          |
|  Exclusion criteria                                                       |
|   1  EXC-01  Not empirical                 4  EXC-04  Wrong population    |
|   2  EXC-02  Animal model                  5  EXC-05  Wrong outcome       |
|   3  EXC-03  Not in English                6  EXC-07  Mean age under 18   |
|                                                                          |
|  [ u ] undo   [ n/p ] navigate   [ ? ] help   [ / ] search   [ , ] note   |
+--------------------------------------------------------------------------+
```

### 3.1 Requirements *(normative)*

| # | Requirement |
|---|---|
| S1 | Every action has a single-key shortcut; the pointer is never required |
| S2 | A decision is visibly acknowledged in under 100 ms; persistence is asynchronous but append-before-advance |
| S3 | Exclusion with a criterion is one keystroke (`e` then a digit), or a digit alone when `require_exclusion_reason` is set and a digit implies exclusion |
| S4 | Multiple criteria may be cited on one exclusion ([06 §4.3](06-workflow-screening.md)) |
| S5 | A criterion's full definition is shown on hover and on keyboard focus |
| S6 | User-configured terms are highlighted in title and abstract |
| S7 | `u` undoes the previous decision by appending a correcting event, and can be pressed repeatedly |
| S8 | Closing the tab and returning resumes at the same record |
| S9 | Records with no abstract are visually flagged, never silently skipped |
| S10 | Another reviewer's decision is never shown while `blind_reviewers` is set |
| S11 | Author, journal, and year are hidden while `blind_metadata` is set |
| S12 | Works offline; no network request leaves the machine |
| S13 | A note can be attached to any record without leaving the keyboard |
| S14 | The queue order is deterministic and recorded, so two reviewers can be given the same order or deliberately different ones |

### 3.2 Re-screening mode

Identical, with the prior decision and the staleness reason displayed
prominently, and a fourth action `[k] keep previous` ([06 §6](06-workflow-screening.md)).

## 4. The criteria editor

The live impact preview is what makes protocol changes feel safe rather than
frightening:

```
  Editing EXC-03 · Not in English

  Definition
  +----------------------------------------------------------------+
  | Publications not written in English, and publications in       |
  | English translation where the original instrument was not      |
  | validated in the translated language.                          |
  +----------------------------------------------------------------+

  How does this change the set of papers the criterion excludes?
  ( ) Tightened   (o) Loosened   ( ) Both   ( ) Editorial

  IMPACT PREVIEW                                      (nothing saved yet)
    42 decisions would become stale
       42 excluded citing EXC-03 -> must be re-screened
    2,876 decisions remain valid
    Estimated re-screening: ~13 minutes

  Why are you making this change?
  +----------------------------------------------------------------+
  |                                                                |
  +----------------------------------------------------------------+

  [ Cancel ]                                        [ Save and commit ]
```

The preview MUST be computed without mutating anything, MUST update as the
direction radio changes, and MUST be recomputed on save in case the repository
changed underneath.

## 5. Technology *(normative)*

- **Server-rendered HTML with progressive enhancement.** No SPA framework, no
  build step required to run from source. A tool researchers will rely on for
  years should not carry a JavaScript dependency tree that rots in eighteen
  months.
- Recommended stack: FastAPI (already a dependency for the local server) +
  Jinja2 + htmx for partial updates + a small hand-written keyboard-shortcut
  module. Total shipped JavaScript SHOULD stay under 50 KB uncompressed.
- All assets vendored into the package. No external requests, enforced by a
  strict `Content-Security-Policy` with no external origins.
- The UI MUST function with JavaScript disabled, at reduced convenience (full
  page loads per decision instead of partial updates). This is both an
  accessibility requirement and a hedge against the frontend rotting.

## 6. Accessibility *(normative)*

WCAG 2.1 Level AA, specifically:

- Full keyboard operability with a visible focus indicator on every control.
- Semantic HTML and correct ARIA roles; the decision buttons are buttons.
- Colour contrast at least 4.5:1 for text and 3:1 for UI components.
- Never colour alone: include/exclude/conflict states carry an icon and a text
  label as well as a colour.
- A live region announces each recorded decision to screen readers.
- Honour `prefers-reduced-motion` and `prefers-color-scheme`.
- Text reflows to 320 px width without horizontal scrolling, and remains usable
  at 200% zoom.

Screening is repetitive work done for hours; reviewers with RSI, low vision, or
motor impairments are a real and under-served part of this user base.

## 7. Security *(normative)*

Even a localhost server is attack surface — any page in the user's browser can
issue requests to `127.0.0.1`.

- A random session token is generated at startup and required on every mutating
  request, delivered via the opened URL and stored in a `SameSite=Strict`,
  `HttpOnly` cookie.
- All mutating requests are `POST`/`PUT`/`DELETE` and carry a CSRF token.
- The `Origin` and `Host` headers are validated on every request, which defeats
  DNS rebinding against a localhost binding.
- All user-supplied content (titles, abstracts, notes) is escaped on output.
  Abstracts from database exports routinely contain HTML.
- File paths supplied by the user (PDF locations, import files) are resolved and
  checked to be within permitted roots; no path traversal.
- The server exits after 60 minutes of inactivity by default, so a forgotten tab
  does not leave a writable endpoint open indefinitely.
