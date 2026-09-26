# Design: web-ui

*Informative.* The requirements are in [spec.md](spec.md). Hosted, multi-user
operation is being planned in the `add-hosted-team-deployment` change; this
document describes the local server that exists today.

## Why a web UI at all

Screening is a high-volume, click-heavy, visually dense task. Reading a
250-word abstract in a terminal is worse than reading it in a browser, and a
doctoral student running her first review will not adopt a tool that requires
her to live in a terminal. For screening, extraction, and adjudication the web
UI is the primary surface, not a second-class one.

## Why strictly local by default

No account, no login, no CDN, no analytics, no third-party fonts: the UI works
on a plane and in a hospital network that blocks everything, and nothing leaves
the machine. The server is stateless with respect to the repository — it reads
and appends to the same event log as the CLI — so a user can screen in the
browser and commit from the terminal without conflict.

## The screening surface

The one screen that must be excellent:

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

## The criteria editor

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

## Why server-rendered HTML

A tool researchers will rely on for years should not carry a JavaScript
dependency tree that rots in eighteen months. FastAPI + Jinja2 + a small
hand-written keyboard module, working with JavaScript disabled, is both an
accessibility requirement and a hedge against the frontend rotting.

## Why accessibility is normative

Screening is repetitive work done for hours; reviewers with RSI, low vision, or
motor impairments are a real and under-served part of this user base.

## Why a localhost server needs security

Any page in the user's browser can issue requests to `127.0.0.1`. The session
token, CSRF tokens, `SameSite=Strict` cookies, and Origin/Host validation (which
defeats DNS rebinding) close that hole; the inactivity exit means a forgotten
tab does not leave a writable endpoint open indefinitely.
