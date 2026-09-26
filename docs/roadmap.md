# Roadmap

*Informative, and a living document.* What shipped milestones must do is
specified in [`openspec/specs/`](../openspec/specs/); each milestone not yet
built is an OpenSpec change under [`openspec/changes/`](../openspec/changes/)
with its proposal, design, tasks, and delta specs. When a milestone ships, its
change is archived into the specs and this page is updated.

| Milestone | Status | OpenSpec |
|---|---|---|
| M0 — Substrate | done | specs |
| M1 — Literature in | done | specs |
| M2 — Screening and staleness | done (`0.1.0`) | specs |
| M2.1 — Wiki and local MCP server | ongoing (MCP server done) | specs: `mcp-server`, `project-documentation` |
| M3 — Full text and extraction | planned | `add-full-text-and-extraction` |
| M4 — Analysis | planned | `add-meta-analysis` |
| M5 — Reporting (`1.0.0`) | planned | `add-prisma-reporting` |
| M5.1 — Collaboration and hosting | planned; parts can start now | `add-container-image`, `add-hosted-team-deployment` |
| M6 — Hardening and adoption | ongoing | `add-distribution-and-adoption`, `add-zotero-integration`, `add-review-repository-ci` |

## Sequencing principle

Build the substrate first, then the flagship feature, then everything that makes
it a complete product. Each milestone ends with something a real reviewer could
use for real work, because a tool in this space only improves through contact
with actual reviews.

**M2 (staleness) came before extraction and analysis**, even though a
"complete" review needs those. If the staleness engine did not work and did not
feel trustworthy, the project would have no reason to exist, and that should be
discovered in month three rather than month nine.

**CI and the pull-request gate came before everything**, including the event
log (`openspec:ci-gate`): three of the project's correctness guarantees are
cross-platform byte-identity claims that cannot be checked on one laptop, and
the statistical validation is the entire credibility argument.

**The test suite grows with every milestone.** Each milestone lists its suite
additions, and the standing rule (`openspec:test-suite#every-change-carries-its-tests`)
— no behaviour change merges without a test that would have failed before it —
applies throughout. Treat the per-milestone additions as the floor.

---

## M0 — Substrate *(done)*

**Scope**: the pull-request gate, branch protection, and the specification
integrity checks — before any feature code; then `strata init`, `clone`,
`doctor`, `config`, `actor`; the event log, canonical serialisation, fold, ids
and normalisation; `gitio` and structured commits; `strata verify`, `status`,
`log`; merge drivers and hooks.

**Suite additions**: the harness itself — `pytest`, `hypothesis`, the OS x
Python matrix, the determinism job, coverage floors and diff coverage, the
requirement marker and its traceability report, and the docs checks.

**Acceptance**

- The gate blocks: a deliberately broken pull request — a failing test, a
  non-deterministic output, a broken specification reference — is rejected by CI
  on each of those grounds, verified by actually opening it.
- Branch protection on `main` requires the `gate` check, includes
  administrators, and a documentation-only pull request still merges cleanly.
- `strata init` produces a valid repository; `strata verify` passes on it.
- Property tests P1–P7, P13 pass.
- A round trip through `git clone`, edit, commit, push, pull is clean.
- Two clones appending disjoint events merge with zero conflicts (E2E-02
  skeleton).
- The determinism check passes on all three platforms in CI.

---

## M1 — Literature in *(done)*

**Scope**: all parsers; search recording; `strata import` with CSV mapping
profiles; the deduplication engine and review queue; `strata records`, `why`,
`fix`.

**Suite additions**: the golden parser corpus including the malformed cases, the
labelled dedup benchmark with its published precision/recall/false-merge
metrics, the fuzz corpus seeded from the fixtures, and P8 (dedup symmetry).

**Acceptance**

- All golden parser fixtures pass, including the malformed ones.
- Dedup benchmark: recall >= 0.95, false-merge rate <= 0.001 on a labelled set.
- 50,000-record import under 60 s; dedup under 300 s.
- `strata why` shows the full import and dedup provenance chain.
- Re-running dedup after a new import re-raises no previously judged pair.

EndNote XML, Excel, and PRISMA-style citation-list parsers were deferred and are
tracked in `add-distribution-and-adoption`.

---

## M2 — Screening and staleness *(done — the flagship, `0.1.0`)*

**Scope**: criteria management with direction classification; the staleness
engine; CLI and web screening surfaces; dual screening, blinding, IRR;
adjudication; `strata rescreen`, `audit`, `irr`; `strata serve`.

**Suite additions**: P10 (staleness soundness) against the brute-force
reference, E2E-01 and E2E-04 through E2E-06, the screening-latency benchmark,
and E2E-09 (interrupt and resume).

**Acceptance**

- **E2E-01 passes**: the origin scenario produces exactly the expected stale set.
- E2E-04, E2E-05, E2E-06 pass (loosening, retirement, cascade).
- Property test P10 passes against the brute-force reference.
- A screening session sustains < 100 ms p95 decision latency at 50k records.
- The criteria editor's impact preview is correct and non-mutating.
- Usability: three non-git users complete a screening session unaided *(still
  to be run by a human; see `docs/m2-plan.md`)*.

**This is the first genuinely useful release.** A team can run screening in it
and export to R for everything downstream.

---

## M2.1 — Project wiki and local MCP server *(ongoing, runs in parallel with M3+)*

M2.1 is not a sequential block: it started when M2 shipped and runs alongside
the later milestones. Documentation written months after a feature ships is
written from memory; documentation written in the same pull request is written
by the person who just built it.

### Wiki

Stand up the GitHub Wiki (`strata.wiki.git`) with the audience-oriented
documentation set (`openspec:project-documentation`): quickstart, first-time-git
guide, per-command CLI reference, web UI walkthrough, and a concepts section
(staleness, criteria versioning and direction, dedup, blinding) written for
reviewers, not implementers. The pull-request template's Wiki item keeps it
current.

### Local MCP server *(done)*

`strata mcp` (`openspec:mcp-server`): a read-only MCP server over stdio exposing
`status`, `why`, `log`, `records`, `criteria_diff`, and the criteria editor's
non-mutating impact preview. No MCP tool records a screening or criteria
decision.

**Acceptance**

- An MCP-aware client can query status, staleness, provenance, and history
  against a real repository, with the MCP server containing no domain logic
  beyond argument marshalling.
- No MCP tool commits a screening or criteria decision on its own.

---

## M3 — Full text and extraction *(planned: `add-full-text-and-extraction`)*

**Scope**: retrieval queue and full-text manifest; study grouping; extraction
schema, coding forms, units, dual extraction and reconciliation; data-quality
guards; risk-of-bias instruments; `strata export effects`.

**Suite additions**: unit-conversion round-trips, each data-quality guard
asserted to fire, RoB 2 algorithmic judgements against a published decision
set, and reconciliation event coverage.

**Acceptance**

- A complete review can be conducted through to an analysis-ready dataset.
- Dual extraction reconciliation records every decision.
- RoB 2 algorithmic suggestions match the published decision rules on a test set.
- `strata export effects` output is directly loadable by `metafor::rma()`.
- E2E-03 passes up to the analysis step.

---

## M4 — Analysis *(planned: `add-meta-analysis`)*

**Scope**: `stats` in full — effect-size computation and conversion, pooling
models, all `tau^2` estimators, Knapp–Hartung, heterogeneity, prediction
intervals, meta-regression, dependency handling, publication bias, diagnostics;
the deterministic SVG plot emitter; `strata analyze`; guardrails.

**Suite additions**: the full `metafor` fixture set and the nightly live-R drift
job, the published worked examples, every numerical edge case, P12, and
byte-identical plot comparison across platforms.

**Acceptance**

- Every estimator matches `metafor` to 1e-8 (1e-6 iterative) on the fixture set.
- Textbook worked examples reproduce exactly.
- All numerical edge cases produce a correct value or a specific error.
- Plots are byte-identical across platforms.
- Every guardrail fires under test.
- `strata diff` shows a pooled estimate moving when the pool changes.

The riskiest estimate in the roadmap: statistical validation against `metafor`
tends to surface convention mismatches that each take a day to run down. Budget
generously and do not compress it — this is where the project's credibility is
established or lost.

---

## M5 — Reporting *(planned: `add-prisma-reporting`)*

**Scope**: PRISMA flow diagram and count reconciliation; checklist generation;
Methods/Results/characteristics/amendments prose; manuscript export via pandoc;
bibliography export; the reproducibility package; robvis-style RoB plots;
funding and competing-interest metadata.

**Suite additions**: P11 (count reconciliation over randomly generated
histories), E2E-03 end to end, and a check that the reproducibility package
contains no full texts.

**Acceptance**

- Flow-diagram counts reconcile under property test P11 for random histories.
- Diagram output matches the official PRISMA 2020 template.
- A methodologist reviews the generated Methods text and judges it publishable
  without correction.
- The reproducibility package contains no copyrighted full texts.
- E2E-03 passes end to end.

**`1.0.0` ships here.** A complete review, from protocol to manuscript, in one
FOSS tool.

---

## M5.1 — Collaboration and hosting *(planned: `add-container-image`, `add-hosted-team-deployment`)*

**Decision (project lead):** `strata` supports a hosted, web-based mode so that
people who know little about git can collaborate as easily as they would in
Overleaf. Git is always the backend; the only question is whether the whole
`strata` stack runs remotely, or just the git repository. When working alone,
everything runs locally. See [overview §4](overview.md#4-deployment-topologies)
and open question Q11, now decided.

| Topology | `strata` runs | Repository | Status |
|---|---|---|---|
| Solo | Locally (native or container) | Local, optionally pushed for backup | works today |
| Local stacks, shared remote | On each collaborator's machine | Shared git remote | works today with plain git; `strata sync` makes it one command |
| Hosted instance | On a server the team runs, from the container image | Instance working copy synced with the shared remote | `add-hosted-team-deployment` |

The topologies interoperate: hosted and local collaborators can work on the same
review at the same time, because every one of them appends to per-actor event
files in the same repository format.

**Sequencing.** This milestone does not block M3–M5, and its first two pieces
can start immediately:

1. **`strata sync`** — already specified (`openspec:collaboration-sync`) but not
   yet implemented; it is the shared-remote workflow and the engine of the
   hosted sync loop.
2. **Container image** (`add-container-image`) — one image that runs every
   `strata` command and the local web UI against a mounted repository, with
   host-supplied git credentials, a public-URL setting for header validation, a
   health endpoint, multi-architecture builds published to GHCR, and
   determinism parity with native installs. Useful on its own for solo users
   and collaborators who will not install Python, and the unit of deployment for
   step 3.
3. **Hosted instance** (`add-hosted-team-deployment`) — `strata host`: many
   projects and users on one self-hosted instance, per-user accounts (built-in
   local accounts by default, OpenID Connect optional) mapped to actor handles
   per project, an automatic git sync loop with conflicts surfaced in-app,
   author/committer attribution, server-side blinding between users, a hosted
   security baseline, instance secrets kept out of review repositories, and the
   MCP tools over HTTP.

**Suite additions**: container smoke tests on both architectures and the
determinism check inside the image; a sync-loop E2E with two hosted members and
one local collaborator; authentication tests for local accounts and OIDC;
multi-tenancy isolation; blinding between users; a test that no secret reaches a
review repository.

**Acceptance**

- The container image runs every command and the web UI against a mounted
  repository with files owned by the host user, and generated output is
  byte-identical to a native install.
- A team runs a hosted instance from the image, points it at a shared remote,
  and screens, adjudicates, and edits criteria collaboratively without any
  member running a local `git` command.
- A collaborator using a local stack against the same remote works concurrently
  with hosted users; no decision is ever silently dropped, and conflicts in
  human-authored files are surfaced explicitly.
- Each commit and decision is attributed to the real reviewer who made it.
- One project's data is never reachable by a non-member.
- The MCP tools are reachable remotely under the same authentication.
- The hosted mode passes a dedicated security review.

---

## M6 — Hardening and adoption *(ongoing)*

- Standalone binaries for all platforms; Homebrew and conda-forge
  (`add-distribution-and-adoption`).
- Documentation set complete (`openspec:project-documentation`).
- A published worked example: a real, small, completed review in the
  repository, which doubles as documentation and a regression test.
- Import from Covidence, Rayyan, and EPPI-Reviewer exports — an explicit
  migration path off the paid tools, which is how this project gets its first
  users.
- **Zotero integration** (`add-zotero-integration`): pull a collection as an
  import source, resolve full texts during screening and extraction, push
  included studies to a collection for citation. Zotero owns the documents;
  `strata` owns the decisions.
- The reusable **review-repository CI workflow** and `strata verify` action
  (`add-review-repository-ci`), so review teams get pre-merge assurance for
  their data. Depends only on M0, so it may land earlier.
- Translations.

---

## Post-1.0 candidates *(not committed)*

Ordered by expected value, not by ease:

| Candidate | Note |
|---|---|
| Vevea–Hedges selection models, p-curve, p-uniform* | Completes the publication-bias toolkit |
| Living systematic reviews | Scheduled re-searches with automatic staleness — a natural fit for this architecture and arguably its best long-term differentiator |
| Machine-assisted prioritisation | Via the `Prioritiser` interface: reordering only, never deciding |
| Hosted instance as a git server | An Overleaf-style git bridge, so a project needs no external remote |
| Zotero annotations as extraction sources | Highlight a number in the PDF, get the source locator for free |
| Other reference managers (Mendeley, EndNote, Paperpile) | Via the same generic interface |
| PRISMA-S, PRISMA-ScR, PRISMA-IPD extensions | Scoping reviews are a large and under-served share of the market |
| GRADE certainty assessment | PRISMA item 22; currently author work |
| Network meta-analysis | Large; possibly better delegated to R via export |
| Bayesian models | Via Stan/`brms` export rather than native implementation |
| A read-only web publication of a review | "Here is our review, fully auditable" as a static site generated from the repository |

## Effort summary

Roughly 8–10 months of one focused full-time developer to `1.0.0`, or 12–15
months at a realistic academic pace. M5.1's container image is small (days);
`strata sync` is moderate; the hosted instance is the size of a milestone
(6–8 weeks) and needs a security review.
