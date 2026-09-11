# strata — Software Specification

Version 0.1 (draft) · Target implementation: `strata` 0.1.0 → 1.0.0

## How to read this document set

This specification is written to be handed to an implementer and executed
without further design work. Where a decision was genuinely open, it has been
*made* and the rationale recorded, rather than deferred. Decisions that remain
open are collected in [16-open-questions.md](16-open-questions.md) and are
flagged inline as **OPEN**.

### Conformance language

The key words **MUST**, **MUST NOT**, **REQUIRED**, **SHALL**, **SHOULD**,
**SHOULD NOT**, **MAY**, and **OPTIONAL** are to be interpreted as described in
RFC 2119 / RFC 8174.

Sections marked *(normative)* define observable behaviour or on-disk format and
MUST be implemented as written; a conforming implementation is judged against
them. Sections marked *(informative)* explain intent and MAY be deviated from
where the implementer has a better idea, provided normative behaviour is
preserved.

### Document map

| # | Document | Status | What it covers |
|---|---|---|---|
| 00 | [Overview](00-overview.md) | informative | Problem, goals, non-goals, personas, prior art |
| 01 | [Domain model](01-domain-model.md) | normative | Entities, identity, lifecycle, glossary |
| 02 | [Repository format](02-repository-format.md) | normative | On-disk layout, file formats, canonicalisation |
| 03 | [Schemas](03-schemas.md) | normative | Every persisted object, field by field |
| 04 | [Git integration](04-git-integration.md) | normative | Commits, trailers, merge drivers, sync, provenance |
| 05 | [Search, import, deduplication](05-workflow-import.md) | normative | Getting literature in and de-duplicated |
| 06 | [Screening & the staleness engine](06-workflow-screening.md) | normative | The flagship feature |
| 07 | [Full text & data extraction](07-workflow-extraction.md) | normative | Retrieval, coding forms, risk of bias |
| 08 | [Analysis](08-analysis.md) | normative | Effect sizes, models, diagnostics, reproducibility |
| 09 | [Reporting & PRISMA](09-reporting.md) | normative | Flow diagram, checklist, manuscript, exports |
| 10 | [Command-line interface](10-cli.md) | normative | Every command, flag, and exit code |
| 11 | [Local web interface](11-web-ui.md) | normative | Screening and extraction UI |
| 12 | [Architecture](12-architecture.md) | informative | Stack, module boundaries, plugin points |
| 13 | [Non-functional requirements](13-nonfunctional.md) | normative | Performance, privacy, a11y, i18n, licensing |
| 14 | [Testing & validation](14-testing.md) | normative | How correctness is proven: the suite, the CI pull-request gate, and the rule that every change carries its tests |
| 15 | [Roadmap](15-roadmap.md) | informative | Milestones with acceptance criteria |
| 16 | [Open questions](16-open-questions.md) | informative | Decisions still owned by the project lead |
| 17 | [Zotero integration](17-zotero-integration.md) | normative (post-1.0) | Delegating document storage and citation to Zotero |

### A note on the name

`strata` is provisional. Before any public release, see the trademark and
namespace concerns raised in [16-open-questions.md](16-open-questions.md#q1--project-name--decided-strata);
they are non-trivial in exactly the research domain this tool targets.
