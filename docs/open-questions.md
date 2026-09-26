# Open questions

*Informative.* Decisions that belong to the project lead rather than to the
implementer. Each open question has a recommendation; decided ones are kept
because their reasoning still affects outstanding work.

---

## Q1 — Project name — **DECIDED: `strata`**

The project is named **strata**, and `strata` is the command.

**Why.** Sedimentary strata are layers laid down in order, never rewritten, and
readable afterwards as a history of what happened and when — a precise
description of the architecture: an append-only event log, a versioned protocol,
and a git history in which every layer of the review stays legible. The name
carries no methodological claim, which matters for a tool whose output goes into
published work.

**What it replaced.** The working name was `epic`, which collided three times in
exactly this domain: Epic Systems Corporation (the dominant US electronic health
record vendor, with an aggressively defended trademark in health software — the
serious one); EPIC, the European Prospective Investigation into Cancer and
Nutrition, which appears constantly in the literature this tool reviews; and
Epic Games / the Electronic Privacy Information Center. Other candidates
considered: `winnow` (existing idiom, weak as a mark), `cairn` (`cairn.info` is a
major scholarly publishing portal), `tessera` (a biotech of that name),
`palimpsest` (the best metaphor, too long to type), `stele`, `florilegium`,
`assay`. Rejected for collisions with active projects: `glean`, `sift`, `quire`,
and anything built on `prism`, which would imply endorsement by the PRISMA
group.

**Outstanding before first public release:**

1. **Trademark search.** "Strata" is a common word used across many software
   products; none found so far is in evidence synthesis or health research, but
   a proper search is warranted.
2. **PyPI distribution name.** `strata` on PyPI is registered but has never had
   a release, making it a candidate for the PEP 541 name-claim process. Until
   that succeeds, ship as **`strata-review`** (confirmed free); the command is
   still `strata`.
3. **Registries.** Reserve the name on Homebrew and conda-forge, and choose the
   container image name (`ghcr.io/eguthriewastaken/strata` is assumed in
   `add-container-image`).

---

## Q2 — Licence for the repository format

`strata` itself is GPL-3.0-or-later, as decided. Separately: a file format that
only one implementation can legally read is not a format. Should the repository
format — the `repository-format`, `canonical-serialisation`, `event-log`,
`record-identity`, and `data-schemas` specs, the shipped JSON Schemas, and a
minimal reference reader — be released permissively so that Zotero, an R
package, or a future competitor can interoperate?

**Recommendation.** Yes. Specification documents under CC BY 4.0, JSON Schema
files and a thin reader library under Apache-2.0, application code under
GPL-3.0-or-later. Wide format adoption is what makes a review's data durable
beyond this project.

---

## Q3 — Scope of v1: which review types?

The specification assumes an intervention-style systematic review with
quantitative synthesis. Scoping reviews, qualitative evidence syntheses,
diagnostic test accuracy reviews, and prevalence reviews use the same screening
machinery and different (or no) analysis.

**Recommendation.** Keep the screening and provenance core generic — it already
is — and ship v1 with the quantitative analysis path only. Scoping reviews
(PRISMA-ScR) are the largest adjacent market and need no new analysis, mostly a
different flow diagram and checklist; they are a cheap M6 addition.

---

## Q4 — Does `analysis/results/` really belong in git?

Committing generated results is what makes `strata diff` show a pooled estimate
moving when the pool changes. It also means every analysis run dirties the
working tree and adds noise to history.

**Recommendation.** Commit them, but only when the user runs `strata analyze`
deliberately, never as a side effect of another command, and keep plots out of
`git diff` via `.gitattributes`. Revisit if history noise becomes a real
complaint. (Adopted in `add-meta-analysis`.)

---

## Q5 — How aggressively should the tool block bad practice?

`strata` can refuse a publication-bias test at `k < 10`, refuse meta-regression
at `k <= p`, and refuse a PRISMA diagram with stale decisions. Every such block
is a methodological opinion imposed on a user who may know better.

**Recommendation.** Block with `--force` always available and always logged in
`run.json`, so the override is recorded rather than invisible. Never block
silently, and never without explaining the reasoning and citing a source. The
tool's job is to make the right thing easy and the wrong thing *deliberate*, not
impossible. (Adopted in `add-meta-analysis`.)

---

## Q6 — Multiple reviews in one repository?

A research group may run several related reviews sharing a search or a
screening pool.

**Recommendation.** One review per repository. The shared-pool case is real but
rare, and modelling it would complicate identity, staleness, and the flow
diagram considerably. A hosted instance serves many repositories side by side,
which covers the common "one lab, several reviews" case without changing the
format. Revisit if users ask.

---

## Q7 — Conflict-of-interest and funding metadata

PRISMA items 25 and 26 require reporting competing interests and funding
sources.

**Recommendation.** Add them to `strata.toml` in M5. Cheap, and it removes two
more items from the author's manual checklist. (Adopted in
`add-prisma-reporting`.)

---

## Q8 — How much should `strata` help write the manuscript?

`add-prisma-reporting` draws the line at generated Methods and Results prose and
refuses to generate a Discussion or Conclusion. The line could be drawn tighter
(tables and numbers only) or looser.

**Recommendation.** Hold the line. Generated Methods text is mechanical
transcription of facts the repository already knows, and doing it by hand is a
documented source of error. A Discussion is an argument, and a tool that drafts
arguments for researchers makes the literature worse.

---

## Q9 — Living systematic reviews

The architecture is unusually well suited to reviews updated continuously: a
re-run search is a new import, new records are unscreened, and existing
decisions are untouched unless criteria change. No free tool supports this.

**Recommendation.** Keep it out of v1 scope, but do not foreclose it: the
`supersedes` field on searches and the append-only event log are already the
right shape. Revisit immediately after 1.0. A hosted instance with a scheduled
re-import would make it especially natural.

---

## Q10 — Governance and sustainability

A tool researchers commit multi-year projects to needs a credible answer to
"what happens if the maintainer moves on?" — more so than most FOSS, because the
data outlives the software.

**Recommendation.** Address it structurally: the plain-text format with a
permissive specification licence (Q2) means a dead project still leaves fully
readable data, and because a hosted instance is only ever a git client, no
review is ever trapped in one. Beyond that, consider an institutional home (a
university library, the Open Science Framework, or a Cochrane/Campbell methods
group) and a named second maintainer before promoting the tool widely. Funders
in evidence synthesis (Wellcome, NIHR, Arcadia, CZI's EOSS programme) fund
exactly this kind of infrastructure.

---

## Q11 — Should `strata` support a hosted option? — **DECIDED: yes, self-hosted**

**Decision.** `strata` supports a hosted, web-based mode so collaborators who
know little about git can work together as easily as in Overleaf. Git is always
the backend: a team either runs the whole `strata` stack on a server
(collaborators sign in with their own credentials) or runs `strata` locally and
shares only the git repository (commit, push, and sync). Working alone,
everything runs locally. A container image makes both the local and hosted
setups one command. See M5.1 in the [roadmap](roadmap.md) and the
`add-container-image` and `add-hosted-team-deployment` changes.

**What the decision does not change.** The project does not operate a service
(non-goal N6 in the [overview](overview.md#5-non-goals)); teams host their own
instances. The data is always an ordinary `strata` git repository that can be
cloned out of an instance at any time, so hosting adds convenience without
adding lock-in.

**Reasoning recorded.** The earlier recommendation was to hold a no-hosting line
because a hosted service changes cost structure, security surface, and
governance. Self-hosting keeps the cost structure (no project-run
infrastructure) and governance (git remains the source of truth); the security
surface is real, which is why the hosted mode has its own security baseline and
a dedicated review before release.

**Still open within Q11:**

- Whether the instance should also act as a git server (an Overleaf-style git
  bridge) so a project needs no external remote. Deferred to post-1.0.
- Whether to provide multi-factor authentication for local accounts, or rely on
  an OpenID Connect provider for it.
