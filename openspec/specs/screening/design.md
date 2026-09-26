# Design: screening

*Informative.* The requirements are in [spec.md](spec.md).

## The two stages have opposite biases

**Title/abstract** is high volume (thousands of records) and low information.
It is optimised for speed — a reviewer should average 10–20 seconds per record —
and over-inclusion is the correct bias: a false exclusion here is invisible and
unrecoverable, while a false inclusion costs one full-text retrieval.

**Full text** is low volume and high information. It is slower, and exclusions
must cite a criterion because PRISMA requires reporting full-text exclusions
with reasons.

## Why blinding is not cosmetic

A reviewer who can see a colleague's judgement is not an independent rater, and
the review's reported inter-rater reliability becomes a fiction. Blinding is
therefore enforced by data layout as well as by the UI: each reviewer's events
live in their own file, so blinding survives someone poking around in the
repository — they would have to deliberately open someone else's file.

## Why single-reviewer mode is disclosed

Single screening is legitimate for pilots and scoping work, but it is a
limitation peer reviewers ask about, so generated Methods text states it
plainly.

## Why imported decisions are marked

Decisions imported from another tool are attributed to the declared actor but
marked `imported: true`, because their independence cannot be verified.

## The screening surface

The CLI and the web UI share one contract (keyboard-first, sub-100 ms,
undo-by-appending, definitions on focus, resumable, no dead ends). The web
screen is described in the `web-ui` design; persistence is append-then-advance
so an interrupted session loses nothing (E2E-09).
