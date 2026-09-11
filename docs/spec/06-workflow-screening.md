# 06 — Screening and the staleness engine *(normative)*

This is the feature the project exists for. Everything else in `strata` is
competent infrastructure; §4–§6 are the part no other tool does.

## 1. Screening stages

Two stages by default:

**Title/abstract.** High volume (thousands of records), low information (title,
abstract, keywords). Optimised for speed: the reviewer should average 10–20
seconds per record. Over-inclusion is the correct bias — a false exclusion here
is invisible and unrecoverable, a false inclusion costs one full-text retrieval.

**Full text.** Low volume (tens to hundreds), high information. Slower, and
exclusions MUST cite a criterion because PRISMA requires reporting exclusions
with reasons at this stage.

## 2. Dual independent screening

The methodological default (`screening.mode = "dual"`) is that two reviewers
screen every record independently, without seeing each other's decisions, and
disagreements are adjudicated.

- `blind_reviewers: true` (default) — the UI MUST NOT reveal another reviewer's
  decision before the current reviewer commits their own. This is not a
  cosmetic setting: a reviewer who can see their colleague's judgement is not an
  independent rater, and the review's reported inter-rater reliability becomes a
  fiction.
- Independence is enforced by data layout, not just UI: each reviewer's events
  live in their own file, so the blinding survives a user poking around in the
  repository — they would have to deliberately open someone else's file.
- IRR is computed over **first opinions only** ([02 §6.5](02-repository-format.md)).

`single` mode is supported for pilot and scoping work, and `strata report` MUST
state plainly in generated Methods text that screening was performed by a single
reviewer, since that is a limitation reviewers will ask about.

## 3. Criteria

### 3.1 Editing criteria

```
$ strata criteria add --kind exclusion --label "Mean sample age under 18"
$ strata criteria edit EXC-03
$ strata criteria retire INC-05
$ strata criteria list --at full-text
```

Any change to the active criteria set increments `criteria.version` by one,
recomputes digests, and emits a `criteria-change` event carrying the deltas.

### 3.2 Declaring the direction of a change *(normative)*

When a criterion's `definition` changes, `strata` MUST ask the user to classify the
change, because the classification determines how much work becomes stale and the
tool cannot reliably infer it from text:

```
  You edited EXC-03.

    was:  Publications not written in English.
    now:  Publications not written in English, and publications in English
          translation where the original instrument was not validated in
          the translated language.

  How does this change the set of papers the criterion excludes?

    [t] Tightened  - it now excludes MORE papers than before
    [l] Loosened   - it now excludes FEWER papers than before
    [b] Both       - some in, some out (or you are not sure)
    [e] Editorial  - wording only; the same papers are affected
```

| Direction | Meaning | Semantics |
|---|---|---|
| `tightened` | For an exclusion criterion, excludes more; for an inclusion criterion, includes fewer. In both cases: **the included pool can only shrink** | May invalidate prior inclusions |
| `loosened` | The included pool can only grow | May invalidate prior exclusions citing it |
| `both` | Unknown or genuinely bidirectional | Invalidates both directions |
| `editorial` | No semantic change | Invalidates nothing; per-criterion digest is unchanged by construction, so `strata` MUST verify the claim by checking that only `label`/`examples`/whitespace changed, and MUST refuse `editorial` if the `definition` text changed in any other way |

The `editorial` guard matters: it is the one option that lets a user assert
"nothing to redo", and it is therefore the one a rushed user will reach for. `strata`
MUST NOT accept the assertion on trust. If the definition's meaning-bearing text
changed, the honest options are `tightened`, `loosened`, or `both`, and `both` is
always safe.

A criterion **added** behaves as `tightened`. A criterion **retired** behaves as
`loosened`.

## 4. The staleness rules *(normative)*

### 4.1 What a decision binds to

Every `screen` and `adjudicate` event records `criteria_version`, the set
`criteria_digest`, and the specific `criteria[]` cited. A decision is therefore
always interpretable against the exact rules in force when it was made.

### 4.2 The rules

Let a resolved decision `D` at stage `S` have been made at criteria version
`v_D`, citing criteria set `C_D`. Let the current version be `v_now`, and let
`Δ` be the set of criterion changes between `v_D` and `v_now` that apply at
stage `S`.

```
D is STALE if and only if:

  D.decision == "include"  and  ∃ c ∈ Δ with direction ∈ {tightened, both}

  D.decision == "exclude"  and  ∃ c ∈ Δ ∩ C_D with direction ∈ {loosened, both, retired}

  D.decision == "maybe"    and  Δ ≠ ∅ (any non-editorial change)
```

Everything else remains valid.

### 4.3 Why this is sound *(informative, but the reasoning is load-bearing)*

The rules are asymmetric, and the asymmetry is the whole economic argument for
the tool.

**Exclusions are robust to tightening.** A record was excluded because it met
some exclusion criterion `c` (or failed some inclusion criterion). If `c` is
unchanged, the record still meets `c`, so it is still excluded — regardless of
how many *new* criteria were added, because adding grounds for exclusion cannot
rescue a paper that already has one. This is why adding a criterion mid-review
does not force re-screening the thousands of records already excluded. In a
typical review that is 85–95% of the screening effort, preserved.

**Inclusions are robust to loosening.** A record was included because it met all
inclusion criteria and no exclusion criterion. Loosening or retiring a criterion
cannot create a new reason to exclude it, so it stays included.

**The dangerous directions are the ones the rules catch.** Tightening creates new
grounds to exclude, so every current inclusion must be re-examined. Loosening
removes grounds, so every exclusion that *relied on* the changed criterion must
be re-examined — but only those. An exclusion citing `EXC-02` is unaffected by a
change to `EXC-03`.

**The assumption this rests on.** The exclusion rule assumes a cited criterion
genuinely applied to the record. This holds under normal "exclude at first
matching criterion" practice, which is what the UI encourages: a reviewer need
not enumerate every applicable criterion, because one valid ground is sufficient
to exclude. The rule does *not* assume the citation is exhaustive.

**The residual risk, stated plainly.** If a reviewer cites a criterion
carelessly — excludes a rodent study but clicks `EXC-05 (wrong outcome)` instead
of `EXC-02 (animal model)` — then retiring `EXC-05` will correctly flag the
record as stale (no harm), but retiring `EXC-02` will *not* flag it, and the
record stays excluded on a ground that no longer exists. The mitigations are:
`strata` MUST support citing multiple criteria on one exclusion and MUST make it
one keystroke each; the UI MUST show the criterion's full definition on hover or
focus, not just its label; and `strata audit --criteria` MUST offer a sampling
workflow that re-presents a random subset of past exclusions for verification.
The tool cannot fully protect against a miscited reason, and the documentation
MUST say so rather than implying a guarantee it cannot make.

### 4.4 Staleness is transitive across stages

A record whose title/abstract decision becomes stale and is then *excluded* on
re-screening leaves the pool, which invalidates any downstream full-text
decision, extraction, and analysis participation. `strata` MUST:

- Cascade staleness forward: a stale `include` at title/abstract marks the
  dependent full-text decision stale as well.
- Never silently delete downstream work. An extraction for a study whose record
  was later excluded is retained, marked `orphaned`, and reported — because the
  user may well change their mind back, and because deleting a colleague's four
  hours of coding without asking is unacceptable.

## 5. Staleness causes

`derived/stale.tsv` records one of these in its `reason` column:

| Reason | Trigger |
|---|---|
| `criterion-added` | A new criterion applies at this stage and this record was included |
| `criterion-tightened` | A cited-or-not criterion was tightened and this record was included |
| `criterion-loosened` | A criterion this exclusion cited was loosened |
| `criterion-retired` | A criterion this exclusion cited was retired |
| `criterion-both` | A bidirectional change |
| `maybe-any-change` | The decision was `maybe` and anything changed |
| `upstream-stale` | A prior-stage decision for this record is stale (§4.4) |
| `manual` | A user explicitly invalidated it with `strata rescreen --mark <records>` |

## 6. The re-screening workflow

```
$ strata status

  Criteria v4 (changed 2026-03-19: EXC-07 added, EXC-03 tightened)

  Title/abstract          4,182 records
    resolved                4,002   (3,798 exclude, 204 include)
    unscreened                  0
    conflicts                  14   -> strata adjudicate
    STALE                     180   -> strata rescreen
                                       138 included, now that EXC-07 applies
                                        42 excluded citing EXC-03, now loosened

  Full text                 204 reports
    resolved                  196
    not retrieved               8
    STALE                      21   (upstream-stale)

  Estimated re-screening effort: ~55 minutes at your recent pace (18s/record)
```

`strata rescreen` opens the stale queue in the screening UI, showing each record
*with its prior decision and reason visible* — the reviewer is re-deciding, not
deciding fresh, and hiding the prior judgement would waste their earlier
thinking and destroy consistency. The prior decision is displayed, clearly marked
as prior, with the change that invalidated it:

```
  Record 3 of 180                                    STALE: criterion-added

  Spacing effects in learning: A temporal ridgeline of optimal retention
  Cepeda, Vul, Rohrer, Wixted & Pashler (2008), Psychological Science

  [abstract ...]

  Your previous decision (2026-03-07, criteria v3):  INCLUDE
  Now stale because:  EXC-07 "Mean sample age under 18" was added,
                      and it applies at title-abstract.

  [i] include   [e] exclude   [m] maybe   [k] keep previous decision   [?] why
```

`[k]` (keep) is a first-class action: it appends a fresh `screen` event with the
same decision at the new criteria version, which clears staleness and records
that a human actually re-considered it. It is *not* a bulk no-op — `strata` MUST
NOT offer "mark all stale decisions as still valid" without an explicit
`--i-have-reviewed-these` flag and a rationale, because that flag is the one
place where the tool's integrity guarantee could be quietly hollowed out.

## 7. The screening UI contract

Whether CLI or web ([11](11-web-ui.md)), the screening surface MUST provide:

| Requirement | Detail |
|---|---|
| Keyboard-first | Every action reachable without a pointer; `i`/`e`/`m` decide, `u` undoes, digits `1`–`9` cite criteria, `n`/`p` navigate, `?` shows help |
| Sub-100 ms response | A decision must feel instant; persistence is async but crash-safe (append then fsync per batch of 10, or on idle) |
| Undo | `u` reverts the last decision within the session by appending a correcting event |
| Criterion definitions visible | Full definition on focus, not just the label |
| Configurable highlighting | User-defined terms highlighted in title and abstract |
| Progress and pace | Records done, remaining, current rate, estimated finish |
| Blinding | Honour `blind_reviewers` and `blind_metadata` |
| Resumability | Closing and reopening resumes at the same record |
| No dead ends | Records with no abstract are flagged, not silently skipped |

Full-text screening additionally MUST offer opening the local PDF and MUST
require at least one criterion on exclusion.

## 8. Adjudication

```
$ strata adjudicate

  Conflict 3 of 14                                    title-abstract

  Retrieval practice and the testing effect in medical education
  Larsen, Butler & Roediger (2009), Medical Education

  [abstract ...]

  ethan   INCLUDE   2026-03-07   "looks like an RCT with a delayed test"
  sam     EXCLUDE   2026-03-08   EXC-04 (wrong population)
                                 "medical residents, not undergraduates"

  [i] include   [e] exclude   [d] discuss (add a note, leave open)   [s] skip
```

- Only actors with the `adjudicator` role or listed in `screening.adjudicators`
  may resolve a conflict.
- The adjudication event supersedes both opinions but does not erase them; IRR
  still reflects the original disagreement, which is the honest number.
- A rationale is REQUIRED for adjudications — this is exactly the decision a
  peer reviewer will question.
- Adjudicating without having screened the record oneself is allowed and is the
  common case (the lead adjudicates). Adjudicating one's *own* conflict is
  allowed but MUST be noted in the event, and `strata report` MUST count it.
- `[d]` records a `note` event and leaves the conflict open, for the "let's
  discuss at the Tuesday meeting" case.

## 9. Worked example: the origin scenario *(informative)*

This is the scenario from the project's origin document, executed end to end. It
is also acceptance test `E2E-01` ([14 §5](14-testing.md)).

```
# Day 1 -- set up, search, import, screen
$ strata init --title "Spaced retrieval and long-term retention"
$ strata criteria add ...                      # 6 criteria, version 1
$ strata search add S-01-medline               # records the Ovid query verbatim
$ strata import medline.nbib --search S-01-medline     # 4,182 records
$ strata import embase.ris   --search S-02-embase      # 3,100 records
$ strata dedup                                 # 2,918 canonical, 4,364 duplicates removed
$ strata screen title-abstract                 # ethan and sam, over two weeks

# Day 15 -- the problem
$ strata criteria add --kind exclusion --label "Mean sample age under 18"
  Direction: added (treated as tightened)
  Why did you make this change?
  > Pilot extraction showed 9 of the first 40 studies used child samples.
  > Our question is about adult learners, and developmental differences in
  > spacing effects are large enough that pooling would be indefensible.

  Committed 4f1a2b9.
  Impact: 180 of 2,918 decisions are now stale (6.2%).
          2,738 decisions remain valid and require no action.

# Day 15 -- the fix
$ strata rescreen                              # 180 records, ~55 minutes
$ strata sync                                  # sam gets the same queue on his machine

# Day 90 -- writing up
$ strata prisma                                # flow diagram, counts reconcile
$ strata report amendments                     # generates the protocol-change section:
```

> **Amendments to the protocol.** One exclusion criterion (mean sample age under
> 18 years) was added on 19 March 2026, after pilot data extraction indicated
> that 9 of the first 40 eligible studies used child or adolescent samples. As
> the review question concerns adult learners, and developmental moderation of
> spacing effects is substantial, these were judged not to belong in the pooled
> estimate. The change invalidated 180 of 2,918 title/abstract screening
> decisions, all of which were re-screened by both reviewers under the revised
> criteria; 42 records were excluded as a result.

Every number and every date in that paragraph is generated from the event log and
the commit trailers. The prose around them is the user's own rationale, written
once, at the moment they made the decision and actually remembered why.

Contrast with the spreadsheet workflow the origin document describes: the
alternative is re-screening all 2,918 records (roughly 15 hours), or — far more
commonly — not updating the criteria at all.
