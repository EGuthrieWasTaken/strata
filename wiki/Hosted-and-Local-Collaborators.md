# Hosted and local collaborators

One review can have collaborators on a [hosted instance](Running-a-Hosted-Instance) and collaborators running
`strata` on their own machines at the same time. They all share the review's git remote: the instance syncs
with it automatically; a local collaborator runs `strata sync` as usual ([Working with others](Working-with-Others)).

## Why this does not conflict

Each reviewer's screening decisions are appended to their own files in the review, so a decision made in the
browser and one made on a laptop never touch the same file. When both have synced, the instance and every
clone hold the same event log with everybody's decisions in it, with no conflict to resolve for screening,
adjudication or duplicates.

## What the instance does

- **Before showing a page**, it brings in what others pushed, if it last looked more than 30 seconds ago
  (`sync.interval_seconds`). So a page can be a few seconds behind the remote; it never loses anything.
- **After each change**, it pushes. Screening decisions are saved the moment you make them and committed in
  batches, one per reviewer: after 200 decisions, after 15 quiet minutes, when you sign out, and before every
  sync.
- **If the remote cannot be reached**, your work stays committed on the instance and the push is retried:
  after 30 seconds, then 1, 2, 4 minutes and so on, up to every 15 minutes, until it gets through. The page
  header says so:

  > ⚠ The remote could not be reached at the last sync; your work is kept here and will be pushed when it can be.

Every page of a project shows when it last synced; **Sync** in the page header shows the detail (the remote,
the last sync and push, anything waiting) and has a **Sync now** button.

## A local collaborator's decisions

They appear on the instance after the collaborator has run `strata sync` *and* the instance's next pull (at
the latest 30 seconds after someone opens a page). Likewise the instance's decisions reach a laptop at its next
`strata sync`.

## When two people edit the same text

Concurrent edits to text a person wrote (a criterion's definition, `question.md`) can conflict: for example a
lead rewords `EXC-03` in the browser while a colleague pushes a different wording from their laptop. Then:

1. The instance stops where `strata sync` would stop: nothing is merged half-way, nothing is pushed, and its
   copy stays exactly as it was. Work on the instance carries on and is committed as usual.
2. **Pushes for that project stop** until a lead resolves it. Every page of the project says so.
3. A lead opens **Sync** and sees both versions, in terms of the review (`EXC-03 definition: mine ... |
   theirs ...`), with three choices for each file: **keep mine** (the instance's), **keep theirs** (the
   remote's), or **edit** the text into what it should be.
4. The instance then completes the sync and pushes. Members without the lead role see that a lead is needed,
   but not the choice.

Nothing is ever resolved silently or dropped.

## Leaving the instance

A project is an ordinary review repository on your remote. Clone it (`strata clone <url>`), run
`strata verify`, and you have every decision anyone recorded on the instance.
