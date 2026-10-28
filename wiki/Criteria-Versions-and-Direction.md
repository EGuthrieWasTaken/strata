# Criteria versions and direction

The eligibility criteria are a **versioned protocol**: any change to the active set increases the version by
one, and every screening decision is stamped with the version (and a digest of the exact set) it was made
under. So a decision is always interpretable against the rules in force when it was made.

## Versions

- Adding, editing or retiring a criterion creates version *n+1* and records a `criteria-change` event with
  the exact changes, your rationale and the versions on either side.
- `strata criteria list --version 3` reconstructs the set as of version 3; `strata criteria diff 3 4` shows
  what changed.
- Retired criteria remain in `protocol/criteria.yaml` for ever and their ids are never reused.

## Direction

When a definition is edited you must classify the edit, because the staleness engine needs to know which
decisions it could affect and the text alone does not say:

| Direction | Meaning | Could invalidate |
|---|---|---|
| **tightened** | The included pool can only shrink: an exclusion excludes more, or an inclusion includes fewer | prior *includes* |
| **loosened** | The included pool can only grow | prior *excludes that cited the criterion* |
| **both** | Genuinely bidirectional, or you cannot tell | both |
| **editorial** | No change of meaning | nothing |

Two operations have a fixed direction: **adding** a criterion behaves as *tightened*, and **retiring** one
behaves as *loosened*.

### Choosing

Ask: *"could this edit change the outcome for a record I already decided?"* and in which direction.

| Edit | Direction |
|---|---|
| EXC "not English" becomes "not English or French" | tightened (excludes more) |
| EXC "adults only" becomes "participants over 16" | loosened (excludes fewer) |
| INC "RCTs" becomes "RCTs and quasi-experiments" | loosened (includes more) |
| INC "children under 12" becomes "children under 10" | tightened (includes fewer) |
| INC "children 6-12" becomes "children 6 to 12 years" | editorial |
| EXC "no control group" gains the examples "single-arm, case series" | editorial (examples only) |
| A definition rewritten so that some cases go one way and others the other | both |
| Not sure | both |

Mistakes in one direction are cheap: choosing `both` for a tightening costs you some extra re-screening (the
exclusions that cited the criterion). Mistakes the other way are not cheap, which is why the editorial claim
is verified: if the definition text changed in any way other than the label, the examples or whitespace,
`strata` refuses `editorial` and makes you pick again.

## Stages

Each criterion lists the stages it applies at (`title-abstract`, `full-text`). Staleness considers only
changes to criteria that apply at a decision's own stage, which is how you can tighten a full-text-only
criterion without touching a single title-abstract decision.

Practical routine: [Changing criteria mid-review](Changing-Criteria-Mid-Review). Background:
[Staleness](Staleness).
