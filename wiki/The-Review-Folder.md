# What is in a review folder

A review is a folder of plain text files (and a hidden `.git` folder holding its history). You rarely need to
open any of it, but knowing what is *yours to edit* and what is *record* or *computed* makes everything else
easier to trust.

```
my-review/
├── strata.toml                  settings: project, team, screening, dedup, git      (edit with strata config)
├── protocol/
│   ├── question.md              the review question and rationale                   (edit by hand)
│   ├── criteria.yaml            eligibility criteria, versioned                      (edit with strata criteria)
│   ├── moderators.yaml          planned moderators                                   (edit by hand)
│   ├── outcomes.yaml            outcomes                                             (edit by hand)
│   ├── searches/<id>.yaml       one file per executed search                         (strata search add)
│   └── amendments.md            generated change log of the protocol
├── imports/<import-id>/
│   ├── manifest.yaml            what was imported, from where, how many
│   └── raw/<export-file>        the untouched export you imported
├── records/
│   ├── records.ndjson           the bibliographic records
│   └── aliases.ndjson           which records were merged into which
├── events/<kind>/...ndjson      the append-only log of everything that happened     (never edit)
├── extraction/                  the coding form, each extractor's data, the consensus
├── rob/                         the risk-of-bias instrument and assessments
├── analysis/<id>.yaml           analysis specifications                              (edit by hand)
├── analysis/results/<id>/       generated: estimates, tables, plots, run record
├── derived/                     generated views: the pool, stale decisions, counts, conflicts
├── reports/                     generated: PRISMA diagram, Methods, Results, checklist
├── fulltext/manifest.ndjson     identifiers and versions of retrieved full texts (the PDFs are not kept here)
├── integrations/zotero.ndjson   which Zotero item each record is (only if you link a Zotero library)
└── .strata/                     git hooks, format version, caches
```

## Three kinds of file

| Kind | Examples | You may |
|---|---|---|
| **Settings and protocol**: written by you | `strata.toml`, `protocol/*`, `extraction/schema.yaml`, `analysis/<id>.yaml` | Edit by hand or with `strata` commands. Changes are recorded in git history |
| **The record**: written by `strata`, never rewritten | `events/**`, `records/**`, `imports/*/raw/**`, `extraction/consensus/**` | Never edit. `events/` is a *hash chain*: each entry carries a digest of the previous one, so a hand edit is detected (`E_CHAIN`) |
| **Generated**: computed from the record | `derived/**`, `reports/**`, `analysis/results/**`, `protocol/amendments.md` | Never edit; regenerate with the command that produced them (`strata analyze`, `strata prisma`, `strata report`). `strata verify` regenerates them and complains if a committed copy differs |

## The event log in one paragraph

Every change to the review is first a line appended to a file under `events/`: an import, a screening
decision, a criteria change, a retrieval outcome, an extraction. Each line records who, when (to the second),
what, and a digest. Everything else (the pool of records, who is in conflict, what is stale, the PRISMA
counts) is a **pure function of those lines**, recomputed on demand. That is why a past state of the review can
be reconstructed exactly, why two people's work merges without conflict (each appends to their own files), and
why `strata` can tell you *why* the review looks the way it does. Screening decisions are in
`events/screen/<stage>.<handle>.ndjson`, one file per reviewer per stage.

## Which files do people share?

Everything except the things named in `.gitignore`: the full-text PDFs under `fulltext/` (only their manifest
is shared), `.strata/cache/` and the network log. The raw exports in `imports/*/raw/` are committed, so the
review's inputs are preserved.

See [Configuration](Configuration) for `strata.toml`, [Filter language](Filter-Language) for `--filter`, and
the [Glossary](Glossary).
