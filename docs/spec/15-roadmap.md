# 15 — Roadmap *(informative)*

## Sequencing principle

Build the substrate first, then the flagship feature, then everything that makes
it a complete product. Each milestone ends with something a real reviewer could
use for real work, because a tool in this space only improves through contact
with actual reviews.

The ordering is deliberate in two respects.

**M2 (staleness) comes before extraction and analysis**, even though a "complete"
review needs those. If the staleness engine does not work and does not feel
trustworthy, the project has no reason to exist, and that should be discovered in
month three rather than month nine.

**CI and the pull-request gate come before everything**, including the event log.
The reasoning is in [14 §9.1](14-testing.md): three of this project's
correctness guarantees are cross-platform byte-identity claims that cannot be
checked on one laptop, and the statistical validation is the entire credibility
argument. A gate that arrives late is a gate that never retroactively covers the
code written before it.

**The test suite grows with every milestone.** Each milestone below lists its
suite additions explicitly, and the standing rule in
[14 §10](14-testing.md) — no behaviour change merges without a test that would
have failed before it — applies from M0 onwards. Treat the per-milestone
additions as the floor, not the ceiling.

---

## M0 — Substrate *(4–6 weeks)*

CI first, then the repository format and the git wrapper. No screening yet.

**Scope**: **the pull-request gate, branch protection, and the documentation
integrity checks ([14 §9](14-testing.md)) — before any feature code**; then
`strata init`, `clone`, `doctor`, `config`, `actor`; the event log, canonical
serialisation, fold, ids and normalisation; `gitio` and structured commits;
`strata verify`, `status`, `log`; merge drivers and hooks.

**Scope**: all parsers; search recording; `strata import` with CSV mapping
profiles; the deduplication engine and review queue; `strata records`, `why`,
`fix`.

**Suite additions**: the harness itself — `pytest`, `hypothesis`, the OS x
Python matrix, the determinism job, coverage floors and diff coverage, the
requirement marker and its traceability report ([14 §10.5](14-testing.md)), and
the `docs.yml` link/anchor/config-block checks. **Acceptance** - **The gate
blocks.** A deliberately broken pull request — a failing test, a
non-deterministic output, a broken specification anchor — is rejected by CI on
each of those three grounds. Verified by actually opening it, not by reading the
workflow file. - Branch protection on `main` requires the `gate` check, includes
administrators, and a documentation-only pull request still merges cleanly. -
`strata init` produces a valid repository; `strata verify` passes on it. -
Property tests P1–P7, P13 pass. - A round trip through `git clone`, edit,
commit, push, pull is clean. - Two clones appending disjoint events merge with
zero conflicts (E2E-02 skeleton). - Determinism check passes on all three
platforms **in CI**, not just locally. --- ## M1 — Literature in *(4–6 weeks)*
**Suite additions**: the golden parser corpus ([14 §3](14-testing.md)) including
the malformed cases, the labelled dedup benchmark with its published
precision/recall/false-merge metrics, the fuzz corpus seeded from the fixtures,
and P8 (dedup symmetry).

**Acceptance**
- All golden parser fixtures pass, including the malformed ones.
- Dedup benchmark: recall >= 0.95, false-merge rate <= 0.001 on a labelled set.
- 50,000-record import under 60 s; dedup under 300 s.
- `strata why` shows the full import and dedup provenance chain.
- Re-running dedup after a new import re-raises no previously judged pair.

---

## M2 — Screening and staleness *(6–8 weeks)* — **the flagship**

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
- Usability: three non-git users complete a screening session unaided.

**This is the first genuinely useful release.** A team could run screening in it
and export to R for everything downstream. Ship it as `0.1.0` and get it in front
of real reviews.

---

## M2.1 — Project wiki *(ongoing, starts now, runs in parallel with M3+)*

Unlike every other milestone here, M2.1 is not a sequential block with a start
and an end — it starts the moment M2 ships and then runs continuously
alongside M3, M4, M5, and M6, rather than being deferred to the documentation
push in [M6](#m6--hardening-and-adoption-ongoing). The reasoning: documentation
written months after a feature ships is written from memory, by which point the
person who best understood the feature has usually moved on to the next one.
Documentation written in the same pull request as the feature is written by the
person who just built it, while the reasoning is still fresh.

**Scope**: stand up a GitHub Wiki for the project (its own versioned git
repository, `strata.wiki.git`, needing no additional hosting or infrastructure)
covering the audience-oriented documentation set from
[13 §8](13-nonfunctional.md): a quickstart, a "first time using git" guide, a
per-command CLI reference, a web UI walkthrough, and a concepts section
(staleness, criteria versioning and direction classification, dedup, blinding)
written for reviewers, not implementers — a different register from
`docs/spec/`, which targets an implementer building the tool, not a
methodologist using it. Backfill it initially with pages for everything M0–M2
already shipped; from then on, treat it as a live document.

**Process, not a one-time task**: add a "Wiki" checklist item to the pull
request template (alongside the existing "Tests" and "Spec" sections) asking
whether the change adds or alters a user-facing command, web screen, or
concept, and if so, whether the corresponding wiki page was updated in this
PR or a fast-follow. This is deliberately a checklist prompt, not a CI gate —
docs quality doesn't reduce to a boolean a script can check, so this stays a
review-time judgment call the way rationale quality already does
([04 §2.3](04-git-integration.md)).

**Acceptance**
- The wiki exists and has at least one page for every M0–M2 CLI command and
  every implemented web UI screen.
- The pull request template's Wiki checklist item is in place and in use.
- Every milestone from M3 onward closes with its own user-facing additions
  already reflected in the wiki, not queued as an M6 backlog item — checked as
  part of that milestone's own acceptance pass, alongside its other
  acceptance criteria.

---

## M3 — Full text and extraction *(6–8 weeks)*

**Scope**: retrieval queue and full-text manifest; study grouping; extraction
schema, coding forms, units, dual extraction and reconciliation; data-quality
guards; risk-of-bias instruments; `strata export effects`.

**Suite additions**: unit-conversion round-trips, the data-quality guards of [07
§3.5](07-workflow-extraction.md) each asserted to fire, RoB 2 algorithmic
judgements against a published decision set, and reconciliation event coverage.

**Acceptance**
- A complete review can be conducted through to an analysis-ready dataset.
- Dual extraction reconciliation records every decision.
- RoB 2 algorithmic suggestions match the published decision rules on a test set.
- `strata export effects` output is directly loadable by `metafor::rma()`.
- E2E-03 passes up to the analysis step.

---

## M4 — Analysis *(8–10 weeks)*

**Scope**: `stats` in full — effect-size computation and conversion, pooling
models, all `tau^2` estimators, Knapp–Hartung, heterogeneity, prediction
intervals, meta-regression, dependency handling, publication bias, diagnostics;
the deterministic SVG plot emitter; `strata analyze`; guardrails.

**Suite additions**: the full `metafor` fixture set and the nightly live-R drift
job, the published worked examples of [14 §4.2](14-testing.md), every numerical
edge case in §4.3, P12, and byte-identical plot comparison across platforms.

**Acceptance**
- Every estimator matches `metafor` to 1e-8 (1e-6 iterative) on the fixture set.
- Textbook worked examples reproduce exactly (§[14 §4.2](14-testing.md)).
- All numerical edge cases produce a correct value or a specific error.
- Plots are byte-identical across platforms.
- Every guardrail in [08 §8](08-analysis.md) fires under test.
- `strata diff` shows a pooled estimate moving when the pool changes.

---

## M5 — Reporting *(4–6 weeks)*

**Scope**: PRISMA flow diagram and count reconciliation; checklist generation;
Methods/Results/characteristics/amendments prose; manuscript export via pandoc;
bibliography export; the reproducibility package; robvis-style RoB plots.

**Suite additions**: P11 (count reconciliation over randomly generated
histories), E2E-03 end to end, and a check that the reproducibility package
contains no full texts.

**Acceptance**
- Flow-diagram counts reconcile under property test P11 for random histories.
- Diagram output matches the official PRISMA 2020 template (verified against the
  official materials, [09 §1](09-reporting.md)).
- A methodologist reviews the generated Methods text and judges it publishable
  without correction.
- The reproducibility package contains no copyrighted full texts.
- E2E-03 passes end to end.

**`1.0.0` ships here.** A complete review, from protocol to manuscript, in one
FOSS tool.

---

## M6 — Hardening and adoption *(ongoing)*

- Standalone binaries for all platforms; Homebrew and conda-forge.
- Documentation set ([13 §8](13-nonfunctional.md)) complete.
- A published worked example: a real, small, completed review in the repository,
  which doubles as the best possible documentation and a regression test.
- Import from Covidence, Rayyan, and EPPI-Reviewer exports — an explicit
  migration path off the paid tools, which is how this project gets its first
  users.
- **Zotero integration** ([17](17-zotero-integration.md)): pull a collection as
  an import source, resolve full texts during screening and extraction, push
  included studies to a collection for citation while writing. This closes the
  one gap the no-PDFs decision leaves open, and it reaches users where they
  already are.
- The reusable **review-repository CI workflow** and `strata verify` action
  ([14 §11](14-testing.md)), so review teams get the same pre-merge assurance for
  their data that this project has for its code. Depends only on M0, so it may
  land earlier.
- Translations.

---

## Post-1.0 candidates *(not committed)*

Ordered by expected value, not by ease:

| Candidate | Note |
|---|---|
| Vevea–Hedges selection models, p-curve, p-uniform* | Completes the publication-bias toolkit |
| Living systematic reviews | Scheduled re-searches with automatic staleness — a very natural fit for this architecture, and arguably its best long-term differentiator |
| Machine-assisted prioritisation | Via the `Prioritiser` interface ([12 §5](12-architecture.md)): reordering only, never deciding |
| Zotero annotations as extraction sources ([17 §7](17-zotero-integration.md)) | Highlight a number in the PDF, get the source locator for free |
| Other reference managers (Mendeley, EndNote, Paperpile) | Via the same generic interface |
| PRISMA-S, PRISMA-ScR, PRISMA-IPD extensions | Scoping reviews are a large and under-served share of the market |
| GRADE certainty assessment | Item 22; currently author work |
| Network meta-analysis | Large; possibly better delegated to R via export |
| Bayesian models | Via Stan/`brms` export rather than native implementation |
| A read-only web publication of a review | "Here is our review, fully auditable" as a static site generated from the repository |

## Effort summary

Roughly 8–10 months of one focused full-time developer to `1.0.0`, or 12–15
months at a realistic academic pace. M2 alone (about 4 months in) produces
something worth using and worth showing to potential collaborators and funders.

The riskiest estimate is M4: statistical validation against `metafor` tends to
surface convention mismatches that each take a day to run down. Budget generously
and do not compress it, because that is the milestone where the project's
credibility is either established or lost.
