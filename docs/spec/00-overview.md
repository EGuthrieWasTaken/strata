# 00 — Overview *(informative)*

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

From the origin document:

> You and a colleague have established your research question and described your
> inclusion/exclusion criteria. As you collect data, however, you realize that
> your initial list of criteria is incomplete. So, you update your list. This in
> turn requires an update to many or all of the subsequent steps. Without
> painstaking cross-referencing (e.g. in a spreadsheet) and meticulous scribing
> within a shared document, you may pollute your candidate literature pool with
> many papers which had already been previously filtered out, requiring you to
> start the process from the beginning.

Spreadsheets have no notion of *why* a cell changed, no notion of *which
version of the criteria* a decision was made under, and no safe way for two
people to edit the same rows. The usual recovery is to re-screen everything,
which is expensive enough that teams instead quietly do not update the criteria
— a methodological failure caused by a tooling failure.

## 2. The thesis

Git already solves versioning, attribution, branching, merging, and "what
changed and why". It does not solve them *for this domain*, because the domain
objects are not text files a researcher wants to edit by hand, and because the
interface is hostile to someone who does not already know it.

`epic` is therefore **a purpose-built front end to git for evidence synthesis**:

- The review lives in a git repository as plain, diffable text.
- Domain operations (`epic screen`, `epic dedup`, `epic analyze`) are the user
  interface; git is the storage engine and the audit log.
- Every operation that changes the review prompts for a one-line rationale and
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

## 3. Goals

**G1 — Nothing is lost.** Every decision, and the reason for it, is recoverable
forever. `epic why <record>` reconstructs the full provenance chain for any
record: which search found it, which duplicates it absorbed, who screened it,
under which version of the criteria, citing which criterion, with what stated
reason, in which commit.

**G2 — Changing your mind is cheap and safe.** When the protocol changes, `epic`
computes the minimal set of decisions that must be revisited, proves the rest
are still valid, and queues the work. Re-screening 180 records instead of 4,000
is the difference between updating your criteria and not.

**G3 — The funnel always reconciles.** The counts in the PRISMA flow diagram are
derived from the event log, never typed by a human. They cannot disagree with
the data, and the diagram is regenerated on demand.

**G4 — Collaboration without git literacy.** Two reviewers screening the same
2,000 records independently — which is the methodological *requirement*, not an
accident — must never produce a git merge conflict. Disagreements surface as a
domain-level adjudication queue, which is where they belong.

**G5 — Reproducible analysis.** Given the repository, `epic verify && epic
analyze` reproduces every number in the manuscript, byte for byte, on another
machine.

**G6 — Free, local, and yours.** No account, no server, no subscription, no
telemetry. The data is plain text on your disk under a licence nobody can
revoke.

## 4. Non-goals

**N1 — Not a literature search engine.** `epic` does not query EBSCO, Web of
Science, Scopus, or PubMed on your behalf in v1. Database licensing and
anti-automation terms make this a legal and operational minefield. `epic`
ingests the exports those platforms already produce (RIS, NBIB, BibTeX, CSV,
EndNote XML) and records the query string, platform, date, and hit count for
reproducibility. Optional, opt-in enrichment from *open* APIs (Crossref,
OpenAlex, PubMed E-utilities, Unpaywall) is in scope.

**N2 — Not a reference manager.** Zotero exists, is excellent, and is FOSS.
`epic` interoperates with it (CSL-JSON in both directions) rather than competing.

**N3 — Not a PDF repository.** Full-text PDFs are third-party copyrighted works.
`epic` tracks them by hash and path, and MUST NOT commit them by default.

**N4 — Not a statistics language.** `epic` implements the standard meta-analytic
toolkit well and correctly. It is not a substitute for R when you need a
Bayesian hierarchical network meta-analysis; it exports clean data so you can go
do that.

**N5 — Not an AI screening product (in v1).** Machine-assisted prioritisation is
a legitimate and well-studied accelerator, but it interacts badly with
auditability if bolted on carelessly. v1 defines the plugin boundary
(§[12](12-architecture.md)) and ships nothing behind it.

**N6 — Not a hosted service.** No multi-tenant backend is in scope. Sharing is
whatever git remote the team already has: GitHub, GitLab, Codeberg, a university
GitLab, or a bare repo on a shared drive.

## 5. Users

**Priya — doctoral student, first systematic review.** Has never used git. Will
use the local web UI for everything. Needs the tool to stop her from making
methodological mistakes and to produce a PRISMA diagram she can paste into her
thesis. Her success criterion: she never sees the word "rebase".

**Ethan — the review lead.** Comfortable in a terminal and an editor. Writes the
protocol, runs the searches, owns the analysis, and adjudicates screening
conflicts. Lives in `epic` at the CLI. Wants `git log` to be a real audit trail.

**Sam — the second screener.** A colleague or a paid RA, often at another
institution, contributing 20 hours to title/abstract screening and nothing else.
Must be productive within ten minutes of a one-line install, and must not be
able to corrupt the repository.

**Dr. Okafor — the methodologist / reviewer #2.** May never run the tool. Reads
the repository, or the generated report, and asks "how did you handle studies
with multiple effect sizes, and what happened when you changed criterion 3?"
The repository must answer both.

## 6. Prior art, and an honest correction to the premise *(informative)*

The origin document states that no FOSS alternative currently exists. That is
right about *integrated, end-to-end* platforms — the commercial field
(Covidence, DistillerSR, EPPI-Reviewer, Nested Knowledge) has no free-software
equivalent that spans protocol → screening → extraction → analysis → report.
But the individual stages are well served by free software, and the implementer
should reuse rather than rebuild:

| Stage | Existing FOSS / free tools | `epic`'s posture |
|---|---|---|
| Deduplication | ASySD, revtools (R) | Reimplement heuristics; validate against their published benchmarks |
| Screening | ASReview, Colandr, CADIMA, Abstrackr; Rayyan (freemium) | Rebuild — this is where provenance must live |
| Search strategy | litsearchr, CiteSource (R) | Interoperate; import their outputs |
| Analysis | **metafor**, meta, metaSEM, clubSandwich, dmetar (R) | Validate numerically against metafor; offer it as an optional engine |
| Risk of bias | robvis (R) | Reimplement plots; match its output conventions |
| PRISMA diagram | PRISMA2020 R package + Shiny app | Generate natively; export in that package's input format too |
| Reference management | Zotero | Interoperate via CSL-JSON |
| Reporting | RevMan (free, Cochrane-restricted, not open source) | Not a target |

The genuine, unfilled gap is not "an analysis engine" or "a screening UI". It is
**a provenance-first substrate that connects them**, so that a change in phase 1
propagates correctly and legibly to phases 4, 5, and 6. That is what this
specification builds. Everything else is in service of it.

The corollary for the implementer: where a mature FOSS tool already does a
sub-task well, `epic`'s job is to own the *record of the decision*, not
necessarily the computation. Validating against `metafor` is worth more than
inventing a new estimator.
