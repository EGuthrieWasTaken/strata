# 15 — Roadmap *(informative)*

## Sequencing principle

Build the substrate first, then the flagship feature, then everything that makes
it a complete product. Each milestone ends with something a real reviewer could
use for real work, because a tool in this space only improves through contact
with actual reviews.

The ordering is deliberate in one respect: **M2 (staleness) comes before
extraction and analysis**, even though a "complete" review needs those. If the
staleness engine does not work and does not feel trustworthy, the project has no
reason to exist, and that should be discovered in month three rather than month
nine.

---

## M0 — Substrate *(4–6 weeks)*

The repository format and the git wrapper. No screening yet.

**Scope**: `epic init`, `clone`, `doctor`, `config`, `actor`; the event log,
canonical serialisation, fold, ids and normalisation; `gitio` and structured
commits; `epic verify`, `status`, `log`; merge drivers and hooks.

**Acceptance**
- `epic init` produces a valid repository; `epic verify` passes on it.
- Property tests P1–P7, P13 pass.
- A round trip through `git clone`, edit, commit, push, pull is clean.
- Two clones appending disjoint events merge with zero conflicts (E2E-02 skeleton).
- Determinism check passes on all three platforms.

---

## M1 — Literature in *(4–6 weeks)*

**Scope**: all parsers; search recording; `epic import` with CSV mapping
profiles; the deduplication engine and review queue; `epic records`, `why`,
`fix`.

**Acceptance**
- All golden parser fixtures pass, including the malformed ones.
- Dedup benchmark: recall >= 0.95, false-merge rate <= 0.001 on a labelled set.
- 50,000-record import under 60 s; dedup under 300 s.
- `epic why` shows the full import and dedup provenance chain.
- Re-running dedup after a new import re-raises no previously judged pair.

---

## M2 — Screening and staleness *(6–8 weeks)* — **the flagship**

**Scope**: criteria management with direction classification; the staleness
engine; CLI and web screening surfaces; dual screening, blinding, IRR;
adjudication; `epic rescreen`, `audit`, `irr`; `epic serve`.

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

## M3 — Full text and extraction *(6–8 weeks)*

**Scope**: retrieval queue and full-text manifest; study grouping; extraction
schema, coding forms, units, dual extraction and reconciliation; data-quality
guards; risk-of-bias instruments; `epic export effects`.

**Acceptance**
- A complete review can be conducted through to an analysis-ready dataset.
- Dual extraction reconciliation records every decision.
- RoB 2 algorithmic suggestions match the published decision rules on a test set.
- `epic export effects` output is directly loadable by `metafor::rma()`.
- E2E-03 passes up to the analysis step.

---

## M4 — Analysis *(8–10 weeks)*

**Scope**: `stats` in full — effect-size computation and conversion, pooling
models, all `tau^2` estimators, Knapp–Hartung, heterogeneity, prediction
intervals, meta-regression, dependency handling, publication bias, diagnostics;
the deterministic SVG plot emitter; `epic analyze`; guardrails.

**Acceptance**
- Every estimator matches `metafor` to 1e-8 (1e-6 iterative) on the fixture set.
- Textbook worked examples reproduce exactly (§[14 §4.2](14-testing.md)).
- All numerical edge cases produce a correct value or a specific error.
- Plots are byte-identical across platforms.
- Every guardrail in [08 §8](08-analysis.md) fires under test.
- `epic diff` shows a pooled estimate moving when the pool changes.

---

## M5 — Reporting *(4–6 weeks)*

**Scope**: PRISMA flow diagram and count reconciliation; checklist generation;
Methods/Results/characteristics/amendments prose; manuscript export via pandoc;
bibliography export; the reproducibility package; robvis-style RoB plots.

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
