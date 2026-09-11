# epic

**A free, version-controlled workbench for systematic reviews and meta-analyses.**

Meta-analysis software today is dominated by closed-source, subscription-priced
products. `epic` is a FOSS alternative built on a simple premise: a systematic
review is a *series of reasoned decisions about a body of literature*, and the
best tool humanity has for tracking reasoned decisions over a shared artifact is
`git`.

`epic` is a purpose-built front end to git for evidence synthesis. It stores the
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

`epic` answers those four questions mechanically.

---

## Status

**Specification stage. No implementation yet.**

The complete design lives in [`docs/spec/`](docs/spec/README.md). It is written
to be executable by an implementer (human or agent) without further design work.

Start with:

1. [Overview, goals and non-goals](docs/spec/00-overview.md)
2. [Domain model](docs/spec/01-domain-model.md)
3. [Repository format](docs/spec/02-repository-format.md) — the normative core
4. [Roadmap and milestones](docs/spec/15-roadmap.md) — the build order

The original problem statement that seeded this project is preserved verbatim at
[`docs/origin/ProgramSpec.org`](docs/origin/ProgramSpec.org).

## License

GNU General Public License v3.0 or later. See [`LICENSE`](LICENSE).
