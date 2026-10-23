# M5.1 ("Collaboration") — implementation notes: `strata sync`

A working note modelled on [`m5-plan.md`](m5-plan.md). The normative text is the capability
[`collaboration-sync`](../openspec/specs/collaboration-sync/spec.md) and the merge-driver requirement of
[`git-integration`](../openspec/specs/git-integration/spec.md). M5.1 also plans a container image
(`add-container-image`) and a hosted instance (`add-hosted-team-deployment`); only the first of the three
pieces the [roadmap](roadmap.md) lists, `strata sync`, is built here.

## Status

| Piece | What | Status |
|---|---|---|
| `strata sync` | refuse a dirty tree; fetch with the 2/4/8/16 s retry; fast-forward or merge; normalise and re-link merged event files; regenerate; verify (restore and push nothing on failure); commit as `Strata-Op: sync`; push with the same retry; report in domain terms | done |
| Merge drivers | `strata merge-regenerate` (derived, reports, analysis results) and `strata merge-records` (three-way, field-wise, with notes that become `record-amend` events); installed by `init` and `doctor --fix` | done |
| Conflict presentation | human-authored files shown as `mine` / `theirs` (criteria summarised by id and field); `--resolve mine\|theirs`, an interactive prompt, or an editor | done, editor path untested |
| Event normalisation | after a divergent merge, changed event files are put in `(ts, id)` order, duplicate ids dropped, `seq` renumbered, `prev`/digest chain re-linked, and a `relink` event written under `events/relink/<actor>.ndjson` | done |
| E2E-02 | two clones screen concurrently through the CLI and `strata sync` repeatedly, with no manual conflict step, ending at one head with identical events and derived views | done |
| Container image | `add-container-image`: `Dockerfile`, entrypoint, `compose.yaml`, `serve --public-url` / `STRATA_TOKEN` / `GET /healthz`, `strata --version`, CI/release/nightly jobs | written and tested without a container runtime; **never built or run**, base image not pinned by digest, no cosign signing; see [`container.md`](container.md) and the notes in the change's `tasks.md` |
| Hosted instance | `add-hosted-team-deployment` | not started |

## Conventions that emerged

- **A dirty tree is refused.** Every `strata` command commits its own work, so uncommitted changes mean
  hand-editing; the message says so in strata terms and names no git concept.
- **Only network-looking failures are retried.** The retry looks at git's stderr; an authentication or
  "not a repository" failure is reported straight away. After four retries the error says it was a
  network failure.
- **A merge is `--no-commit --no-ff`.** That keeps the state between merge and commit available, so a
  failed verification can restore the repository (`git merge --abort`, a hard reset to the commit from
  before the sync, and removal of untracked files under `events/` and `derived/`) and nothing is pushed.
- **Conflicts only in human-authored files.** Event files merge with git's `union` strategy and the
  normaliser; derived files are regenerated; `records/records.ndjson` goes through the records driver.
  What remains (`protocol/criteria.yaml`, `strata.toml`, `analysis/*.yaml`, notes) is a person's.
- **`mine` and `theirs`.** The conflicting file is summarised (criteria by id, field, both values; other
  files by the first dozen differing lines). `--resolve` settles every file the same way.
- **Records driver rules.** Sources are a set union; `canonical: false` is sticky (a merge that one side
  had folded in stays folded); when both sides changed the same field the value from the source with the
  higher `dedup.source_trust` rank wins, a longer abstract beats a shorter one, and the lexicographically
  smaller value breaks the remaining tie. Each such decision is a note, and `sync` records the notes as
  `record-amend` events with `source: "merge"` and reports them as "decided automatically".
- **A clone without the drivers still syncs.** Git falls back to a text merge when a configured driver is
  missing, which would leave conflict markers in `records.ndjson` and `derived/`. `sync` settles those
  files itself (derived: take ours and regenerate; records: the same function the driver calls;
  `records/aliases.ndjson`, `fulltext/manifest.ndjson` and event files: line union).
- **Up to three rounds.** If the push is rejected because someone pushed meanwhile, `sync` integrates the
  new commits and pushes again, three times at most, then says the remote kept changing.
- **Exit codes.** Dirty tree, missing remote, network failure: 1; failed verification: 4 (`EXIT_VALIDATION`);
  unresolved conflict: 5 (`EXIT_CONFLICT`).

## Partial or deliberately left for later

- **Rebase strategy.** `git.sync_strategy = "rebase"` replays local commits on the remote ones and then
  normalises, regenerates and verifies like a merge. A rebase that stops on a conflict is aborted and
  reported as a conflict (the `mine`/`theirs` choices are not offered mid-rebase). It is covered by one
  clean-divergence test, not by conflicting histories.
- **Editor choice.** `click.edit` on the conflicted file with the merge markers; not covered by a test
  (it needs a person at an editor).
- **Remote protocol coverage.** Tests use a local bare repository over the file transport. Authentication
  failures, hooks that reject a push for another reason and very large histories have not been exercised.
- **`strata merge-records` on files that are not valid records.** A `records.ndjson` with a line that is not
  JSON, or a record without an `id`, makes the driver fail with a Python error rather than a message.
  Git then reports the file as conflicted and `sync` (which settles the file itself) fails the same way.
  Neither path is handled or tested.
- **The hosted instance** (`add-hosted-team-deployment`) will drive the same `sync` function from a loop;
  its conflicts-in-app screen is not built.
