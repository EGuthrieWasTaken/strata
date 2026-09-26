# Design: event-log

*Informative.* The requirements are in [spec.md](spec.md).

## Why an event log at all

Three requirements force it:

1. **Provenance.** "Sam changed this from include to exclude on 4 March citing
   EXC-07" is a fact the review must retain even though only the final state
   matters to the analysis.
2. **Conflict-free merging.** Append-only files sharded by actor merge with
   git's built-in `union` driver without human intervention.
3. **Recomputable staleness.** Deciding whether a past decision survives a
   criteria change requires knowing what it was made *against*, which a
   current-state table does not record.

## An example event

```json
{"ev":"screen","id":"ev_01j9x7m2q4h8s0v3n5k1t6w2yb","ts":"2026-03-04T14:02:11Z","actor":"ethan","seq":1183,"body":{"confidence":"high","criteria":["EXC-02"],"criteria_digest":"sha256:9f1c...","criteria_version":3,"decision":"exclude","note":"rodent model","record":"rec_3kq8v1r0zx2m4a7b","stage":"title-abstract"},"tool":"strata/0.4.1","prev":"sha256:1a2b...","digest":"sha256:3c4d..."}
```

## What the hash chain is (and is not) for

`prev` + `digest` form a per-file chain. It does **not** defend against a
determined adversary, who could simply rewrite the chain, and must never be
described as doing so. It defends against the realistic failures: a
well-meaning collaborator opening an event file in Excel and saving it, or a
partial write from a crashed process.

## The union-merge caveat

Git's `union` driver concatenates both sides of a divergent append, which breaks
a single linear chain whenever one actor appended on two machines. Rather than
fight git, the chain is validated per contiguous run, a restart is accepted if
it links to an earlier line, and `strata sync` later rewrites the file into
canonical order and records a `relink` event so the rewrite is itself auditable.

## Why `maybe` never resolves

`maybe` means "discuss it". Letting two `maybe`s resolve to anything would skip
the discussion, so any `maybe` among the opinions yields `conflict`, and the
discussion happens in the adjudication queue.

## Why one writer per file

Two actors never append to the same file, so the only way to get interleaved
lines is a genuine merge of two branches by the same actor — the case `strata
sync` normalises. This single decision is what makes dual screening conflict-free
(`openspec:collaboration-sync#dual-screening-never-conflicts`).
