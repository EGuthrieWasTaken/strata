# Glossary

**Actor.** A person who records something in a review, identified by a lowercase handle (`ada`). Everything in
the log carries its actor.

**Adjudication.** Settling a screening conflict. Requires a rationale and an authorised adjudicator. See
[Adjudication and agreement](Adjudication-and-Agreement).

**Amendment.** A change to the eligibility criteria after screening began. Reported automatically (PRISMA 24c).

**Blinding.** Not showing a reviewer their colleague's decisions while they screen. See
[Blinding and independence](Blinding-and-Independence).

**Canonical record.** The record that survives when duplicates are merged. The others are *absorbed* (kept, but
not counted).

**Commit.** One saved, labelled snapshot of the review. `strata` makes them for you, with your `--why`.

**Conflict.** A record whose screening opinions disagree, or include a "maybe". Goes to adjudication.

**Criteria version.** The number of the current set of eligibility criteria; every change increases it.

**Derived (view).** A file computed from the log (`derived/`, `reports/`, `analysis/results/`). Regenerated,
never edited.

**Direction.** How an edit to a criterion moves the included pool: *tightened*, *loosened*, *both* or
*editorial*. See [Criteria versions and direction](Criteria-Versions-and-Direction).

**Effect (effect size).** A number summarising a study's result for one outcome, with its variance (`yi`, `vi`).

**Event.** One line in the append-only log: an import, a decision, a retrieval outcome...

**Guardrail.** A named warning about a fragile analysis (`k-lt-5`, ...). Acknowledged with `--ack`; some are
blocking. See [Analysis](Analysis).

**Hash chain.** The way event files are protected: each entry carries a digest of the one before, so any
alteration is detectable.

**Moderator.** A study or effect characteristic you test as a source of heterogeneity (age group, retention
interval).

**Pool.** The set of canonical records and their screening state (`derived/pool.tsv`).

**Provenance.** Where a record or value came from: the search, the import, the merge, the correction. `strata
why REC_ID` shows it.

**Rationale (`--why`).** The reason you give for a change. Stored in the history.

**Record.** One bibliographic reference (`rec_...`).

**Remote.** A copy of the review on a server, for sharing. See [Git for reviewers](Git-for-Reviewers).

**Report.** One document (`rpt_...`): a paper, preprint or abstract. A **study** (`std_...`) may have several
reports.

**Stage.** A step of screening: `title-abstract` or `full-text`.

**Stale.** A past decision that a later change to the criteria might have invalidated. See [Staleness](Staleness).

**Study.** The unit of analysis: a set of reports describing the same participants. See
[Grouping reports into studies](Grouping-Reports-into-Studies).

**Sync.** `strata sync`: bring in others' work, check it, and send yours. See [Working with others](Working-with-Others).
