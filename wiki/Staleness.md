# Staleness

*Staleness* is the idea `strata` was built around: when your eligibility criteria change after screening has
begun, some of your earlier decisions may no longer be safe to rely on, and you should be told exactly which.

## The problem in methodologist's terms

A screening decision is a judgement made **against a particular statement of the criteria**. If the criteria
change, you have two bad options without a tool: re-screen everything (wasteful, and it discards trustworthy
work) or carry on and hope (unsafe, and unreportable). `strata` takes a third: it keeps, for every decision, the
version of the criteria it was made under and the criteria it cited, and from that works out the *minimal set*
of decisions the change could alter and proves the rest are untouched.

## The rules

Let a decision have been made at some earlier criteria version, and look at the criterion changes since that
apply **at that decision's stage**:

| The decision was | It is stale if... |
|---|---|
| **include** | any criterion was *tightened* (including a new criterion added) or changed in *both* directions |
| **exclude** | a criterion **that the exclusion cited** was *loosened*, *retired* or changed in *both* directions |
| **maybe** | anything non-editorial changed |

Everything else stays valid. The reasoning is monotonic:

- A stricter rule can only turn includes into excludes, so it can never revive an exclusion. Hence adding or
  tightening a criterion leaves *every exclusion* alone and re-opens only the inclusions.
- A looser rule can only turn excludes into includes, so it can never reject an inclusion. Hence loosening
  or retiring a criterion re-opens only the exclusions **that cited that criterion**. Exclusions that cited
  other criteria still stand on their own reasons.

A decision made before another stage's criterion changed is untouched: a change that applies only at full
text does not disturb title-abstract decisions. An *editorial* change (wording, label, examples,
whitespace; verified, not taken on trust) makes nothing stale.

### Worked example

You excluded 2,738 records and included 138 at title-abstract. Then:

| You... | Stale |
|---|---|
| add a new exclusion criterion | the 138 inclusions; no exclusion |
| loosen `EXC-03`, which 42 exclusions cited (300 cited `EXC-02`) | those 42 exclusions only; no inclusion |
| retire `EXC-05` | the exclusions that cited it, with the reason `criterion-retired` |
| fix a typo in a definition (`editorial`) | nothing |

## Reasons

Each stale decision carries exactly one reason, shown when you re-screen it:

| Reason | Meaning |
|---|---|
| `criterion-added` | A new criterion applies at this stage and this record was included |
| `criterion-tightened` | A criterion was tightened and this record was included |
| `criterion-loosened` | A criterion this exclusion cited was loosened |
| `criterion-retired` | A criterion this exclusion cited was retired |
| `criterion-both` | A bidirectional change |
| `maybe-any-change` | The decision was "maybe" and anything changed |
| `upstream-stale` | The record's decision at the previous stage is stale |
| `manual` | You forced it with `strata rescreen --mark` |

## Cascading, without deleting

A stale **title-abstract include** makes the record's **full-text** decision stale too (`upstream-stale`):
the full-text work was only done because of the earlier inclusion. If the record is then re-screened and
excluded, anything built on it is **kept, never deleted**: an extraction for a study whose record was later
excluded is retained, marked *orphaned*, and reported by `strata verify`. Committed analyses that used the
study are reported stale. You decide what to do; the log keeps everything.

## What it cannot do

The exclusion rule assumes the criterion a reviewer *cited* really was the reason. If a reviewer cites the
wrong one, a later change to the right one will not flag that record. `strata` helps (citing several criteria
takes one keystroke each, definitions are shown beside the choice, and `strata audit --criteria` re-presents a
random sample of exclusions to be checked), but it cannot fully protect against a mis-cited reason. Treat
the audit as part of the method.

## Where you see it

- `strata status`: stale counts per stage, and the command that addresses them.
- `strata rescreen`: the queue, showing the prior decision and the reason it is stale.
- `derived/stale.tsv`: the list, if you want to inspect it.
- `strata report amendments`: how many decisions each amendment made stale and what became of them.
- The [web interface](The-Web-Interface): the rescreening screen, and a live **impact preview** while you
  edit a criterion, before anything is saved.

Practical routine: [Changing criteria mid-review](Changing-Criteria-Mid-Review).
