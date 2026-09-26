# staleness Specification

## Purpose

The staleness engine — the feature the project exists for. When the protocol
changes mid-review, it computes the minimal set of prior screening decisions the
change could alter, proves the rest are still valid, cascades staleness forward
across stages without deleting downstream work, and drives the re-screening and
audit workflows that clear it.

Rationale, including the soundness argument: `docs/spec/06-workflow-screening.md` §4–§6.

## Requirements

### Requirement: Decisions bind to the criteria they were made under

Every `screen` and `adjudicate` event MUST record `criteria_version`, the set
`criteria_digest`, and the specific `criteria[]` cited, so a decision is always
interpretable against the exact rules in force when it was made.

_Source: `docs/spec/06-workflow-screening.md` §4.1_

#### Scenario: Screening event contents

- **WHEN** a reviewer excludes a record citing `EXC-02` at criteria version 3
- **THEN** the event records `criteria: ["EXC-02"]`, `criteria_version: 3`, and the version-3 set digest

### Requirement: The staleness rules

Let a resolved decision `D` at stage `S` have been made at criteria version
`v_D` citing criteria set `C_D`, and let `Δ` be the set of criterion changes
between `v_D` and the current version that apply at stage `S`. `D` MUST be
marked STALE if and only if:

```
D.decision == "include"  and  ∃ c ∈ Δ with direction ∈ {tightened, both}
D.decision == "exclude"  and  ∃ c ∈ Δ ∩ C_D with direction ∈ {loosened, both, retired}
D.decision == "maybe"    and  Δ ≠ ∅ (any non-editorial change)
```

Everything else MUST remain valid. For a random criteria change and decision
set, every decision not marked stale MUST be one whose outcome provably cannot
change under the declared direction (property P10, tested against a brute-force
reference implementation, and never weakened to make the suite pass).

_Source: `docs/spec/06-workflow-screening.md` §4.2–§4.3; property P10 in `docs/spec/14-testing.md` §2_

#### Scenario: Criterion added

- **GIVEN** 138 records included and 2,738 excluded at title-abstract
- **WHEN** a new exclusion criterion applying at title-abstract is added
- **THEN** exactly the 138 inclusions are stale and every exclusion remains valid

#### Scenario: Criterion loosened

- **GIVEN** 42 exclusions citing `EXC-03` and 300 citing `EXC-02`
- **WHEN** `EXC-03` is loosened
- **THEN** exactly the 42 exclusions citing `EXC-03` are stale, and no inclusion is stale

#### Scenario: Criterion retired after exclusions cited it

- **GIVEN** exclusions citing `EXC-05`
- **WHEN** `EXC-05` is retired
- **THEN** those exclusions are stale with reason `criterion-retired`

#### Scenario: Change at a different stage

- **GIVEN** a title-abstract inclusion
- **WHEN** a criterion that applies only at `full-text` is tightened
- **THEN** the title-abstract inclusion remains valid

#### Scenario: Editorial change

- **WHEN** a verified editorial change is made to any criterion
- **THEN** no decision becomes stale

### Requirement: Mitigations for miscited criteria

Because the exclusion rule assumes a cited criterion genuinely applied,
`strata` MUST support citing multiple criteria on one exclusion with one
keystroke each, MUST show a criterion's full definition on hover or focus, and
MUST offer `strata audit --criteria [--sample N]`, which re-presents a random
sample of past exclusions for verification. The documentation MUST state that
the tool cannot fully protect against a miscited reason.

_Source: `docs/spec/06-workflow-screening.md` §4.3_

#### Scenario: Audit sample

- **WHEN** `strata audit --criteria --sample 50` runs
- **THEN** 50 randomly sampled past exclusions are re-presented with their cited criteria for verification

### Requirement: Staleness cascades across stages without deleting work

A stale `include` at title-abstract MUST mark the dependent full-text decision
stale as well (reason `upstream-stale`). Downstream work MUST never be silently
deleted: an extraction for a study whose record was later excluded is retained,
marked `orphaned`, and reported.

_Source: `docs/spec/06-workflow-screening.md` §4.4; E2E-06 in `docs/spec/14-testing.md` §5_

#### Scenario: Title-abstract reversal orphans downstream work

- **GIVEN** a record included at both stages with a full-text decision
- **WHEN** its title-abstract inclusion becomes stale and is re-screened as exclude
- **THEN** its full-text decision is marked stale with reason `upstream-stale`
- **AND** any extraction for its study is retained and reported as orphaned

### Requirement: Staleness causes

Each stale decision MUST carry exactly one of these reasons:

| Reason | Trigger |
|---|---|
| `criterion-added` | A new criterion applies at this stage and this record was included |
| `criterion-tightened` | A criterion was tightened and this record was included |
| `criterion-loosened` | A criterion this exclusion cited was loosened |
| `criterion-retired` | A criterion this exclusion cited was retired |
| `criterion-both` | A bidirectional change |
| `maybe-any-change` | The decision was `maybe` and anything changed |
| `upstream-stale` | A prior-stage decision for this record is stale |
| `manual` | A user explicitly invalidated it with `strata rescreen --mark <records>` |

_Source: `docs/spec/06-workflow-screening.md` §5_

#### Scenario: Manual invalidation

- **WHEN** a user runs `strata rescreen --mark rec_3kq8v1r0zx2m4a7b --why "..."`
- **THEN** that record's decision is stale with reason `manual`

### Requirement: Status reports staleness with its causes

`strata status` MUST report, per stage, resolved, unscreened, conflict, and
stale counts, break the stale count down by cause, name the command that
addresses each problem, and estimate re-screening effort at the reviewer's
recent pace.

_Source: `docs/spec/06-workflow-screening.md` §6_

#### Scenario: After adding a criterion

- **WHEN** `strata status` runs after a change made 180 decisions stale
- **THEN** it shows `STALE 180 -> strata rescreen` with a breakdown by cause and an effort estimate

### Requirement: Re-screening shows the prior decision

`strata rescreen [--stage S]` MUST open the stale queue showing each record with
its prior decision (clearly marked as prior), when and under which criteria
version it was made, and the change that invalidated it.

_Source: `docs/spec/06-workflow-screening.md` §6_

#### Scenario: Stale record presented

- **WHEN** a record made stale by adding `EXC-07` is shown in the re-screening queue
- **THEN** the prior decision, its date and criteria version, and the reason "EXC-07 was added and applies at title-abstract" are displayed

### Requirement: Keep previous is an explicit re-decision

The keep-previous action MUST append a fresh `screen` event with the same
decision at the current criteria version, clearing staleness and recording that
a human reconsidered it. `strata` MUST NOT offer to mark all stale decisions as
still valid without an explicit `--i-have-reviewed-these` flag and a rationale.

_Source: `docs/spec/06-workflow-screening.md` §6_

#### Scenario: Keep previous decision

- **WHEN** a reviewer presses `k` on a stale inclusion made at version 3 while version 4 is current
- **THEN** a new `screen` event with `decision: include` and `criteria_version: 4` is appended and the record is no longer stale

#### Scenario: Bulk keep without the flag

- **WHEN** a user attempts to clear all stale decisions at once without `--i-have-reviewed-these`
- **THEN** the operation is refused

### Requirement: Staleness computation performance

Staleness computation over 50,000 decisions MUST complete in under 2 seconds
(hard limit 5 seconds) on reference hardware.

_Source: `docs/spec/13-nonfunctional.md` §1_

#### Scenario: Large review

- **WHEN** staleness is computed over 50,000 decisions
- **THEN** it completes in under 2 seconds
