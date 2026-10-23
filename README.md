# strata

**A free, version-controlled workbench for systematic reviews and meta-analyses.**

Meta-analysis software today is dominated by closed-source, subscription-priced
products. `strata` is a FOSS alternative built on a simple premise: a systematic
review is a *series of reasoned decisions about a body of literature*, and the
best tool humanity has for tracking reasoned decisions over a shared artifact is
`git`.

`strata` is a purpose-built front end to git for evidence synthesis. It stores the
entire review — protocol, search strategies, records, screening decisions,
extracted data, and analyses — as plain text in a git repository, and it wraps
git so that a reviewer who has never typed `git commit` gets full versioning,
provenance, and collaboration for free.

The problem it exists to solve:

> You and a colleague agree on your inclusion criteria and start screening.
> Halfway through, you realize criterion 3 was underspecified. You change it.
> Now: which of your 4,000 screening decisions are still valid? Which papers
> silently re-enter the candidate pool? What did this do to your pooled effect
> size? And how do you explain all of it in the manuscript six months later?

`strata` answers those four questions mechanically.

## The name

Sedimentary strata are layers laid down in order, never rewritten, and readable
afterwards as a record of what happened and when. That is what this tool makes
of a systematic review: an append-only log of decisions, a versioned protocol,
and a history in which every layer stays legible — including the ones you would
rather have quietly rewritten.

---

## Status

**M0 (substrate), M1 ("literature in"), M2 ("screening and staleness"), and
M3 ("full text and extraction") are complete, and M4 ("analysis") and M5
("reporting") are implemented apart from the open items named below.** The
pull-request gate, the repository format's core (event log, canonical
serialisation, identity and normalisation, the fold), and
`init`/`clone`/`doctor`/`config`/`actor`/`verify`/`status`/`log` are
implemented and tested. Recording searches (`strata search add`/`list`) and
importing literature (`strata import`, with CSL-JSON/RIS/BibTeX/PubMed-MEDLINE/
EndNote-XML/Excel/CSV-TSV/plain-text citation-list parsers and detection profiles for six major database platforms) both
work end to end, including idempotent re-import and full provenance, and hold
up against a `hypothesis`-driven fuzz corpus. Deduplication (`strata dedup`)
is implemented end to end: blocking, scoring, thresholds, auto-merge, an
interactive review queue, merge semantics, and `--undo`, validated against a
labelled benchmark (recall 1.000, false-merge rate 0.0000 against the v1
targets — see
[`docs/dedup-benchmark-results.md`](docs/dedup-benchmark-results.md)).
`strata records list|show`, `strata why`, and `strata fix` are implemented,
including the `--filter` expression language shared with the web UI. A
50,000-record import completes in ~20s and a 50,000-record dedup pass in
~126s (single-threaded, well inside the M1 roadmap's acceptance targets).

M2 adds the flagship feature: criteria management with direction
classification (`strata criteria add|edit|retire|list|diff`), the staleness
engine (change a criterion mid-review and `strata rescreen` finds exactly
the decisions it invalidates, with the reason), title-abstract/full-text
screening (`strata screen`), dual review with blinding, adjudication of
disagreements (`strata adjudicate`), inter-rater reliability (`strata irr`),
criterion-citation audit sampling (`strata audit`), and a local, no-login
web UI (`strata serve`) covering the dashboard, screening, criteria editing
with a live non-mutating impact preview, rescreening, adjudication, the
duplicate review queue, a searchable record table, and domain history — all
server-rendered and fully usable with JavaScript disabled. A screening
session sustains sub-100ms decision latency at 50,000 records.

M3 takes a review from included records to an analysis-ready dataset. A
retrieval queue (`strata retrieve`) records each full text by identifier and
version in a committed manifest, with the reason for every report that could not
be obtained and, if you opt in, legal open-access links from Unpaywall.
`strata studies` groups reports into studies and splits multi-study reports,
suggesting but never applying. `strata extract` drafts a coding form from the
protocol, walks each study (units converted, a source locator after any value,
effects entered in whatever form the paper reports with the effect size shown as
you type), warns about implausible values without blocking, and — with dual
extraction — reconciles two reviewers field by field with a recorded rationale.
`strata rob` records risk of bias (RoB 2 with algorithmic suggestions and
recorded overrides, ROBINS-I, Newcastle-Ottawa, or your own instrument), and
`strata export effects` writes one row per effect for `metafor::rma()` or any
other tool. All of it is also in the web UI.

M4 pools the extracted effects. An analysis is a versioned file,
`analysis/<id>.yaml`, and `strata analyze` turns it into committed results
(`estimates.json`, `studies.tsv`, a plain-language `summary.md`, deterministic
SVG forest, funnel, Baujat and bubble plots, and a `run.json` that records the
exact inputs) — never as a side effect of another command. The native engine
covers the standardised mean difference, mean difference, log odds and risk
ratios, risk difference, Fisher's z, log hazard ratios, proportions and pre-post
change; common-effect and random-effects models with eight `tau^2` estimators,
Knapp–Hartung intervals, prediction intervals and meta-regression; effects that
share a study handled by aggregation, a multilevel model or cluster-robust
errors; small-study tests, trim-and-fill and PET-PEESE as labelled sensitivity
analyses; and leave-one-out, influence and cumulative analyses. Every estimator
is compared with `metafor` (and `clubSandwich`) to 1e-8 on committed fixtures,
and a model that cannot be computed correctly is absent rather than
approximated. Fourteen named guardrails (for example, publication-bias tests
with fewer than ten studies are blocked unless you pass `--force`) are recorded
in `run.json`. `strata diff v1-protocol..HEAD` shows a pooled estimate moving
when a protocol change moves the pool, and `strata status` and `strata verify`
say when committed results are stale. One item is open: the Hedges & Olkin
worked example could not be reproduced because its tables were not available;
see [`docs/m4-plan.md`](docs/m4-plan.md).

M5 turns the repository into the reporting a review owes its readers. Every
PRISMA 2020 count is derived from the event log with its reconciliation
identities asserted (`derived/counts.json`; a count that does not close is
`E_COUNT_RECONCILE`, naming the identity), and `strata prisma` draws the flow
diagram from them in SVG, PDF, PNG or JSON (including the input shape of the
`PRISMA2020` R package), in one column or with the records found by other
methods in a second, watermarked DRAFT while screening is unfinished or any
decision is stale. `strata report checklist` fills in the 27-item checklist where
the repository knows the answer, says where it holds the material, and names what
only the author can write (certainty of evidence and the discussion among them).
`strata report methods|results|characteristics|amendments|rob|manuscript`
drafts those sections from the repository under strict rules (marked with the
commit, numbers only from the results, no causal or significance language, the
caveat of every guardrail that fired, and never a Discussion or Conclusion);
the amendments section reports each change to the eligibility criteria after
screening began with what it invalidated and what became of it. `strata export
bibliography` lists the included, excluded-at-full-text, screened or
not-retrieved records as BibTeX, CSL-JSON or RIS, and `strata export package`
builds the supplement PRISMA item 27 asks for with no full text in it. Two items
are open: the checklist wording has not been compared with the official
template, and a methodologist has not yet read the generated Methods; see
[`docs/m5-plan.md`](docs/m5-plan.md).

See [the roadmap](docs/roadmap.md) for what comes next, and
[`docs/m1-plan.md`](docs/m1-plan.md) / [`docs/m2-plan.md`](docs/m2-plan.md) /
[`docs/m3-plan.md`](docs/m3-plan.md) / [`docs/m4-plan.md`](docs/m4-plan.md) /
[`docs/m5-plan.md`](docs/m5-plan.md) /
[`docs/m5-1-plan.md`](docs/m5-1-plan.md) /
[`docs/m6-plan.md`](docs/m6-plan.md) for
the sub-objective-by-sub-objective status of each milestone, including what is
deliberately partial. Reference pages: [statistical methods](docs/statistics.md) (formulae and
sources), [recovery](docs/recovery.md) (when something looks wrong), [for people who have never used git](docs/never-used-git.md),
[methods-text cookbook](docs/methods-cookbook.md), [running in a container](docs/container.md), and [contributing](CONTRIBUTING.md) (including
how to add an import parser).

## Installing

`strata` isn't packaged for PyPI/Homebrew/conda-forge yet (that's tracked in
[M6](docs/roadmap.md#m6--hardening-and-adoption-ongoing)); for now,
run it from a checkout with [`uv`](https://docs.astral.sh/uv/). You'll need
Python 3.11+ and `git`.

```
git clone https://github.com/EGuthrieWasTaken/strata.git
cd strata
uv sync
uv run strata --help
```

Or, to get a `strata` command on your `PATH` without keeping the checkout
around:

```
uv tool install git+https://github.com/EGuthrieWasTaken/strata.git
strata --help
```

(Every example below assumes the latter; swap in `uv run strata` if you're
running from a checkout instead.)

Or, without installing Python at all, in a container (see
[`docs/container.md`](docs/container.md); no image is published yet, so build it from the checkout
with `docker build -t strata .`):

```
docker run --rm --user "$(id -u):$(id -g)" -v "$PWD":/review strata status
```

## Getting started

Every mutating command records *why*, not just *what* — via `--why`, a
`--why-file`, or an interactive prompt — because that rationale is what
makes the repository's history worth reading later. A full walkthrough:

```
# Start a repository for the review.
strata init my-review --title "My systematic review" --actor you --actor-name "Your Name"
cd my-review

# Record a search before importing its results.
strata --why "recording the search before import" search add \
    --database MEDLINE --platform Ovid --by you --query "1 exp Learning/"
strata --why "first import" import my-export.ris --by you --search S-01-medline

# Find and resolve duplicates.
strata dedup --by you --review

# Define your inclusion/exclusion criteria, then screen.
strata criteria add --kind exclusion --label "Not empirical" \
    --definition "Not an original empirical study." \
    --applies-at title-abstract --by you
strata screen title-abstract --by you

# See where things stand at any point.
strata status

# Or drive the whole thing from a browser instead of the terminal --
# same repository, same commits, no server-side account or database.
strata serve
```

If you loosen, tighten, or retire a criterion mid-review, `strata rescreen`
tells you exactly which prior decisions are now stale and why; disagreements
between reviewers surface in `strata adjudicate`; `strata irr` reports
inter-rater agreement; `strata audit --criteria` spot-checks cited criteria
against a random sample. Every command's `--help` includes a worked example,
and `strata log` / `strata why <id>` reconstruct the full reasoning behind
any decision after the fact.

## Specification

What `strata` must do is specified with [OpenSpec](openspec/README.md):
[`openspec/specs/`](openspec/specs/) holds one spec per capability — the
requirements, each with WHEN/THEN scenarios, for everything that has shipped —
and [`openspec/changes/`](openspec/changes/) holds the remaining roadmap
milestones (M3 onwards) as change proposals. Behaviour changes are proposed
there first; `openspec validate --all --strict` runs on every pull request.

Each capability has a `spec.md` (the requirements) and a `design.md` (the
reasoning, worked examples, and rejected alternatives). Start with:

1. [Overview](docs/overview.md) — the problem, goals, non-goals, and the
   deployment topologies (solo, shared git remote, hosted instance)
2. [Domain model](openspec/specs/domain-model/spec.md)
3. [Repository format](openspec/specs/repository-format/spec.md) and
   [event log](openspec/specs/event-log/spec.md) — the normative core
4. [Staleness](openspec/specs/staleness/spec.md) and its
   [design](openspec/specs/staleness/design.md) — the flagship feature
5. [The web UI](openspec/specs/web-ui/spec.md) — `strata serve`
6. [The CI gate](openspec/specs/ci-gate/spec.md) and
   [test suite](openspec/specs/test-suite/spec.md)
7. [Roadmap](docs/roadmap.md) and [open questions](docs/open-questions.md)

The original problem statement that seeded this project is preserved verbatim at
[`docs/origin/ProgramSpec.org`](docs/origin/ProgramSpec.org).

## License

GNU General Public License v3.0 or later. See [`LICENSE`](LICENSE).
