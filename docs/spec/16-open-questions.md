# 16 — Open questions *(informative)*

Decisions that belong to the project lead rather than to the implementer. Each
has a recommendation; none blocks starting M0.

---

## Q1 — Project name — **DECIDED: `strata`**

The project is named **strata**, and `strata` is the command. This section is
retained because the reasoning affects release tasks that are still outstanding.

**Why.** Sedimentary strata are layers laid down in order, never rewritten, and
readable afterwards as a history of what happened and when. That is a precise
description of this tool's architecture: an append-only event log, a versioned
protocol, and a git history in which every layer of the review stays legible.
The name also carries no methodological claim, which matters for a tool whose
output goes into published work.

**What it replaced, and why not the others.** The working name was `epic`, which
had three collisions in exactly this domain:

- **Epic Systems Corporation** — the dominant US electronic health record vendor,
  with an aggressively defended trademark in health software. A systematic-review
  tool given to health researchers is plausibly the same class of goods. This was
  the serious one.
- **EPIC** — the European Prospective Investigation into Cancer and Nutrition, a
  half-million-participant cohort study that appears constantly in the
  epidemiological literature this tool is used to review.
- **Epic Games**, and **EPIC** the Electronic Privacy Information Center — less
  likely to matter, but they own the search results.

Other candidates considered: `winnow` (clearest meaning, but "winnowing the
literature" is existing idiom and therefore weak as a mark), `cairn` (exact
provenance metaphor, but `cairn.info` is a major French-language scholarly
publishing portal — adjacent space), `tessera` (distinctive, but Tessera
Therapeutics is a biotech and the health adjacency is not zero), `palimpsest`
(the best metaphor of all — revision that never erases — but too long to type),
`stele`, `florilegium`, `assay`. Rejected outright for collisions with active
projects: `glean` (Mozilla's Glean SDK), `sift` (Sift Science), `quire` (Getty's
Quire, an active scholarly publishing tool), and anything built on `prism`, which
would imply endorsement by the PRISMA group.

**Outstanding before first public release:**

1. **Trademark search.** "Strata" is a common English word used across many
   software products; none found so far is in evidence synthesis or health
   research, but a proper search is still warranted given that the tool's users
   are in exactly the sector where the earlier name failed.
2. **PyPI distribution name.** The name `strata` on PyPI is registered but has
   **never had a release** (`0.0.0dev`, no files). It is therefore a candidate
   for the PEP 541 name-claim process, which is worth attempting. Until that
   succeeds, ship as **`strata-review`** (confirmed free), so the install line is
   `pipx install strata-review` and the command is `strata`. A mismatch between
   distribution name and command is a mild and very common tax (`ripgrep`
   installs `rg`); losing the command name would be worse.
3. **GitHub.** The repository is still named `epic`; rename it, and reserve the
   command name on Homebrew and conda-forge at the same time.

---

## Q2 — Licence for the repository format

`strata` itself is GPL-3.0-or-later, as decided. Separately: a file format that
only one implementation can legally read is not a format. Should
[02](02-repository-format.md) and [03](03-schemas.md) — and a minimal reference
reader library — be released permissively (CC0, Apache-2.0, or MIT) so that
Zotero, an R package, or a future competitor can interoperate?

**Recommendation.** Yes. Specification documents under CC BY 4.0, JSON Schema
files and a thin reader library under Apache-2.0, application code under
GPL-3.0-or-later. Wide format adoption is what makes a review's data durable
beyond this project, which is the point.

---

## Q3 — Scope of v1: which review types?

The specification assumes an intervention-style systematic review with
quantitative synthesis. Scoping reviews, qualitative evidence syntheses,
diagnostic test accuracy reviews, and prevalence reviews all use the same
screening machinery and different (or no) analysis.

**Recommendation.** Build the screening and provenance core generically — it
already is — and ship v1 with the quantitative analysis path only. Scoping
reviews (PRISMA-ScR) are the largest adjacent market and need no new analysis at
all, mostly a different flow diagram and checklist; they are a cheap M6 addition.

---

## Q4 — Does `analysis/results/` really belong in git?

Committing generated results is what makes `strata diff` show a pooled estimate
moving when the pool changes — a genuinely compelling feature. It also means
every analysis run dirties the working tree and adds noise to history.

**Recommendation.** Commit them, but only when the user runs `strata analyze`
deliberately, never as a side effect of another command, and keep plots out of
`git diff` via `.gitattributes`. Revisit if history noise becomes a real
complaint from users.

---

## Q5 — How aggressively should the tool block bad practice?

`strata` can refuse a publication-bias test at `k < 10`, refuse meta-regression at
`k <= p`, and refuse a PRISMA diagram with stale decisions. Every such block is a
methodological opinion imposed on a user who may know better.

**Recommendation.** Block with `--force` always available and always logged in
`run.json`, so the override is recorded rather than invisible. Never block
silently, never block without explaining the reasoning and citing a source. The
tool's job is to make the right thing easy and the wrong thing *deliberate*, not
impossible.

---

## Q6 — Multiple reviews in one repository?

A research group may run several related reviews sharing a search or a screening
pool.

**Recommendation.** One review per repository for v1. The shared-pool case is
real but rare, and modelling it would complicate identity, staleness, and the
flow diagram considerably. Revisit if users ask.

---

## Q7 — Conflict-of-interest and funding metadata

PRISMA items 25 and 26 require reporting competing interests and funding sources.
These could live in `strata.toml` and flow into generated output.

**Recommendation.** Add them to `strata.toml` in M5. Cheap, and it removes two more
items from the author's manual checklist.

---

## Q8 — How much should `strata` help write the manuscript?

[09 §5.1](09-reporting.md) draws the line at generated Methods and Results prose,
and explicitly refuses to generate a Discussion or Conclusion. That line could be
drawn tighter (tables and numbers only, no prose) or looser.

**Recommendation.** Hold the line as specified. Generated Methods text is
mechanical transcription of facts the repository already knows, and doing it by
hand is a documented source of error. A Discussion is an argument, and a tool
that drafts arguments for researchers makes the literature worse.

---

## Q9 — Living systematic reviews

The architecture is unusually well suited to reviews that are updated
continuously: a re-run search is a new import, new records are unscreened, and
existing decisions are untouched unless criteria change. This may be the
project's strongest long-term differentiator, since no free tool supports it.

**Recommendation.** Keep it out of v1 scope, but do not foreclose it: the
`supersedes` field on searches and the append-only event log are already the
right shape. Revisit immediately after 1.0.

---

## Q10 — Governance and sustainability

A tool that researchers commit multi-year projects to needs a credible answer to
"what happens if the maintainer moves on?" — more so than most FOSS, because the
data outlives the software.

**Recommendation.** Address it structurally rather than organisationally: the
plain-text format with a permissive specification licence (Q2) means a dead
project still leaves fully readable data. Beyond that, consider an institutional
home (a university library, the Open Science Framework, or a Cochrane/Campbell
methods group) and a named second maintainer before promoting the tool widely.
Funders in evidence synthesis (Wellcome, NIHR, Arcadia, CZI's EOSS programme)
fund exactly this kind of infrastructure, and a working M2 demo is a far stronger
application than a proposal.

---

## Q11 — Should `strata` ship a hosted option?

[00 §4](00-overview.md) rules out a hosted service as a non-goal. But the
collaborator who will not install software is a real and common obstacle, and
"set up a GitHub account" is itself a barrier for some researchers.

**Recommendation.** Hold the non-goal. The mitigation is better packaging
(standalone binaries, M6) and the read-only published review site in the post-1.0
list, not a backend. A hosted service changes the project's cost structure,
security surface, and governance obligations entirely, and the whole premise here
is that those are what make the incumbents expensive.
