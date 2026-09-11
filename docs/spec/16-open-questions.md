# 16 — Open questions *(informative)*

Decisions that belong to the project lead rather than to the implementer. Each
has a recommendation; none blocks starting M0.

---

## Q1 — Project name

**The concern.** `epic` has three collisions that matter in exactly this domain:

- **Epic Systems Corporation** — the dominant US electronic health record
  vendor, with an aggressively defended trademark in health software. A
  systematic-review tool sold to (or given to) health researchers is plausibly
  the same class of goods. This is the serious one.
- **EPIC** — the European Prospective Investigation into Cancer and Nutrition, a
  half-million-participant cohort study that appears constantly in the
  epidemiological literature this tool will be used to review. "We screened the
  EPIC records in epic" is a genuinely confusing sentence.
- **Epic Games**, and **EPIC** the Electronic Privacy Information Center — less
  likely to matter, but they own the search results.

**Also settled by checking:** the PyPI name `epic` is already taken (a different
project); `epic-review` is currently free.

**Recommendation.** Keep `epic` as the working name and the CLI verb for now —
it is short, memorable, and typing `epic screen` is pleasant. Choose a
distinguishable published name before the first public release, and ideally one
that is also the CLI verb, since a mismatch between `pip install epic-review` and
`epic` is a small permanent tax on every user. Worth a trademark search rather
than a guess, given the health-software overlap.

### Candidates

PyPI's single-word namespace is largely exhausted, so "taken" below distinguishes
a *dead stub* (reclaimable in practice, and harmless either way since the
distribution name need not match the command name) from an *active project* worth
avoiding. What actually matters is the command name, the GitHub org, and
trademark safety.

| Name | Meaning | PyPI | Notes |
|---|---|---|---|
| **winnow** | To separate grain from chaff — literally what screening is | stub (2015) | Strongest meaning-to-length ratio. "Winnowing the literature" is already idiom in this field, which helps discoverability and hurts distinctiveness |
| **cairn** | A stack of stones marking a trail; you add to it as you pass | stub (2019) | Provenance metaphor is exact. **But**: `cairn.info` is a major French-language scholarly publishing portal — adjacent space, real confusion risk |
| **tessera** | One tile of a mosaic; each study is a tessera, the review is the picture | stub (2017, dead Graphite dashboard) | Distinctive and pretty. Tessera Therapeutics is a biotech — different goods class, but the health adjacency is not zero |
| **palimpsest** | A manuscript rewritten with the earlier text still legible | stub | The *best* metaphor for this specific product — revision that never erases. Too long to type; would need a short command alias |
| **stele** | An inscribed stone slab; a permanent public record of decisions | 0.0.0 placeholder | Unique, evocative, but people will not know how to say or spell it |
| **florilegium** | A medieval compilation of excerpts from many works — a pre-modern meta-analysis | **free outright** | Delightful and completely unclaimed. Far too long as a command; works better as a tagline than a name |
| **assay** | A systematic test or analysis | never released | Short, scientific, types well. Chemistry/biology connotation may mislead in biomedical contexts |
| **strata** | Layers, deposited in order and readable as history | never released | Version-history metaphor; slightly generic |

**Avoid** (active projects or strong collisions): `glean` (Mozilla's Glean
telemetry SDK), `sift` (Sift Science, commercial), `quire` (Getty's Quire is an
active scholarly publishing tool — same space), `rubric`, `concordance`, and
anything built on `prism`, which would imply endorsement by the PRISMA group.

**If forced to pick two:** `winnow` for the clearest meaning, `tessera` for the
most distinctive mark. Both are worth a proper trademark search first.

---

## Q2 — Licence for the repository format

`epic` itself is GPL-3.0-or-later, as decided. Separately: a file format that
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

Committing generated results is what makes `epic diff` show a pooled estimate
moving when the pool changes — a genuinely compelling feature. It also means
every analysis run dirties the working tree and adds noise to history.

**Recommendation.** Commit them, but only when the user runs `epic analyze`
deliberately, never as a side effect of another command, and keep plots out of
`git diff` via `.gitattributes`. Revisit if history noise becomes a real
complaint from users.

---

## Q5 — How aggressively should the tool block bad practice?

`epic` can refuse a publication-bias test at `k < 10`, refuse meta-regression at
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
These could live in `epic.toml` and flow into generated output.

**Recommendation.** Add them to `epic.toml` in M5. Cheap, and it removes two more
items from the author's manual checklist.

---

## Q8 — How much should `epic` help write the manuscript?

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

## Q11 — Should `epic` ship a hosted option?

[00 §4](00-overview.md) rules out a hosted service as a non-goal. But the
collaborator who will not install software is a real and common obstacle, and
"set up a GitHub account" is itself a barrier for some researchers.

**Recommendation.** Hold the non-goal. The mitigation is better packaging
(standalone binaries, M6) and the read-only published review site in the post-1.0
list, not a backend. A hosted service changes the project's cost structure,
security surface, and governance obligations entirely, and the whole premise here
is that those are what make the incumbents expensive.
