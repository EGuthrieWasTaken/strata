# OpenSpec

`strata`'s normative requirements live here, managed with
[OpenSpec](https://github.com/Fission-AI/OpenSpec) (`@fission-ai/openspec`,
pinned to 1.13.2 in CI). The long-form design rationale — worked examples,
formula derivations, the soundness argument for the staleness rules, rejected
alternatives — stays in [`docs/spec/`](../docs/spec/README.md), whose section
numbers the code cites. **Where the two disagree, the OpenSpec spec wins.**

## Layout

- [`specs/`](specs/) — one directory per capability, describing behaviour as
  `### Requirement:` blocks (RFC 2119 keywords) with `#### Scenario:`
  WHEN/THEN examples. These cover everything in roadmap milestones M0, M1, M2,
  and M2.1, which have shipped. Each requirement ends with a `_Source:_` line
  citing the `docs/spec/` section it was converted from.
- [`changes/`](changes/) — proposed changes not yet built. The remaining
  roadmap milestones are pre-loaded as changes, each with a proposal, tasks, a
  design where the rationale warrants one, and delta specs:

  | Change | Milestone |
  |---|---|
  | `add-full-text-and-extraction` | M3 |
  | `add-meta-analysis` | M4 |
  | `add-prisma-reporting` | M5 (`1.0.0`) |
  | `add-hosted-team-deployment` | M5.1 |
  | `add-zotero-integration` | M6 |
  | `add-review-repository-ci` | M6 |
  | `add-distribution-and-adoption` | M6 |

  When a milestone ships, `openspec archive <change>` folds its requirements
  into `specs/` and moves the change to `changes/archive/`.
- [`config.yaml`](config.yaml) — project context and per-artifact rules that
  OpenSpec feeds to AI assistants.

## Workflow

```
npm install -g @fission-ai/openspec@1.13.2
export OPENSPEC_TELEMETRY=0          # strata ships no telemetry; neither should its tooling

openspec list                        # changes in flight
openspec list --specs                # capabilities
openspec show staleness              # read one spec
openspec validate --all --strict     # what the `docs` CI job runs
```

In Claude Code, the `/opsx:propose`, `/opsx:apply`, `/opsx:archive`,
`/opsx:explore`, `/opsx:sync`, and `/opsx:update` commands (installed under
`.claude/`) drive the same workflow.

A behaviour change is proposed as a change under `changes/` whose delta specs
use `## ADDED`, `## MODIFIED`, `## REMOVED`, or `## RENAMED Requirements`,
implemented with its tests (`docs/spec/14-testing.md` §10), and archived when
merged. The standing rules still apply: every behaviour change carries a test
that fails without it, identified requirements keep their ids (P1–P13,
E2E-01–E2E-12, `E_*`) so `scripts/traceability_report.py` can find them, and a
change to identity, normalisation, canonical serialisation, the fold, or the
staleness rules needs a schema-version review.

## Where each capability came from

| Capability | Converted from |
|---|---|
| `domain-model` | `docs/spec/01-domain-model.md` §1, §2, §4, §5 |
| `record-identity` | `01-domain-model.md` §3 |
| `repository-format` | `02-repository-format.md` §1–§3, §7 |
| `canonical-serialisation` | `02-repository-format.md` §5 |
| `event-log` | `02-repository-format.md` §4 |
| `derived-views` | `02-repository-format.md` §6 |
| `data-schemas` | `03-schemas.md` §1–§5 |
| `repository-verification` | `03-schemas.md` §10; `13-nonfunctional.md` §2; `04-git-integration.md` §1 |
| `git-integration` | `04-git-integration.md` §1–§4, §7 |
| `collaboration-sync` | `04-git-integration.md` §5 |
| `provenance-queries` | `04-git-integration.md` §6 |
| `literature-import` | `05-workflow-import.md` §1–§2 |
| `deduplication` | `05-workflow-import.md` §3 |
| `criteria-management` | `06-workflow-screening.md` §3 |
| `staleness` | `06-workflow-screening.md` §4–§6 |
| `screening` | `06-workflow-screening.md` §1, §2, §7; `10-cli.md` §5 |
| `adjudication` | `06-workflow-screening.md` §8 |
| `cli` | `10-cli.md` §1, §2, §4–§6 |
| `filter-language` | `10-cli.md` §3 |
| `web-ui` | `11-web-ui.md` |
| `architecture` | `12-architecture.md` §2–§6, §8 |
| `performance` | `13-nonfunctional.md` §1; `14-testing.md` §7 |
| `privacy-and-security` | `13-nonfunctional.md` §4–§5 |
| `copyright-and-licensing` | `13-nonfunctional.md` §6, §9 |
| `portability-and-i18n` | `13-nonfunctional.md` §3, §7 |
| `project-documentation` | `13-nonfunctional.md` §8; `15-roadmap.md` M2.1 (Wiki) |
| `test-suite` | `14-testing.md` §1–§8, §10 |
| `ci-gate` | `14-testing.md` §9 |
| `mcp-server` | `15-roadmap.md` M2.1 (Local MCP server) |

The changes carry the rest: `07-workflow-extraction.md` and `03-schemas.md`
§6–§8 (M3), `08-analysis.md` (M4), `09-reporting.md` (M5), `15-roadmap.md` M5.1,
`17-zotero-integration.md`, `14-testing.md` §11, and `12-architecture.md` §7
(M6). `00-overview.md` is summarised in `config.yaml`'s context;
`15-roadmap.md` and `16-open-questions.md` remain living planning documents in
`docs/spec/`.

## Known gaps in shipped capabilities

The specs under `specs/` describe the M0–M2.1 contract as the design documents
wrote it, which in a few places is ahead of the code. As of this conversion,
these specified behaviours are not yet implemented:

- `strata sync`, `strata migrate`, `strata diff`, `strata moderators`,
  `strata note`, and `strata gc --imports` (`collaboration-sync`,
  `repository-format`, `provenance-queries`, `cli`,
  `repository-verification`).
- EndNote XML, Excel, and PRISMA-style citation-list parsers
  (`literature-import`; deferred in `docs/m2-plan.md`, and tracked as a task in
  `add-distribution-and-adoption`).
- Opt-in enrichment and its `.strata/network.log` (`privacy-and-security`).
- The batched-commit policy's 200-decision and 15-minute triggers
  (`git-integration`; sessions commit when they end).
- Crash logs under `.strata/crash-<timestamp>.log` (`cli`).

`scripts/traceability_report.py` measures test coverage of identified
requirements; these gaps are the ones a reader of the specs would otherwise
assume are done.
