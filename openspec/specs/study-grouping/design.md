# Design: study-grouping

*Informative.* The requirements are in [spec.md](spec.md).

## Why a study, not a report, is the unit

Double-counting a study reported twice is one of the most common serious errors in
published meta-analyses. A trial can appear as a conference abstract, a primary
paper and a follow-up; an article can report three independent experiments. The
unit that is extracted, assessed for bias and clustered in analysis is the
**study**, so every included report belongs to exactly one.

## Singletons are derived, not recorded

An ungrouped report is a study of one whose id is a pure function of the report id
(`singleton_study_id`). No event has to create it, so the common case costs
nothing and an undo of a grouping simply returns the reports to their derived
ids. Only `study-group` events mint a new `std_<16>` id, and `study-split`
records the opposite move; the fold applies them in log order.

## Suggestions never apply themselves

Grouping heuristics (a shared trial registration, shared authors with overlapping
sample descriptions, follow-up wording, mutual citation) and splitting heuristics
(several independent experiments in one report) are ranked suggestions. Applying
one needs a decision and a rationale, and dismissing one is also recorded, so a
suggestion the reviewer already rejected does not return. Grouping is a judgement
about the world, and the audit trail should say who made it.

## Example

```
$ strata studies

  41 included reports -> 38 studies

  Suggested groupings (shared trial registration, sample, or authors):
    std_?  Larsen 2009 (Med Educ) + Larsen 2013 (Med Educ)
           same NCT id: NCT00713310; overlapping sample description
           [g] group   [k] keep separate   [?] show both

  Suggested splits:
    rpt_8k2m...  Kornell 2009 reports 3 independent experiments
           [s] split   [k] keep as one
```
