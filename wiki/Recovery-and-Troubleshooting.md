# Recovery and troubleshooting

When something looks wrong, start by looking, not fixing. Everything `strata` records is in git, so
nothing here needs a backup you do not already have: `git log` is the backup.

```
strata status          # where the review stands, and what to do next
strata verify          # validates every file; exit code 4 when something is wrong, with the file and a code
strata log             # the domain-level history (who did what, and why)
git status             # anything uncommitted
```

## What is authoritative

The events under `events/`, `strata.toml`, `protocol/`, `records/`, `imports/` and `analysis/*.yaml` are the
record. Everything under `derived/`, `reports/` and `analysis/results/` is regenerated from them: do not
repair those by hand, regenerate them with the command that produces them (`strata analyze`, `strata prisma`,
`strata report …`; `strata sync` regenerates `derived/` after a merge). Never edit an event file: it is a hash
chain, and a hand edit is exactly what `E_CHAIN` exists to catch.

## "My screening session was interrupted"

Decisions are appended to the event log and flushed as you make them; the commit is made when the session
ends. If the process died (a crash, a closed terminal, a dead battery) every decision you saw accepted is on
disk, uncommitted. Start `strata screen` again: it resumes with those records already done, and the commit
comes at the end of that session. `git diff` shows exactly what is waiting to be committed.

## `strata verify` says…

| Code | What it means | Usual cause and what to do |
|---|---|---|
| `E_SCHEMA` | a file does not match its JSON Schema | a hand edit, or a file from a newer `strata`. `git diff <path>` shows the change; `git checkout -- <path>` puts back the last committed version |
| `E_CHAIN` | an event file's hash chain is broken | a hand edit, or a merge done with plain `git` of a file two clones both appended to. If you have not pushed, `git reset --hard ORIG_HEAD` undoes the merge and `strata sync` redoes it properly (it puts the file back in order and re-links it, recording a `relink` event). If you have, restore the file from before the edit with `git checkout <good-commit> -- <path>` and add what was lost again |
| `E_DANGLING_REF` | an event names a record, criterion, actor, study or stage that does not exist | a file was deleted or an actor removed by hand; restore it from git |
| `E_ALIAS_CYCLE` | duplicate merges refer back to each other | `strata dedup --undo CANONICAL ABSORBED` reverses one merge |
| `E_CRITERION_REUSE` | a criterion id was reused after being retired | add the criterion under a new id; retired ids are never reused |
| `E_EXCLUSION_NO_CRITERION` | an exclusion cites no criterion while `screening.require_exclusion_reason` is on | record the decision again, citing a criterion |
| `E_CRITERION_STAGE` | a decision cites a criterion that does not apply at that stage | record it again with a criterion that does, or change where the criterion applies (`strata criteria edit`, with its direction) |
| `E_ORPHAN_EXTRACTION` | extraction data exists for a study that is not included | the study was excluded after extraction; the data is kept, not deleted. Re-include the study, or leave the warning |
| `E_MISSING_EXTRACTION` | an included study has no consensus extraction | a warning until you analyse: `strata extract --missing` |
| `E_COUNT_RECONCILE` | the PRISMA counts do not add up | records that no import manifest accounts for (hand-written records) or a hand-edited `derived/counts.json`; the message names the identity that fails. Every `strata` command that changes a count regenerates the file, so `strata prisma` rewrites it |
| `E_DERIVED_DRIFT` | a file under `derived/` is not what regenerating it from the records and events would write | a hand edit, a merge done with plain `git`, or a `strata` older than the version that regenerates every derived file after each command (its `pool.tsv` could lag behind an import, a duplicate merge or a correction). `strata verify --fix` regenerates the files that drifted and leaves them uncommitted; `git diff derived/` shows what changed, and committing it keeps it. A file that is not there at all is not drift |
| `E_UNIT`, `E_EFFECT_INPUTS` | an extracted value has a unit the schema does not accept, or an effect lacks the fields its design needs | `strata extract` the study again |

## "I made a wrong decision"

The log is append-only, so a wrong decision is corrected by a new one, and both stay in the history:
screen the record again (`strata screen`), settle a disagreement with `strata adjudicate`, correct a record's
metadata with `strata fix`, reverse a duplicate merge with `strata dedup --undo CANONICAL ABSORBED`, change a
criterion with its direction so `strata rescreen` shows what is now stale. Reverting a commit with `git
revert` is available, but it removes the events without a record of why; use it for a change that never
should have been made, not to correct a judgement.

## Sharing went wrong (`strata sync`)

| What you see | What it means |
|---|---|
| "there are uncommitted changes" | something is half-done in the working tree. `git status` shows it; every `strata` command commits its own work, so this usually means a hand edit or an interrupted session (finish it, as above) |
| "the merged repository does not verify, so nothing was pushed" | your repository was restored exactly as it was and the problems the merge would have caused are listed; nothing reached the remote. Send the list to whoever pushed last |
| a conflict shown as `mine` and `theirs` | two people edited the same criterion or settings file. Choose with the prompt, or `strata sync --resolve mine` / `--resolve theirs` |
| "failed after 5 attempts (network)" | the remote could not be reached (it retries after 2, 4, 8 and 16 seconds). Nothing was lost; run `strata sync` again when you are online |
| "the remote kept changing while syncing" | others pushed three times during one sync; run it again |

## The tooling around git

`strata doctor` checks the git version, `core.hooksPath`, the versioned hooks and the two merge drivers; `strata
doctor --fix` installs what is missing. A clone made with plain `git clone` has no merge drivers until you run
it (`strata clone` does it for you, and `strata sync` still works without them, settling the files the drivers
would have).

## Starting again from the remote

If a working copy is beyond repair and the remote is good: clone it afresh with `strata clone <url>` (it
installs the drivers and hooks and runs `strata verify`), and bring across anything you had not pushed from the
old copy by `git diff`/`git format-patch` of its unpushed commits.

## Problems that are not about the data

| What you see | What it means and what to do |
|---|---|
| `strata: command not found` | The program is installed but your shell cannot find it. `uv tool update-shell`, then open a new terminal ([Installation](Installation)) |
| a commit fails with `.strata/hooks/pre-commit: ... strata: not found` | Git ran a hook that calls `strata`, and `strata` was not on the PATH of whatever ran git (an editor, a script, an absolute-path invocation). Run the command from a normal terminal where `strata --version` works |
| `error: a rationale is required; pass --why or --why-file in a non-interactive context` | You ran a command that records a reason without a terminal to ask in. Add `--why "..."`. If the command had already changed files before it complained (some do), discard them with `git checkout . && git clean -fd` and run it again with `--why` |
| `error: repository is locked (held by process 1234); timed out after 30s` | Another `strata` command, or `strata serve`, is writing to this review right now (the message names it). Wait for it to finish, or stop it, and run your command again. You never need to delete `.strata/lock` by hand: the lock belongs to the running program and is released the moment that program ends, however it ends |
| `warning: the repository lock was left by process 1234, which is no longer running` | An earlier `strata` was killed, or the computer lost power, part-way through a write. Your command took over the lock and carried on. Run `strata verify`; if it reports nothing, nothing was left half-done (`strata status` shows a commit that never happened) |
| `strata sync` says there are uncommitted changes | Something was changed but not committed: a hand edit, an interrupted screening session, or a `strata config` change (which does not commit yet). `git status` shows it; commit it (`git commit -am "..."`) or discard it |
| `strata verify` prints a list of single letters and digits as unknown records, exits 4 | You are on a version before the fix for merged duplicates. Update `strata` ([Installation](Installation)); nothing is wrong with your data |
| `strata analyze` exits with code 8 | A blocking guardrail fired. Read the message; either change the analysis or pass `--force` knowing the result will be labelled ([Analysis](Analysis)) |
| `strata prisma` exits with code 8 | Decisions are stale. Run `strata rescreen`, or `--allow-stale` for a DRAFT |
| `E_COUNT_RECONCILE` from `strata prisma` | The PRISMA counts do not add up; the message names the identity that fails ([above](#strata-verify-says)) |

## Exit codes

Every command exits with one of these, so scripts can tell what happened:

| Code | Meaning |
|---|---|
| 0 | success |
| 1 | an error (the message says which) |
| 2 | wrong usage (a missing or invalid option) |
| 3 | not inside a review (no `strata.toml` found; use `-C PATH`) |
| 4 | the repository does not validate (`strata verify`, `E_COUNT_RECONCILE`, ...) |
| 5 | a conflict that needs a decision (`strata sync`) |
| 6 | the review was made by a newer `strata` than this one |
| 7 | a rationale was required and not given (or was rejected as too short or meaningless). Run without a terminal, the command stops before it writes anything, so there is nothing to clean up; run with a terminal, it asks after doing the work |
| 8 | a guardrail refused: stale decisions, or a blocking analysis warning (`--force` / `--allow-stale` override, recorded) |
