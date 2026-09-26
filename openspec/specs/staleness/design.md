# Design: staleness

*Informative, but the reasoning is load-bearing.* The requirements are in
[spec.md](spec.md).

This is the feature the project exists for. Everything else in `strata` is
competent infrastructure; this is the part no other tool does.

## Why the rules are sound

The rules in `openspec:staleness#the-staleness-rules` are asymmetric, and the
asymmetry is the whole economic argument for the tool.

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
matching criterion" practice, which the UI encourages: a reviewer need not
enumerate every applicable criterion, because one valid ground is sufficient to
exclude. The rule does *not* assume the citation is exhaustive.

**The residual risk, stated plainly.** If a reviewer cites a criterion carelessly
— excludes a rodent study but clicks `EXC-05 (wrong outcome)` instead of
`EXC-02 (animal model)` — then retiring `EXC-05` will correctly flag the record
as stale (no harm), but retiring `EXC-02` will *not* flag it, and the record
stays excluded on a ground that no longer exists. The mitigations in
`openspec:staleness#mitigations-for-miscited-criteria` (multi-citation, visible
definitions, the audit sample) reduce this; they cannot eliminate it, and the
documentation must say so rather than imply a guarantee the tool cannot make.

Property P10 checks the implementation against a brute-force reference of these
rules and must never be weakened to make the suite pass.

## Why downstream work is never deleted

A title/abstract reversal can orphan a full-text decision and an extraction.
The extraction is retained and reported, not deleted: the user may well change
their mind back, and deleting a colleague's four hours of coding without asking
is unacceptable.

## Why keep-previous is an explicit action

`[k]` appends a fresh decision at the new criteria version, recording that a
human actually reconsidered. A bulk "mark all as still valid" would be the one
place the tool's integrity guarantee could be quietly hollowed out, so it needs
an explicit flag and a rationale.

## Why the prior decision is shown during re-screening

The reviewer is re-deciding, not deciding fresh. Hiding the prior judgement
would waste their earlier thinking and destroy consistency.

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

And `strata status` reports the work with its causes and an effort estimate:

```
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

## Worked example: the origin scenario

This is the scenario from the project's origin document
([docs/origin/ProgramSpec.org](../../../docs/origin/ProgramSpec.org)), executed
end to end. It is also acceptance test E2E-01. Its numbers are illustrative;
E2E-01 asserts the stale set the normative rule actually produces.

```
# Day 1 -- set up, search, import, screen
$ strata init --title "Spaced retrieval and long-term retention"
$ strata criteria add ...                      # 6 criteria
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
$ strata report amendments                     # generates the protocol-change section
```

> **Amendments to the protocol.** One exclusion criterion (mean sample age under
> 18 years) was added on 19 March 2026, after pilot data extraction indicated
> that 9 of the first 40 eligible studies used child or adolescent samples. As
> the review question concerns adult learners, and developmental moderation of
> spacing effects is substantial, these were judged not to belong in the pooled
> estimate. The change invalidated 180 of 2,918 title/abstract screening
> decisions, all of which were re-screened by both reviewers under the revised
> criteria; 42 records were excluded as a result.

Every number and date in that paragraph is generated from the event log and the
commit trailers. The prose around them is the user's own rationale, written
once, at the moment they made the decision and actually remembered why.

The spreadsheet alternative is re-screening all 2,918 records (roughly 15
hours), or — far more commonly — not updating the criteria at all.
