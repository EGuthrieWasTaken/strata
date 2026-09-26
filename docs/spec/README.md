# strata — Software Specification

Version 0.1 (draft) · Target implementation: `strata` 0.1.0 → 1.0.0

## Normative requirements now live in OpenSpec

The normative requirements from this document set have been converted into
[OpenSpec](../../openspec/README.md) capability specs under
[`openspec/specs/`](../../openspec/specs/), and the roadmap milestones not yet
built are tracked as change proposals under
[`openspec/changes/`](../../openspec/changes/). **OpenSpec is the source of
truth for what `strata` must do; where a document here and an OpenSpec spec
disagree, the OpenSpec spec wins.** Behaviour changes are proposed as OpenSpec
changes, not by editing these documents.

The documents here remain the long-form design rationale — the *why* behind
each requirement, worked examples, formula derivations, and rejected
alternatives — and keep their section numbers, because code comments and every
OpenSpec requirement's `_Source:_` line cite them. The roadmap
([15](15-roadmap.md)) and open questions ([16](16-open-questions.md)) remain
living planning documents.

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

Sections marked *(normative)* define observable behaviour or on-disk format;
their requirements are carried, with scenarios, by the OpenSpec specs listed in
the map below, and a conforming implementation is judged against those.
Sections marked *(informative)* explain intent and MAY be deviated from where
the implementer has a better idea, provided normative behaviour is preserved.

### Document map

| # | Document | Status | What it covers | OpenSpec |
|---|---|---|---|---|
| 00 | [Overview](00-overview.md) | informative | Problem, goals, non-goals, personas, prior art | `config.yaml` context |
| 01 | [Domain model](01-domain-model.md) | normative | Entities, identity, lifecycle, glossary | `domain-model`, `record-identity` |
| 02 | [Repository format](02-repository-format.md) | normative | On-disk layout, file formats, canonicalisation | `repository-format`, `canonical-serialisation`, `event-log`, `derived-views` |
| 03 | [Schemas](03-schemas.md) | normative | Every persisted object, field by field | `data-schemas`, `repository-verification`; §6–§8 in change `add-full-text-and-extraction` |
| 04 | [Git integration](04-git-integration.md) | normative | Commits, trailers, merge drivers, sync, provenance | `git-integration`, `collaboration-sync`, `provenance-queries` |
| 05 | [Search, import, deduplication](05-workflow-import.md) | normative | Getting literature in and de-duplicated | `literature-import`, `deduplication` |
| 06 | [Screening & the staleness engine](06-workflow-screening.md) | normative | The flagship feature | `criteria-management`, `staleness`, `screening`, `adjudication` |
| 07 | [Full text & data extraction](07-workflow-extraction.md) | normative | Retrieval, coding forms, risk of bias | change `add-full-text-and-extraction` |
| 08 | [Analysis](08-analysis.md) | normative | Effect sizes, models, diagnostics, reproducibility | change `add-meta-analysis` |
| 09 | [Reporting & PRISMA](09-reporting.md) | normative | Flow diagram, checklist, manuscript, exports | change `add-prisma-reporting` |
| 10 | [Command-line interface](10-cli.md) | normative | Every command, flag, and exit code | `cli`, `filter-language` |
| 11 | [Local web interface](11-web-ui.md) | normative | Screening and extraction UI | `web-ui` |
| 12 | [Architecture](12-architecture.md) | informative | Stack, module boundaries, plugin points | `architecture`; §7 in change `add-distribution-and-adoption` |
| 13 | [Non-functional requirements](13-nonfunctional.md) | normative | Performance, privacy, a11y, i18n, licensing | `performance`, `privacy-and-security`, `copyright-and-licensing`, `portability-and-i18n`, `project-documentation` |
| 14 | [Testing & validation](14-testing.md) | normative | How correctness is proven: the suite, the CI pull-request gate, and the rule that every change carries its tests | `test-suite`, `ci-gate`; §11 in change `add-review-repository-ci` |
| 15 | [Roadmap](15-roadmap.md) | informative | Milestones with acceptance criteria | `mcp-server`, `project-documentation`; milestones M3–M6 as changes |
| 16 | [Open questions](16-open-questions.md) | informative | Decisions still owned by the project lead | — |
| 17 | [Zotero integration](17-zotero-integration.md) | normative (post-1.0) | Delegating document storage and citation to Zotero | change `add-zotero-integration` |

### A note on the name

`strata` is provisional. Before any public release, see the trademark and
namespace concerns raised in [16-open-questions.md](16-open-questions.md#q1--project-name--decided-strata);
they are non-trivial in exactly the research domain this tool targets.
