# collaboration-sync Specification

## Purpose

`strata sync`, the only sharing verb: fetch, merge, resolve, verify, and push
with domain-level reporting, arranged so that dual independent screening never
produces a git-level conflict and disagreement surfaces in the adjudication
queue instead.

Rationale and worked examples: [design.md](design.md).

## Requirements

### Requirement: Sync algorithm

`strata sync` MUST:

1. Refuse to start if the working tree is dirty, telling the user to commit or
   stash via `strata`.
2. `git fetch <remote>`, retrying network failures up to 4 times with
   exponential backoff (2s, 4s, 8s, 16s).
3. If there is no divergence: fast-forward, regenerate, verify, done.
4. Merge (or rebase, per `git.sync_strategy`).
5. Normalise merged event files: sort by `(ts, id)`, drop exact duplicate ids,
   re-link the chain, and append a `relink` event.
6. Regenerate every derived file and stage it.
7. Run `strata verify`; on failure abort the merge, restore the pre-sync state,
   and report precisely what failed. It MUST never push an unverifiable
   repository.
8. Commit the merge with a generated message and `Strata-Op: sync`.
9. Push with `git push -u origin <branch>`, with the same retry policy.
10. Report domain-level consequences (who screened what, pool changes, new
    conflicts and the command that addresses them).

#### Scenario: Dirty working tree

- **WHEN** `strata sync` runs with uncommitted changes
- **THEN** it refuses to start and tells the user how to commit via `strata`

#### Scenario: Verification fails after merge

- **GIVEN** an incoming change that makes `strata verify` fail after merging
- **WHEN** `strata sync` runs
- **THEN** the merge is aborted, the pre-sync state is restored, nothing is pushed, and the failure is reported

#### Scenario: Collaborator screened records

- **GIVEN** `sam` pushed 412 title-abstract decisions
- **WHEN** `ethan` runs `strata sync`
- **THEN** the output summarises `sam`'s decisions, the pool change, and any new conflicts with the `strata adjudicate` hint

### Requirement: Human-authored conflicts are presented in domain terms

If a merge produces a genuine conflict in a human-authored file (two people
edited the same criterion definition or the same `question.md` paragraph),
`strata` MUST present it in domain terms and offer: keep mine, keep theirs, or
open an editor. It MUST NOT show raw conflict markers unless the user chooses
the editor. Such a conflict exits with code 5 when it requires human resolution.

#### Scenario: Two people edited the same criterion

- **WHEN** `strata sync` merges divergent edits to `EXC-03`'s definition
- **THEN** the user is shown both definitions and offered keep mine, keep theirs, or open an editor

### Requirement: Dual screening never conflicts

Each reviewer MUST write only to `events/screen/<stage>.<their-handle>.ndjson`,
so two reviewers screening the same records touch disjoint files, and
disagreement between reviewers is never a git-level event — it appears in
`derived/conflicts.tsv` and the adjudication queue. Any change to file sharding
MUST preserve this property.

#### Scenario: Concurrent screening on separate clones

- **GIVEN** two collaborators screening concurrently on separate clones and syncing repeatedly
- **WHEN** they finish
- **THEN** both repositories are identical and no manual conflict resolution was needed
