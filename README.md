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

**M0 (substrate), M1 ("literature in"), and M2 ("screening and staleness")
are complete — this is the first genuinely useful release.** The
pull-request gate, the repository format's core (event log, canonical
serialisation, identity and normalisation, the fold), and
`init`/`clone`/`doctor`/`config`/`actor`/`verify`/`status`/`log` are
implemented and tested. Recording searches (`strata search add`/`list`) and
importing literature (`strata import`, with CSL-JSON/RIS/BibTeX/PubMed-MEDLINE/
CSV-TSV parsers and detection profiles for six major database platforms) both
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
session sustains sub-100ms decision latency at 50,000 records. Extraction
(M3) and analysis (M4) are not built yet; see [the roadmap](docs/spec/15-roadmap.md)
for what comes next, and [`docs/m1-plan.md`](docs/m1-plan.md) /
[`docs/m2-plan.md`](docs/m2-plan.md) for the sub-objective-by-sub-objective
status of each milestone.

## Installing

`strata` isn't packaged for PyPI/Homebrew/conda-forge yet (that's tracked in
[M6](docs/spec/15-roadmap.md#m6--hardening-and-adoption-ongoing)); for now,
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

## Getting started

Every mutating command records *why*, not just *what* — via `--why`, a
`--why-file`, or an interactive prompt — because that rationale is what
makes the repository's history worth reading later. A full walkthrough:

```
# Start a repository for the review.
strata init my-review --title "My systematic review" --actor you --actor-name "Your Name"
cd my-review

# Record a search before importing its results (docs/spec/05).
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

The complete design lives in [`docs/spec/`](docs/spec/README.md). It is written
to be executable by an implementer (human or agent) without further design work.

Start with:

1. [Overview, goals and non-goals](docs/spec/00-overview.md)
2. [Domain model](docs/spec/01-domain-model.md)
3. [Repository format](docs/spec/02-repository-format.md) — the normative core
4. [Screening and staleness](docs/spec/06-workflow-screening.md) — the flagship
   feature, implemented in M2
5. [The web UI](docs/spec/11-web-ui.md) — `strata serve`
6. [Testing and CI](docs/spec/14-testing.md) — the pull-request gate, which is
   the first thing to build
7. [Roadmap and milestones](docs/spec/15-roadmap.md) — the build order

The original problem statement that seeded this project is preserved verbatim at
[`docs/origin/ProgramSpec.org`](docs/origin/ProgramSpec.org).

## License

GNU General Public License v3.0 or later. See [`LICENSE`](LICENSE).
