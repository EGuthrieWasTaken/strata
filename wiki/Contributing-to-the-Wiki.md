# Contributing to the wiki

This wiki is written for **reviewers**, not implementers: people who know systematic reviews and may never
have used git. Keep it practical. A page should tell someone what to do, in what order, what they will see, and
what to check before moving on.

## Where the pages live

The pages are Markdown files in the **`wiki/`** folder of the
[main repository](https://github.com/EGuthrieWasTaken/strata), reviewed in pull requests alongside the change
that makes them necessary. When a change reaches `main`, a workflow copies `wiki/` to the GitHub wiki
(`strata.wiki.git`). **Edit the files in `wiki/`, not the wiki on GitHub**: the next publish overwrites it.

- One page per file: `Page-Name.md` is the page "Page Name". Links between pages are
  `[text](Page-Name)` (no `.md`); a link to a heading is `[text](Page-Name#heading-in-lowercase-with-dashes)`.
- `Home.md` is the front page and `_Sidebar.md` the navigation. Every page must appear in the sidebar.
- Pictures and example files go in `wiki/examples/` (or another subfolder) and are linked by their raw address.
- The pages under the heading **Command reference** are *generated* from the program's own help text by
  `scripts/build_wiki_reference.py`; do not edit them by hand. Change the help text in the code and
  regenerate.

## When you change `strata`

The pull request template asks: *does this change add or alter a user-facing command, web screen or concept,
and if so did you update the wiki page in the same pull request (or a fast follow)?* It is a prompt for the
reviewer, not a gate. The usual pages to touch:

| You changed | Update |
|---|---|
| a command or option | the stage guide that uses it, then regenerate the [Command reference](Command-Reference) |
| a setting | [Configuration](Configuration) |
| a warning, guardrail or error code | [Analysis](Analysis), [Extracting data](Extracting-Data) or [Recovery](Recovery-and-Troubleshooting) |
| a limit or a fix of one | [Known limitations](Known-Limitations) |

## Checks

```
uv run python scripts/build_wiki_reference.py       # regenerate the command reference
uv run python scripts/check_wiki.py                 # links, sidebar, commands in examples
```

`scripts/check_wiki.py` fails if a link points at a page or heading that does not exist, a page is missing from
the sidebar, a page the reference generator should own is out of date, or a `strata ...` example names a
command that does not exist. It runs in CI with the other documentation checks.

## Style

- Plain words first, the technical term second. Define a term where it first matters.
- **Show real output.** Run the command on a scratch review and paste what it prints; trim paths. The example
  data in `wiki/examples/` is invented on purpose.
- State limits plainly and link [Known limitations](Known-Limitations) rather than burying a caveat.
- Don't document what a command *might* do. If you have not run it, say so or leave it out.
- No screenshots of text; copy the text.
