# 01 — Domain model *(normative)*

## 1. Why the distinctions matter

PRISMA counts three different things and calls them by three different names.
Conflating them is the single most common source of a flow diagram that does not
reconcile. `epic` models them separately and derives every count from the model.

```
   Search hit          Deduplicated       Document             Research
   from one DB         bibliographic      obtained and         study reported
                       entity             assessed             by >=1 document
  +-----------+       +-----------+      +-----------+        +-----------+
  |  Record   |--n:1->|  Record   |-1:1->|  Report   |--n:1-->|   Study   |
  | (raw row) |       |(canonical)|      |(full text)|        |           |
  +-----------+       +-----------+      +-----------+        +-----------+
                                                                    | 1:n
                                                                    v
                                                              +-----------+
                                                              |  Effect   |
                                                              +-----------+
```

- **Records identified** in the flow diagram = raw `Record`s across all imports.
- **Duplicates removed** = raw records absorbed into a canonical record.
- **Records screened** = canonical records entering title/abstract screening.
- **Reports sought for retrieval** = canonical records promoted to `Report`.
- **Reports assessed for eligibility** = reports whose full text was obtained.
- **Studies included** and **reports of included studies** are different numbers
  whenever one study is reported in more than one paper. `epic` MUST report both.

## 2. Entities

### 2.1 Record

A bibliographic entity. Created by import; one per row of a database export.
After deduplication, records are either **canonical** or **absorbed** (merged
into a canonical record, retained forever as an alias with its own provenance).

Identity: see §3. Schema: [03-schemas.md §2](03-schemas.md).

A record carries a **screening state** per stage, derived from the event log —
never stored as a mutable field.

### 2.2 Report

A retrievable document — usually a journal article PDF. A canonical record
becomes a report when it is promoted out of title/abstract screening. The report
tracks retrieval status (`sought`, `retrieved`, `not-retrieved` with reason), a
content hash of the local file, and the date and source of retrieval.

`epic` MUST NOT commit the file itself (see [13 §6](13-nonfunctional.md)).

### 2.3 Study

The unit of research. Created during full-text assessment by grouping one or
more reports. Most studies have exactly one report; a study with a protocol
paper, a primary outcomes paper, and a long-term follow-up has three. A single
report describing three independent experiments yields three studies, each
linked to that one report.

Studies are the unit of data extraction and the unit of clustering in analysis.

### 2.4 Effect

One effect estimate contributed by one study: an outcome, a contrast, a
timepoint, a subsample. A study MAY contribute many. Effects carry either
summary statistics from which an effect size is computed, or a pre-computed
effect size and variance, plus moderator values.

Multiple effects from one study are statistically dependent; see
[08 §5](08-analysis.md).

### 2.5 Criterion

One inclusion or exclusion rule, with a stable identifier, a short label, a
precise definition, and the stages at which it applies. Criteria are the axis
along which screening decisions are justified, and the axis along which
staleness is computed. See [06 §3](06-workflow-screening.md).

### 2.6 Search

One executed query against one database on one date: the platform, the exact
query string, field tags, applied limits, the number of hits, and the export
file(s) it produced. PRISMA item 7 requires this verbatim. `epic` MUST preserve
the query string byte-for-byte, including whitespace and line breaks.

### 2.7 Event

An immutable, append-only record of one decision or state change: a screening
decision, a dedup merge, an extraction edit, a retrieval outcome. Events are the
only authoritative mutable-state carrier in the repository. All views of "current
state" are folds over the event log. See [02 §4](02-repository-format.md).

### 2.8 Actor

A person contributing to the review, identified by a short stable handle
(`ethan`, `sam`) mapped to a display name, email, ORCID (optional), and role.
The handle — not the git author — is what events record, so that a reviewer who
changes institutions or email does not fragment their history.

## 3. Identity *(normative)*

Identifiers MUST be stable, collision-resistant, and — where possible —
**deterministic across independent imports of the same paper**. Determinism is
what lets two collaborators import the same Scopus export on different machines
and produce byte-identical files that merge without conflict.

### 3.1 Record identity

On import, compute a *canonical key* from the first available of:

| Priority | Source | Canonical key form |
|---|---|---|
| 1 | DOI | `doi:` + normalised DOI (§3.2) |
| 2 | PubMed ID | `pmid:` + digits |
| 3 | PMC ID | `pmcid:PMC` + digits |
| 4 | arXiv ID | `arxiv:` + normalised id |
| 5 | ISBN (books) | `isbn:` + digits, check digit normalised |
| 6 | Fallback | `sig:` + normalised title + `\|` + year + `\|` + normalised first-author family name |
| 7 | Last resort (no title) | `ulid:` + a fresh ULID |

Then:

```
record_id = "rec_" + base32_crockford(sha256(canonical_key)[0:10]).lower()   # 16 chars
```

Yielding e.g. `rec_3kq8v1r0zx2m4a7b`. Rationale for a truncated hash: 80 bits of
entropy gives a collision probability below 1e-12 at 10^6 records, ids stay
short enough to read aloud, and they are URL- and filename-safe.

Priority 7 (a random ULID) is the only non-deterministic branch and MUST emit a
warning naming the offending import row.

**Identifiers are permanent.** Correcting a record's DOI after import MUST NOT
change its id; it creates an alias instead (§3.3). The id is a name, not a
checksum.

### 3.2 Normalisation rules *(normative)*

These rules are used for identity, blocking, and similarity. They MUST be
implemented exactly as written — a change to them is a breaking format change,
and is governed by [02 §7](02-repository-format.md).

**DOI**: strip a leading `https://doi.org/`, `http://dx.doi.org/`, `doi:` or
`DOI:` (case-insensitive); strip surrounding whitespace and a single trailing
`.`, `,`, `;`, or `)`; lowercase. A value not matching `^10\.\d{4,9}/\S+$` is
not a DOI and MUST be ignored for identity purposes.

**Title**: decode HTML entities and strip inline markup (`<i>`, `<sub>`,
`&amp;`) first; Unicode NFKD normalise; strip combining marks (so `Über` becomes
`Uber`); lowercase; replace any run of characters that are not `[a-z0-9]` with a
single space; trim.

**Author family name**: as Title, but additionally strip particles (`van`,
`von`, `de`, `del`, `della`, `da`, `di`, `du`, `la`, `le`, `ter`, `ten`, `al`,
`bin`, `ibn`) when they appear as a leading token, retaining both the stripped
and unstripped forms as alternates for blocking.

**Year**: 4-digit integer. Where a record gives a range or a season, take the
first 4-digit number in `[1400, current_year + 2]`.

**Pages**: take the first integer run.

**Journal / container title**: as Title, plus expansion of a shipped
abbreviation table (`j` to `journal`, `psychol` to `psychology`, ...) applied to
whole tokens only.

### 3.3 Aliases

`records/aliases.ndjson` maps non-canonical ids to canonical ones:

```json
{"alias":"rec_9m2p0000000000ab","canonical":"rec_3kq8v1r0zx2m4a7b","reason":"dedup","event":"ev_01j9x7m2q4h8s0v3n5k1t6w2yb"}
```

Alias resolution MUST be transitive and MUST be cycle-checked at load; a cycle is
a hard error (`E_ALIAS_CYCLE`). Every id that has ever existed MUST resolve
forever, so that an old commit, an old export, or a collaborator's stale branch
still names something real.

### 3.4 Other identifiers

| Entity | Form | Assignment |
|---|---|---|
| Report | `rpt_` + the same 16 chars as its canonical record | derived |
| Study | `std_` + 16 chars, ULID-derived | assigned at creation, permanent |
| Effect | `eff_` + study suffix + `_` + 4-char sequence | assigned at creation |
| Criterion | `INC-nn` / `EXC-nn`, zero-padded, assigned in order, **never reused** | user-visible |
| Search | `S-nn` or a user-chosen slug (`S-embase-2026-03`) | user-visible |
| Import | `imp_` + ULID | assigned |
| Event | `ev_` + ULID (lowercase, 26 chars) | assigned |
| Analysis | user-chosen slug (`primary`, `sensitivity-rct-only`) | user-visible |

Criterion numbers MUST NOT be reused after a criterion is retired, because
historical events cite them.

## 4. Screening states *(normative)*

Per stage (`title-abstract`, `full-text`), a canonical record is in exactly one
state, derived from the fold (see [02 §4.3](02-repository-format.md)):

| State | Meaning |
|---|---|
| `unscreened` | No decision by any reviewer at this stage |
| `partial` | Some but not all assigned reviewers have decided |
| `conflict` | All assigned reviewers decided, and they disagree |
| `include` | Resolved: advances to the next stage |
| `exclude` | Resolved: leaves the pool, citing at least one criterion |
| `not-retrieved` | Full-text stage only: sought, could not be obtained |

`stale` is an **overlay**, not a seventh state: a stale record retains its prior
decision and cited criteria so that the flow diagram remains well defined while
re-screening is in progress. `epic status` MUST report both the resolved count
and the stale count, and `epic prisma` MUST refuse to emit a final diagram while
any record is stale unless `--allow-stale` is passed.

## 5. Stage graph

v1 defines a fixed two-screening-stage pipeline, because that is what PRISMA
describes and what the overwhelming majority of reviews do:

```
import -> dedup -> title-abstract -> [retrieval] -> full-text -> extraction -> analysis
```

The stage list MUST be read from configuration rather than hard-coded, so that an
added stage (a separate `tiab-pilot` calibration round, say, or a third
`data-availability` gate) is a config change rather than a schema migration. v1
ships the two stages above and MUST reject unknown stages in events.

## 6. Glossary

| Term | Definition |
|---|---|
| **Adjudication** | Resolving a screening `conflict`, by a third reviewer or by consensus |
| **Blocking** | Partitioning records into candidate groups so deduplication avoids O(n^2) comparison |
| **Canonical record** | The surviving record after duplicates are merged into it |
| **CHE** | Correlated-hierarchical-effects model for dependent effect sizes |
| **Dual screening** | Two reviewers independently screening the same records — the methodological default |
| **Fold** | Deterministic reduction of the event log to current state |
| **IRR** | Inter-rater reliability (Cohen's kappa, PABAK, percent agreement) |
| **Moderator** | A study-level variable hypothesised to explain heterogeneity |
| **PRISMA** | Preferred Reporting Items for Systematic Reviews and Meta-Analyses (2020 statement) |
| **RoB** | Risk of bias |
| **Staleness** | The property of a decision made under a version of the protocol that has since changed in a way that could alter it |
| **tau^2** | Between-study variance in a random-effects model |
