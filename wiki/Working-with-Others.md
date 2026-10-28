# Working with others

A review shared between people is a git repository on a shared server (a *remote*), and `strata sync` is the
one command for sharing it. If git is new to you, read [Git for reviewers](Git-for-Reviewers) first for the
one-time setup (creating the remote, cloning, credentials); this page is about the day-to-day.

## The daily rhythm

```
strata sync        # first thing: bring in what others did, check it, send yours
...                # screen, extract, adjudicate ...
strata sync        # last thing: send what you did
```

`strata sync` is deliberately one verb for fetch, merge, check and push:

1. **Refuses if you have uncommitted changes** (every `strata` command commits its own work, so this means a
   half-finished session or a hand edit).
2. **Fetches** the remote, retrying if the network drops (after 2, 4, 8 and 16 seconds).
3. **Merges** what others did. Fast-forwards if you had done nothing; otherwise merges.
4. **Puts merged event files back in order and re-links them** (each collaborator's screening decisions are in
   their own file, so the common case never conflicts; where two clones both appended to the same file, the
   merge is put in order and the repair is recorded as a `relink` event).
5. **Regenerates the derived views** (`derived/`) from the merged log.
6. **Verifies the whole repository.** If anything is wrong, your repository is restored *exactly* as it was and
   nothing is pushed.
7. **Pushes**. If the remote moved while you were syncing, it integrates and tries again (up to three rounds).

and then reports in plain terms what others did:

```
  Fetching origin ...
  Fast-forwarding ...
  Regenerating derived views ...
  Verifying ...
  Pushing ...

  Incoming: 2 change(s) (2 from sam)
  What changed:
    sam screened 3 record(s) at title-abstract (3 include)
    title-abstract included: 0 -> 2
    1 new screening conflict(s)   run `strata adjudicate`
  Pushed
```

Options: `--no-push` (fetch, merge and verify, but do not push), `--resolve mine|theirs` (below), `--by` (which
actor you are syncing as; defaults to the first active actor). The merge strategy is `git.sync_strategy` in
`strata.toml`: `merge` (default) or `rebase`.

## Example: two people screening at the same time

Ada and Sam each have a clone of the same review (Sam made his with `strata clone`):

```
$ strata clone remote.git sam-copy
fixed set core.hooksPath = .strata/hooks
fixed installed merge driver strata-regenerate
fixed installed merge driver strata-records
ok — cloned and verified
```

Both screen three records, without syncing in between. Ada syncs first, which simply pushes. Then Sam syncs.
His copy has things Ada's does not, and the reverse, so `strata sync` **merges**:

```
  Fetching origin ...
  Merging ...
  Normalising merged event files ...
  Regenerating derived views ...
  Verifying ...
  Pushing ...

  Incoming: 1 change(s) (1 from ada)
  What changed:
    ada screened 3 record(s) at title-abstract (1 exclude, 2 include)
    title-abstract included: 0 -> 2
    1 new screening conflict(s)   run `strata adjudicate`
  Pushed
```

There was no conflict to resolve: each of them wrote to their own file. The one disagreement it found
(the same record included by one and excluded by the other) is a *screening conflict*, which is a normal
part of dual screening and is settled by [adjudication](Adjudication-and-Agreement), not by sync. When Ada
syncs again she fast-forwards to the merged state, with Sam's decisions in it.

## When two people changed the same file

Screening and extraction by different people never conflict. What *can* conflict is a file two people both
edited: a criterion, `strata.toml`, a protocol file. `strata sync` stops, **shows both versions as "mine" and
"theirs"**, and asks:

```
conflict: a human-authored file was edited differently by two people
  protocol/criteria.yaml
    ...
Nothing changed. Run `strata sync --resolve mine` or `--resolve theirs`.
```

Choose: `strata sync --resolve mine` keeps your version of every conflicting file, `--resolve theirs` keeps
theirs, or answer the prompts file by file. You will never be shown git's `<<<<<<<` markers. After resolving, it
carries on (regenerate, verify, push).

For criteria in particular, agree with your colleague which edit should stand and apply the other as a new,
deliberate criteria change (with its direction), so staleness is computed for it ([Changing criteria
mid-review](Changing-Criteria-Mid-Review)).

## Who does what

- **Everyone** screens, extracts and assesses risk of bias under their own handle. Nobody should use another
  person's handle: their file, their blinding and the agreement statistics depend on it.
- **The lead** (or anyone with the right) adds actors, edits criteria and settings, and adjudicates (as
  listed in `screening.adjudicators`).
- **Extraction and RoB** can be done by one person or two (`extraction.mode = "dual"`), then reconciled.
- Agree who runs `strata analyze` and `strata report`: generated files merge by being *regenerated*, so the
  last person to sync after a change should regenerate before anything is published.

## Checks on a shared repository (optional, GitHub)

Create the review repository with `strata init --ci` (or add the workflow later) and every pull request is
checked:

```
strata init my-review --title "..." --actor lead --actor-name "..." --ci --methodologist your-github-login
```

This installs `.github/workflows/strata.yml`, a thin file that calls a reusable workflow published with
`strata`. On each pull request it:

- runs **`strata verify`** on the proposed state, so a damaged event file or a broken reference blocks the merge;
- posts a **comment** saying what the pull request does to the review: how many records, decisions and
  studies change, stage by stage;
- **labels** a change to the eligibility criteria `protocol-amendment` (comparing the criteria *as data*, so
  reformatting does not count) and asks the `--methodologist` to review it.

It runs on the `pull_request` event, never `pull_request_target`. Only the job that comments has permission to
write to pull requests (`pull-requests: write`); for a pull request from a fork the token is read-only and
there are no secrets, so the checks still run but the comment, label and review request are skipped. The same pieces are available directly as
`strata ci amendment` and `strata ci comment`. In a repository you use only by pushing to `main`, none of this
applies; it is for teams that want changes to a review looked at before they merge.

## If something goes wrong

The common cases (an uncommitted change, a failed verify, a conflict, a network error) are in
[Recovery and troubleshooting](Recovery-and-Troubleshooting#sharing-went-wrong-strata-sync). The short
version: `strata verify` says what is wrong, nothing you have recorded is lost while it is in git, and
`strata sync` never pushes a repository that does not verify.
