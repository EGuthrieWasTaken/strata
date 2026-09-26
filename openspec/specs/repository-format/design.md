# Design: repository-format

*Informative.* The requirements are in [spec.md](spec.md).

The repository format is the contract. The CLI, the web UI, the MCP server, and
any future reimplementation are interchangeable as long as they honour it.

## The five principles

- **P1 — Plain text, always.** A researcher with `cat` and twenty years must be
  able to read the review.
- **P2 — The event log is the truth.** Anything that can change is an
  append-only event; only human-authored prose and declarative configuration
  are edited in place.
- **P3 — Derived files are committed anyway.** A `git diff` that shows "these
  four papers left the pool and the pooled effect moved from 0.42 to 0.38" is
  the entire point of the product. Derived files are never read back as input,
  so committing them costs nothing in correctness.
- **P4 — Merges must be boring.** Layout and merge drivers are chosen so two
  people screening the same records produce zero git conflicts.
- **P5 — Canonical serialisation.** Same logical content, same bytes, on any
  platform (`openspec:canonical-serialisation`).

## Annotated layout

```
my-review/
├── strata.toml
├── protocol/
│   ├── question.md
│   ├── criteria.yaml
│   ├── moderators.yaml
│   ├── outcomes.yaml
│   ├── searches/S-01-medline.yaml
│   └── amendments.md                    # GENERATED: protocol change log
├── imports/imp_01j9x.../
│   ├── manifest.yaml
│   └── raw/medline-2026-03-04.nbib      # untouched export, source of truth
├── records/{records,aliases}.ndjson
├── events/
│   ├── screen/title-abstract.ethan.ndjson
│   ├── screen/title-abstract.sam.ndjson
│   ├── screen/full-text.ethan.ndjson
│   ├── dedup/ethan.ndjson
│   ├── retrieval/ethan.ndjson
│   └── adjudication/ethan.ndjson
├── extraction/{schema.yaml,by-reviewer/<handle>/,consensus/}
├── rob/{instrument.yaml,by-reviewer/<handle>/}
├── analysis/{primary.yaml,results/primary/{estimates.json,studies.tsv,forest.svg,funnel.svg,summary.md,run.json}}
├── derived/{pool.tsv,counts.json,conflicts.tsv,stale.tsv,irr.json}
├── reports/{prisma-flow.svg,prisma-flow.json,prisma-checklist.md,manuscript/}
├── fulltext/manifest.ndjson             # the directory is gitignored except this
└── .strata/{hooks/,schema-version,cache/}
```

## Why migrations never happen implicitly

A reader who opens an old repository with a new tool must not find it silently
rewritten. `strata migrate` is an ordinary commit with a generated message, so
the upgrade is itself part of the auditable history, and it is forward-only and
idempotent so running it twice, or on a collaborator's clone, is harmless.
