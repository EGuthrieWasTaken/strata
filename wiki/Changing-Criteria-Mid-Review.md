# Changing your criteria mid-review

It happens in almost every review: a criterion turns out to be vague, a pilot shows a loophole, or a
reviewer raises a case nobody foresaw. Changing the criteria after screening has begun is legitimate (and
reportable as a protocol amendment, PRISMA item 24c). The danger is not the change but *not knowing what it
did*. `strata` computes that exactly. This page is the practical routine; the reasoning is on
[Staleness](Staleness) and [Criteria versions and direction](Criteria-Versions-and-Direction).

## The routine

1. **Decide the change** with your co-reviewers and write down why.
2. **Make it with `strata criteria`**, declaring its *direction*.
3. **Read `strata status`** to see how many decisions the change put in doubt.
4. **Re-screen the stale decisions** with `strata rescreen`.
5. **Re-run anything downstream** (retrieval, extraction, analyses) that the new decisions affect.

### 1-2. Make the change

There are three ways to change the criteria set:

```
# add a criterion (behaves as "tightened": it can only remove records)
strata --why "The protocol requires randomised designs; the pilot found quasi-experiments slipping through" \
    criteria add --kind exclusion --label "Not randomised" \
    --definition "Participants were not randomly allocated to schedules." \
    --applies-at title-abstract,full-text --by ada

# edit a definition: you must say which way it moves the included pool
strata --why "Pilot showed adults on a university course should count as formal education" \
    criteria edit INC-01 --direction loosened \
    --definition "Participants are school pupils, university students or adults on a formal course." --by ada

# retire a criterion (behaves as "loosened": it can only add records)
strata --why "Superseded by EXC-03" criteria retire EXC-02 --by ada
```

```
added EXC-03 (criteria v6)
edited INC-01 (criteria v5, loosened)
```

For an edit, the direction is required, because the tool cannot reliably read it from the wording:

| `--direction` | Choose it when the change | Puts in doubt |
|---|---|---|
| `tightened` | can only make the included pool smaller (an exclusion excludes more, or an inclusion includes fewer) | decisions to **include** |
| `loosened` | can only make the pool larger | decisions to **exclude that cited this criterion** |
| `both` | does both, or you are unsure | both of the above |
| `editorial` | changes no meaning (wording, label, examples, whitespace) | nothing |

When unsure, choose `both`: it is always safe, only costlier. `editorial` is checked: `strata` refuses it if
the definition changed in any way other than the label, examples or whitespace.

`strata criteria diff 5 6` shows what changed between two versions, and `strata criteria list --version 4`
shows the set as it stood at version 4.

### 3. See the damage

```
strata status
```

```
Spacing and retention  criteria v6
...
TITLE-ABSTRACT  8 records    8 resolved · 0 unscreened · 0 partial
  6 STALE                    strata rescreen

FULL-TEXT  8 records    5 resolved · 3 unscreened · 0 partial
  5 STALE                    strata rescreen

NEXT  strata rescreen
```

Adding the exclusion criterion `EXC-03` put all 6 title-abstract inclusions in doubt (a record that was
included might fail the new test) and, because those inclusions are in doubt, the 5 full-text decisions that
depend on them. The two exclusions are *not* stale: a record already out for another reason cannot be
brought back by a stricter rule. That asymmetry is the whole idea.

### 4. Re-screen

```
strata --why "Re-screening after EXC-03 was added" rescreen --by ada
```

Each stale record is shown with your previous decision, why it is stale, and the current criteria:

```
title-abstract  STALE 1 of 11  (criterion-added)

Retrieval practice schedules in adult language learners

Your previous decision: INCLUDE  citing (none cited)
Now stale because: criterion-added

Criteria:
  1  INC-01  Learners in formal education
  ...
  5  EXC-03  Not randomised
[i]nclude [e]xclude [m]aybe [k]eep previous [s]kip [q]uit [s]:
```

- **`k` (keep previous)** records a *fresh* decision, identical to the old one, under the new criteria
  version: "a person reconsidered this and it stands". There is deliberately no "mark everything still
  valid" button; each stale decision gets looked at.
- **`i`, `e`, `m`** give a new decision (with criteria and a note, as in [Screening](Screening)).
- `--stage` limits the queue to one stage.

You can also *force* a decision stale for a reason the rules cannot see (a record you now doubt):
`strata rescreen --by ada --mark REC_ID --why "..."`.

Because the rule depends on the criteria you cited, it is worth auditing a sample of past exclusions for
mis-cited reasons: `strata audit --criteria` ([Adjudication and agreement](Adjudication-and-Agreement)).

### 5. Re-run what depends on it

Re-screening changes who is included. Then:

- Newly included records need full texts ([Retrieving full texts](Retrieving-Full-Texts)) and extraction.
- A record that was included and extracted but is now excluded keeps its extraction, marked **orphaned** and
  reported by `strata verify`; nothing is deleted. Re-include it, or leave the warning.
- A committed analysis whose inputs changed is reported **stale** by `strata status`. Screening never
  re-runs an analysis by itself; run `strata analyze` when you are ready.
- `strata diff v1-protocol..HEAD` (after `git tag v1-protocol` when the protocol was fixed; see
  [Setting up a review](Setting-Up-a-Review)) shows the criteria, records, included studies and pooled
  estimates that moved:

  ```
  Criteria:  v4 -> v6  (1 added, 1 loosened)
  Records:   10 -> 10  (+0 identified, +0 duplicates)
  Pool:      8 -> 8 at title-abstract  (+0 entered, -0 left)
  Pool:      6 -> 6 at full-text  (+0 entered, -0 left)
  Included:  4 -> 4 studies
  primary:  unchanged  SMD = 0.48 [0.15, 0.80]
  ```

## In the manuscript

Every change after screening began is reported automatically by `strata report amendments` (and in the Methods
and the PRISMA checklist, item 24c): the date, the criterion, your rationale (the `--why` you gave), how many
decisions it made stale, how many were re-screened and how many of those ended excluded. This is why the
`--why` for a criteria change is worth writing carefully.

## Rules of thumb

- **Cheapest: change before you start.** A pilot of 50 records with everyone is the least expensive place
  to find an ambiguous definition.
- **Prefer `editorial` only for real rewording.** Tightening "not English" to "not English or French" is a
  `tightened` change however small it looks.
- **Don't reuse an id.** Retired criteria stay in the file for ever and their ids are never reused
  (`strata verify` reports `E_CRITERION_REUSE`).
- **A change at one stage is invisible to the other.** A criterion that applies only at full text does not
  disturb title-abstract decisions.
