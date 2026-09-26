# strata — overview

*Informative.* What the system must do is specified in
[`openspec/`](../openspec/README.md); what is left to build is in the
[roadmap](roadmap.md); decisions still open are in
[open questions](open-questions.md).

## 1. The problem

A systematic review or meta-analysis proceeds in six broad phases:

1. **Frame the question.** Establish scope; identify moderators and covariates
   that may need to be controlled; write inclusion/exclusion criteria.
2. **Design the search.** Choose databases; write query strings per database.
3. **Execute the search.** Export the resulting mass of literature.
4. **Screen.** Filter the pool against the criteria from (1) to produce the
   final list of included studies.
5. **Extract and analyse.** Pull effect sizes and moderator values from each
   included study; pool them.
6. **Write it up.**

Two properties of this process are in tension with the tools normally used to
run it (a shared spreadsheet and a shared document, or a proprietary SaaS
platform):

**It is iterative, not linear.** Criteria are almost never right the first time.
You discover mid-screening that "adult sample" was never defined, or that you
need to exclude conference abstracts, or that a moderator you did not plan to
code turns out to explain most of the heterogeneity. Every such discovery
invalidates some — but crucially *not all* — of the work done so far.

**It must be auditable.** PRISMA 2020 requires you to report your search
strategies in full, the number of records at every stage of the funnel, the
reasons reports were excluded at full text, and any amendments to the registered
protocol. Six months later you must be able to answer "why is this paper not in
the review?" for any paper a reviewer names.

### The concrete failure mode

From the [origin document](origin/ProgramSpec.org):

> You and a colleague have established your research question and described your
> inclusion/exclusion criteria. As you collect data, however, you realize that
> your initial list of criteria is incomplete. So, you update your list. This in
> turn requires an update to many or all of the subsequent steps. Without
> painstaking cross-referencing (e.g. in a spreadsheet) and meticulous scribing
> within a shared document, you may pollute your candidate literature pool with
> many papers which had already been previously filtered out, requiring you to
> start the process from the beginning.

Spreadsheets have no notion of *why* a cell changed, no notion of *which version
of the criteria* a decision was made under, and no safe way for two people to
edit the same rows. The usual recovery is to re-screen everything, which is
expensive enough that teams instead quietly do not update the criteria — a
methodological failure caused by a tooling failure.

## 2. The thesis

Git already solves versioning, attribution, branching, merging, and "what
changed and why". It does not solve them *for this domain*, because the domain
objects are not text files a researcher wants to edit by hand, and because the
interface is hostile to someone who does not already know it.

`strata` is therefore **a purpose-built front end to git for evidence
synthesis**:

- The review lives in a git repository as plain, diffable text.
- Domain operations (`strata screen`, `strata dedup`, `strata analyze`) are the
  user interface; git is the storage engine and the audit log.
- Every operation that changes the review asks for a one-line rationale and
  writes it into a structured commit message.
- Because the tool knows the *semantics* of a change, it can compute the
  consequences of that change — above all, exactly which prior decisions a
  criteria edit invalidated, and which it did not.
- Because the history is structured, the PRISMA flow diagram, the protocol
  amendment log, and large parts of the Methods section are *generated*, not
  transcribed.

A researcher who never learns git still gets versioning, provenance, blame, and
conflict-free collaboration. A researcher who does know git gets a repository
they can inspect, branch, and review with ordinary tools.

The name follows from the architecture: sedimentary strata are layers laid down
in order, never rewritten, and readable afterwards as a record of what happened
and when.

## 3. Goals

**G1 — Nothing is lost.** Every decision, and the reason for it, is recoverable
forever. `strata why <record>` reconstructs the full provenance chain for any
record.

**G2 — Changing your mind is cheap and safe.** When the protocol changes,
`strata` computes the minimal set of decisions that must be revisited, proves the
rest are still valid, and queues the work. Re-screening 180 records instead of
4,000 is the difference between updating your criteria and not.

**G3 — The funnel always reconciles.** The counts in the PRISMA flow diagram are
derived from the event log, never typed by a human.

**G4 — Collaboration without git literacy.** Two reviewers screening the same
2,000 records independently — the methodological *requirement* — must never
produce a git merge conflict. Disagreements surface as a domain-level
adjudication queue. A collaborator who has never used git can work through a
browser, whether `strata` runs on their own machine or on a server the team
hosts.

**G5 — Reproducible analysis.** Given the repository, `strata verify && strata
analyze` reproduces every number in the manuscript, byte for byte, on another
machine.

**G6 — Free, and yours.** No subscription and no telemetry. Nothing requires an
account or a server: working alone, everything runs locally. A team that wants a
shared instance hosts one itself, and the review's data is always a plain-text
git repository the team controls and can clone out at any time, under a licence
nobody can revoke.

## 4. Deployment topologies

Git is always the backend. What varies is where the rest of the `strata` stack
runs:

| Topology | Where `strata` runs | Where the repository lives | Collaboration |
|---|---|---|---|
| **Solo** | The reviewer's machine (CLI, `strata serve`, or the container) | Local, optionally pushed to a remote for backup | — |
| **Local stacks, shared remote** | Each collaborator's machine | A shared git remote (GitHub, GitLab, Gitea, a bare repo on a shared drive) | Each commits locally and runs `strata sync`; merges are conflict-free by construction |
| **Hosted instance** | A server the team runs (usually the container image) | The instance's working copies, synced with a shared git remote | Collaborators sign in with their own credentials in a browser, like Overleaf; git-literate collaborators can still clone the remote and sync from a local stack |

The topologies mix freely because every one of them reads and writes the same
repository format and the same append-only, per-actor event files. The hosted
instance is a git client like any other. See the roadmap (M5.1) and the
`add-container-image` and `add-hosted-team-deployment` changes.

## 5. Non-goals

**N1 — Not a literature search engine.** `strata` does not query EBSCO, Web of
Science, Scopus, or PubMed on your behalf. Database licensing and
anti-automation terms make this a legal and operational minefield. `strata`
ingests the exports those platforms already produce and records the query
string, platform, date, and hit count for reproducibility. Optional, opt-in
enrichment from *open* APIs (Crossref, OpenAlex, PubMed E-utilities, Unpaywall)
is in scope.

**N2 — Not a reference manager.** Zotero exists, is excellent, and is FOSS.
`strata` interoperates with it: **Zotero owns the documents and `strata` owns
the decisions**.

**N3 — Not a PDF repository.** Full-text PDFs are third-party copyrighted works.
`strata` tracks them by identifier and never commits them by default.

**N4 — Not a statistics language.** `strata` implements the standard
meta-analytic toolkit well and correctly. It exports clean data for anything
beyond that.

**N5 — Not an AI screening product (in v1).** Machine-assisted prioritisation is
a legitimate accelerator, but it interacts badly with auditability if bolted on
carelessly. The plugin boundary (`openspec:architecture#plugin-boundaries`) is
defined; nothing ships behind it.

**N6 — Not a service the project operates.** `strata` is self-hostable
software, not a SaaS. The project will not run a multi-tenant service holding
other people's reviews; a team that wants a shared instance runs one on
infrastructure it controls, and git remains the source of truth.

## 6. Users

**Priya — doctoral student, first systematic review.** Has never used git. Will
use the web UI for everything — locally, or on her lab's hosted instance. Needs
the tool to stop her from making methodological mistakes and to produce a PRISMA
diagram she can paste into her thesis. Her success criterion: she never sees the
word "rebase".

**Ethan — the review lead.** Comfortable in a terminal and an editor. Writes the
protocol, runs the searches, owns the analysis, and adjudicates screening
conflicts. Lives in `strata` at the CLI. Wants `git log` to be a real audit
trail.

**Sam — the second screener.** A colleague or a paid RA, often at another
institution, contributing 20 hours to title/abstract screening and nothing else.
Must be productive within ten minutes — ideally by opening a link and signing
in — and must not be able to corrupt the repository.

**Dr. Okafor — the methodologist / reviewer #2.** May never run the tool. Reads
the repository, or the generated report, and asks "how did you handle studies
with multiple effect sizes, and what happened when you changed criterion 3?" The
repository must answer both.

## 7. Prior art, and an honest correction to the premise

The origin document states that no FOSS alternative currently exists. That is
right about *integrated, end-to-end* platforms — Covidence, DistillerSR,
EPPI-Reviewer, and Nested Knowledge have no free-software equivalent spanning
protocol → screening → extraction → analysis → report. But the individual stages
are well served by free software, and `strata` should reuse rather than rebuild:

| Stage | Existing FOSS / free tools | `strata`'s posture |
|---|---|---|
| Deduplication | ASySD, revtools (R) | Reimplement heuristics; validate against their published benchmarks |
| Screening | ASReview, Colandr, CADIMA, Abstrackr; Rayyan (freemium) | Rebuild — this is where provenance must live |
| Search strategy | litsearchr, CiteSource (R) | Interoperate; import their outputs |
| Analysis | **metafor**, meta, metaSEM, clubSandwich, dmetar (R) | Validate numerically against metafor; offer it as an optional engine |
| Risk of bias | robvis (R) | Reimplement plots; match its output conventions |
| PRISMA diagram | PRISMA2020 R package + Shiny app | Generate natively; export in that package's input format too |
| Reference management | Zotero | Interoperate via CSL-JSON |
| Collaborative hosting | Overleaf (for LaTeX), Gitea/GitLab (for code) | The model for a self-hosted instance with a git backend |

The genuine, unfilled gap is **a provenance-first substrate that connects them**,
so that a change in phase 1 propagates correctly and legibly to phases 4, 5, and
6. Where a mature FOSS tool already does a sub-task well, `strata`'s job is to
own the *record of the decision*, not necessarily the computation.
