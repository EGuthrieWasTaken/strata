# Risk-of-bias instruments: what ships, where it came from, what to check

`strata rob` ships five instrument definitions under `src/strata/extract/instruments/` and one
set of algorithms in `src/strata/extract/rob_algorithms.py`. This note records, plainly, how far
each can be trusted today and what has not been checked.

## What ships

| Instrument id | Tool | Domains | Overall |
|---|---|---|---|
| `rob2` | RoB 2, parallel-group trials, effect of assignment | D1-D5 | worst domain |
| `rob2-adhering` | RoB 2, effect of adhering to the intervention | D1-D5 (D2 differs) | worst domain |
| `robins-i` | ROBINS-I, non-randomised studies of interventions | seven | most severe domain, or `no-information` |
| `nos-cohort` | Newcastle-Ottawa Scale, cohort studies | selection, comparability, outcome | sum of stars |
| `nos-case-control` | Newcastle-Ottawa Scale, case-control studies | selection, comparability, exposure | sum of stars |

`strata rob init --instrument <id>` copies one into `rob/instrument.yaml`. A project may edit that
file or write its own in the same shape (`rob-instrument.schema.json`).

## Licence decision: no official question wording is bundled

Cochrane publishes the RoB 2 materials under CC BY-NC-ND 4.0, and ROBINS-I and the
Newcastle-Ottawa Scale carry their own terms. A "no derivatives" licence does not allow a
different tool to republish the wording in a modified form, and strata is GPL-licensed software
that others may redistribute and adapt. So the shipped definitions contain **only**:

- the domain names and ids (needed to refer to the domains at all),
- the judgement vocabulary of each domain,
- the signalling-question **numbers and a short neutral topic** written for this project
  ("Allocation sequence random"), not the official question text, and
- the answer options.

A project that holds a licence for the official wording can add a `text:` key to any question; the
CLI and the web screen show it when present. Nothing in strata depends on it.

## Where the RoB 2 algorithms came from, and how they are tested

The suggested domain judgements are computed from the signalling answers
(`rob_algorithms.py`; a suggestion is only ever a proposal, and overriding it needs a recorded
justification: openspec:risk-of-bias#algorithmic-suggestion-with-recorded-override).

The primary Cochrane algorithm tables could not be retrieved while this was written. The rules were
therefore implemented from two independent open-source transcriptions of those tables - the
R package [`robbR`](https://github.com/BLMoran/robbR) (`rob2_algorithm()`) and the [RoB 2 workbench](https://github.com/aashnapandyapsych/RoB) - and the two were compared **exhaustively**: they agree on all 82,125 combinations of
answers for Domains 1-5. `tests/unit/test_rob_algorithms.py` re-states one of them as an
independent rule-chain oracle and checks every combination against the decision-flow code, and
pins the flows' "which question is needed next" behaviour.

That is strong evidence the code matches the *published rules as others have transcribed them*. It
is not the same as having checked them against the Cochrane document, so the milestone's
"RoB 2 suggestions match the published decision rules on a published test set" criterion is met
only to that extent. Before a release that advertises RoB 2 support:

1. Obtain the official algorithm tables (the RoB 2 "full guidance" Excel macro or the Cochrane
   handbook chapter 8 supplement) and run the same exhaustive comparison against them.
2. Look first at the rules where the transcriptions make a judgement call rather than follow an
   explicit table row:
   - **D2, effect of assignment, question 2.3 answered "no information".** Both transcriptions
     return *some concerns* without consulting 2.4 and 2.5. The official flow chart's routing of
     "no information" at this point is the first thing to confirm.
   - **D4, question 4.2 "no information".** The base judgement becomes *some concerns* and 4.1
     "yes" or 4.2 "yes" is *high* regardless of 4.3-4.5.
   - **D2, effect of adhering.** Questions 2.3-2.5 are "if applicable"; an unanswered question is
     treated as not applicable.
3. Record the outcome here and, if anything differs, change the code and the pinned oracle.

## Overall judgements

`worst-domain` takes the most severe domain. For ROBINS-I a domain answered `no-information`
makes the overall `no-information` unless another domain is already serious or critical (the
published rule for ROBINS-I overall). The Newcastle-Ottawa Scale has no categories: each domain
holds a star count and the overall is their sum. Any overall can be overridden with a justification,
and a `custom` overall has no suggestion.

## Not covered

- RoB 2 for cluster-randomised and crossover trials (Domains 1b and S, and the cluster variants of
  the other domains) is not shipped; a project can define it as a custom instrument.
- ROBINS-E, QUADAS-2, and other tools are not shipped, for the same reason.
- `strata report rob` (robvis-compatible traffic-light and summary plots) belongs to the reporting
  milestone; the judgements are already exposed as moderators (`rob_overall`, `rob.<domain>`)
  in filters and in `strata export effects`.
