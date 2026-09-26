# Design: collaboration-sync

*Informative.* The requirements are in [spec.md](spec.md).

## The only sharing verb

`strata sync` is fetch, merge, resolve, verify, push — reported in domain terms:

```
$ strata sync

  Fetching origin ....................... done
  Incoming: 3 commits from sam
  Merging ............................... clean (union-merged 2 event files)
  Regenerating derived views ............ done
  Verifying ............................. ok

  What changed:
    Sam screened 412 records at title-abstract (387 exclude, 25 include)
    Pool: 1,204 -> 1,229 records at full-text
    New screening conflicts: 14   (run `strata adjudicate`)

  Pushing ............................... done
```

It is the foundation of every collaboration topology the project supports
(see [docs/roadmap.md](../../../docs/roadmap.md), M5.1): collaborators each
running `strata` locally against a shared remote, a hosted instance syncing
with that remote on their behalf, or any mix of the two.

## Why dual screening never conflicts

Each reviewer writes only to `events/screen/<stage>.<their-handle>.ndjson`, so
two reviewers screening the same 2,000 records touch disjoint files. The union
driver handles one reviewer syncing from two machines. Disagreement between
reviewers is therefore never a git-level event: it appears in
`derived/conflicts.tsv` and the adjudication queue, which is where a
methodologist expects to find it. This is the single most important structural
decision in the format.

## Why sync never pushes an unverifiable repository

A broken merge that reaches the shared remote breaks every collaborator at
once. Verifying before pushing, and restoring the pre-sync state on failure,
keeps a bad merge local to the person who can fix it.

## Why human-authored conflicts are shown in domain terms

When two people edit the same criterion definition, the question is "which
definition do we mean?", not "what does `<<<<<<<` mean?". Raw conflict markers
appear only if the user asks for an editor.
