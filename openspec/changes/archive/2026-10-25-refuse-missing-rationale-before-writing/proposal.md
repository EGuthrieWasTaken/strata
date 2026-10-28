# Proposal: Refuse a missing rationale before any file is written

## Why

`openspec:git-integration#eliciting-the-rationale` says a mutating command run
non-interactively without `--why` or `--why-file` "exits with code 7 and makes no
commit". The CLI honoured the exit code and the missing commit, but not the state
the command left behind: the rationale was elicited inside the commit step, after
the domain operation had written its files. A script that forgot `--why` got exit
code 7 and a dirty working tree: `strata actor add` left `strata.toml` modified,
and `strata dedup` left two auto-merges in `records/`, `events/dedup/` and
`derived/counts.json`. The dirty tree then made `strata sync` refuse and made
`strata verify` misleading, and the only way back was `git checkout . && git clean -fd`.

The same happened to a `--why` that the rationale rules reject (empty, stop-listed,
too short) or that points to an unreadable `--why-file`: it was refused at commit
time, after the work.

## What Changes

- Every mutating command checks, before its first write, whether it will need a
  rationale and can get one. If a rationale is required, none was given with
  `--why` or `--why-file`, and stdin is not a TTY, it exits with code 7 and has
  changed nothing. A `--why` or `--why-file` is validated at the same point, so
  one that would be rejected stops the command before the work, and an unreadable
  `--why-file` is reported as an error, not a traceback.
- Nothing else about the rationale changes. An interactive run is still prompted
  after the work, because the prompt tells the user what was done. `--no-commit`
  still needs none. Criteria changes, adjudications, study decisions and manual
  staleness marks still need one whatever `git.require_rationale` says, because the
  rationale is part of their event.
- `openspec:git-integration#eliciting-the-rationale` states the guarantee: a
  refused command changes no file. The "Script without a rationale" scenario says
  so, and two scenarios cover a rejected `--why` and `--no-commit`.

Milestone: M0 (git integration), already shipped.

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `git-integration`: the "Eliciting the rationale" requirement.

## Impact

- `src/strata/cli/main.py`: a `_preflight_rationale` helper, called ahead of the first
  write in `actor add|deactivate`, `search add`, `import`, `dedup`, `fix`, `screen`,
  `assign`, `rescreen`, `adjudicate`, `retrieve`, `studies`, `extract`, `rob`,
  `analyze`, `prisma` and `report`. The criteria commands, `rescreen --mark` and
  `studies --group|--split` already asked first and are unchanged.
- Some commands commit only if their work finds something to record. `strata dedup`
  and `strata import` therefore ask a check that writes nothing (`preview_dedup`,
  `import_file(dry_run=True)`) before they refuse, and only on the path that would
  refuse, so a rerun that would commit nothing (dedup with no duplicates, import of a
  file already imported) is not refused, and an import that fails reports its own
  error. Commands with no such check ask up front even when they would have ended with
  nothing to commit: `strata fix` to the value a field already has, and an
  interactive-mode session driven from a pipe that decides nothing. Pass `--why` (or
  `--no-commit`) as for any other run. Read-only modes (`--list`, `--check`,
  `--dry-run`, `--out -`, `report checklist --status`) are unaffected.
- A usage error in a command that has no such check (an unknown actor or stage, a field
  that cannot be corrected) is now reached only with a rationale in hand: without one
  the command exits with code 7 first.
- The web UI is unaffected: it validates the rationale before calling the domain
  operation.
- No schema-version bump; no change to events, records or commits.
