# Design: domain-model

*Informative.* The requirements are in [spec.md](spec.md).

## Why the distinctions matter

PRISMA counts three different things and calls them by three different names.
Conflating them is the single most common source of a flow diagram that does not
reconcile, so `strata` models them separately and derives every count from the
model.

```
   Search hit          Deduplicated       Document             Research
   from one DB         bibliographic      obtained and         study reported
                       entity             assessed             by >=1 document
  +-----------+       +-----------+      +-----------+        +-----------+
  |  Record   |--n:1->|  Record   |-1:1->|  Report   |--n:1-->|   Study   |
  | (raw row) |       |(canonical)|      |(full text)|        |           |
  +-----------+       +-----------+      +-----------+        +-----------+
                                                                    | 1:n
                                                                    v
                                                              +-----------+
                                                              |  Effect   |
                                                              +-----------+
```

- **Records identified** = raw records across all imports.
- **Duplicates removed** = raw records absorbed into a canonical record.
- **Records screened** = canonical records entering title/abstract screening.
- **Reports sought for retrieval** = canonical records promoted to a report.
- **Reports assessed for eligibility** = reports whose full text was obtained.
- **Studies included** and **reports of included studies** differ whenever one
  study is reported in more than one paper.

A study with a protocol paper, a primary-outcomes paper, and a long-term
follow-up has three reports; a single report describing three independent
experiments yields three studies. Studies are the unit of extraction and the
unit of clustering in analysis, which is why multiple effects from one study are
statistically dependent (see the `pooling-models` capability once analysis
ships).

## Why actors are handles, not git authors

A reviewer who changes institution or email would otherwise fragment their
history across several git identities. Events record the handle from
`strata.toml`; git authorship is incidental.

## Why staleness is an overlay

If `stale` were a seventh state, a record would drop out of the `include` or
`exclude` counts the moment a criterion changed, and the flow diagram would stop
being well defined mid-re-screening. As an overlay, the prior decision still
counts, the stale count is reported alongside, and `strata prisma` refuses to
call the diagram final until the overlay is cleared.

## Why the stage list is configuration

Two screening stages is what PRISMA describes and what most reviews do, but a
calibration round (`tiab-pilot`) or an extra gate (`data-availability`) is a
real need. Reading stages from configuration makes that a config change rather
than a schema migration.

## Glossary

| Term | Definition |
|---|---|
| **Adjudication** | Resolving a screening `conflict`, by a third reviewer or by consensus |
| **Blocking** | Partitioning records into candidate groups so deduplication avoids O(n^2) comparison |
| **Canonical record** | The surviving record after duplicates are merged into it |
| **CHE** | Correlated-hierarchical-effects model for dependent effect sizes |
| **Dual screening** | Two reviewers independently screening the same records — the methodological default |
| **Fold** | Deterministic reduction of the event log to current state |
| **IRR** | Inter-rater reliability (Cohen's kappa, PABAK, percent agreement) |
| **Moderator** | A study-level variable hypothesised to explain heterogeneity |
| **PRISMA** | Preferred Reporting Items for Systematic Reviews and Meta-Analyses (2020 statement) |
| **RoB** | Risk of bias |
| **Staleness** | The property of a decision made under a version of the protocol that has since changed in a way that could alter it |
| **tau^2** | Between-study variance in a random-effects model |
