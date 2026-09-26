# OpenSpec

`strata`'s specification lives here, managed with
[OpenSpec](https://github.com/Fission-AI/OpenSpec) (`@fission-ai/openspec`,
pinned to 1.13.2 in CI). It is the single source of truth for what `strata`
must do and why. The project's goals are in [docs/overview.md](../docs/overview.md),
the milestone plan in [docs/roadmap.md](../docs/roadmap.md), and decisions still
open in [docs/open-questions.md](../docs/open-questions.md).

## Layout

- [`specs/`](specs/) — one directory per capability that has shipped:
  - `spec.md` — the normative requirements (`### Requirement:` blocks using
    RFC 2119 keywords, each with `#### Scenario:` WHEN/THEN examples).
  - `design.md` — the informative rationale: why the requirements are what they
    are, worked examples, and rejected alternatives.
- [`changes/`](changes/) — proposed changes not yet built, each with a
  proposal, design, tasks, and delta specs. The remaining roadmap milestones are
  here. When one ships, `openspec archive <change>` folds its requirements into
  `specs/` and moves it to `changes/archive/`.
- [`config.yaml`](config.yaml) — project context and per-artifact rules that
  OpenSpec feeds to AI assistants.

## Citing the specification

Code comments, docs, and specs cite requirements as
`openspec:<capability>#<requirement-slug>`, where the slug is the requirement's
name lower-cased with runs of other characters replaced by `-` — for example
`openspec:staleness#the-staleness-rules` for "### Requirement: The staleness
rules" in [specs/staleness/spec.md](specs/staleness/spec.md). A whole capability
is `openspec:staleness`. `scripts/check_docs.py` fails the build if any such
reference does not resolve, so renaming a requirement means updating its
references in the same pull request.

Identified requirements keep their ids — property invariants P1–P13, end-to-end
scenarios E2E-01–E2E-12, and the `E_*` error codes — and tests name them with
`@pytest.mark.req(...)` so `scripts/traceability_report.py` can find them.

## Workflow

```
npm install -g @fission-ai/openspec@1.13.2
export OPENSPEC_TELEMETRY=0          # strata ships no telemetry; neither should its tooling

openspec list                        # changes in flight
openspec list --specs                # capabilities
openspec show staleness              # read one spec
openspec validate --all --strict     # what the `docs` CI job runs
uv run python scripts/check_docs.py  # links, anchors, config blocks, openspec: references
```

In Claude Code, the `/opsx:propose`, `/opsx:apply`, `/opsx:archive`,
`/opsx:explore`, `/opsx:sync`, and `/opsx:update` commands (installed under
`.claude/`) drive the same workflow.

A behaviour change is proposed as a change under `changes/` whose delta specs
use `## ADDED`, `## MODIFIED`, `## REMOVED`, or `## RENAMED Requirements`,
implemented with its tests (`openspec:test-suite#every-change-carries-its-tests`),
and archived when merged. A change to identity, normalisation, canonical
serialisation, the fold, or the staleness rules also needs a schema-version
review (`openspec:repository-format#format-versioning`).

## Capabilities

| Capability | Covers |
|---|---|
| [domain-model](specs/domain-model/spec.md) | Records, reports, studies, effects, criteria, searches, events, actors; screening states; the stage graph |
| [record-identity](specs/record-identity/spec.md) | Deterministic ids, normalisation, aliases |
| [repository-format](specs/repository-format/spec.md) | Principles, directory layout, authoritative vs derived files, format versioning |
| [canonical-serialisation](specs/canonical-serialisation/spec.md) | Byte-exact NDJSON, YAML, TSV, and generated output |
| [event-log](specs/event-log/spec.md) | Event envelope, hash chain, the fold, event types, sharding |
| [derived-views](specs/derived-views/spec.md) | `pool.tsv`, `counts.json`, `conflicts.tsv`, `stale.tsv`, `irr.json` |
| [data-schemas](specs/data-schemas/spec.md) | `strata.toml`, records, criteria, moderators, searches |
| [repository-verification](specs/repository-verification/spec.md) | `strata verify`, error codes, crash safety, recovery |
| [git-integration](specs/git-integration/spec.md) | Commits, trailers, rationales, batching, merge drivers, hooks, hygiene |
| [collaboration-sync](specs/collaboration-sync/spec.md) | `strata sync` and conflict-free dual screening |
| [provenance-queries](specs/provenance-queries/spec.md) | `strata why`, `log`, `diff` |
| [literature-import](specs/literature-import/spec.md) | Search recording, parsers, CSV mapping, idempotent import |
| [deduplication](specs/deduplication/spec.md) | Blocking, scoring, thresholds, merges, review queue, benchmark |
| [criteria-management](specs/criteria-management/spec.md) | Criteria commands, versioning, direction classification |
| [staleness](specs/staleness/spec.md) | The staleness rules, causes, cascade, re-screening, audit |
| [screening](specs/screening/spec.md) | Stages, dual screening and blinding, the screening surface, IRR |
| [adjudication](specs/adjudication/spec.md) | Resolving conflicts |
| [cli](specs/cli/spec.md) | Global options, exit codes, commands, status, errors |
| [filter-language](specs/filter-language/spec.md) | The `--filter` expression language |
| [web-ui](specs/web-ui/spec.md) | `strata serve`: screens, screening surface, criteria editor, accessibility, security |
| [architecture](specs/architecture/spec.md) | Module boundaries and invariants, cache, locking, plugins |
| [performance](specs/performance/spec.md) | Scale targets and benchmarks |
| [privacy-and-security](specs/privacy-and-security/spec.md) | No telemetry, offline by default, enrichment etiquette, threat model |
| [copyright-and-licensing](specs/copyright-and-licensing/spec.md) | Full texts, legitimate sources, attribution, licences |
| [portability-and-i18n](specs/portability-and-i18n/spec.md) | Platforms, Unicode, internationalisation |
| [project-documentation](specs/project-documentation/spec.md) | Documentation set, wiki, docs-with-the-feature |
| [test-suite](specs/test-suite/spec.md) | Test levels, P1–P13, E2E scenarios, statistical validation, traceability |
| [ci-gate](specs/ci-gate/spec.md) | The pull-request gate, branch protection, nightly, integrity checks |
| [mcp-server](specs/mcp-server/spec.md) | `strata mcp`: read-only MCP tools |

## Changes in flight

| Change | Milestone |
|---|---|
| `add-full-text-and-extraction` | M3 |
| `add-meta-analysis` | M4 |
| `add-prisma-reporting` | M5 (`1.0.0`) |
| `add-container-image` | M5.1 (can land any time) |
| `add-hosted-team-deployment` | M5.1 |
| `add-distribution-and-adoption` | M6 |
| `add-zotero-integration` | M6 |
| `add-review-repository-ci` | M6 |

## Known gaps in shipped capabilities

A few requirements in `specs/` are ahead of the code:

- `strata sync`, `strata migrate`, `strata diff`, `strata moderators`,
  `strata note`, and `strata gc --imports` (`collaboration-sync`,
  `repository-format`, `provenance-queries`, `cli`,
  `repository-verification`). `strata sync` is scheduled first in M5.1.
- EndNote XML, Excel, and PRISMA-style citation-list parsers
  (`literature-import`; deferred in M1, tracked in
  `add-distribution-and-adoption`).
- Opt-in enrichment and its `.strata/network.log` (`privacy-and-security`).
- The batched-commit policy's 200-decision and 15-minute triggers
  (`git-integration`; sessions currently commit when they end).
- Crash logs under `.strata/crash-<timestamp>.log` (`cli`).

## History

The specification was first written as a set of long-form documents under a
`docs/spec` directory, converted to OpenSpec, and then retired: its normative
content is in the specs above, its rationale in each capability's `design.md`,
and its planning documents in `docs/`. The historical milestone plans
(`docs/m1-plan.md`, `docs/m2-plan.md`, `docs/m2.1-plan.md`) still cite its
section numbers; the retired text is preserved in git history.
