# Design: Reporting and PRISMA

## Context

Every count and date needed for reporting already exists in the event log and
the `Strata-` commit trailers (`event-log`, `git-integration` specs). What is
missing is the generator.

## Goals / Non-Goals

**Goals:**

- A flow diagram whose arithmetic always closes, or a loud failure naming the
  broken identity.
- Methods text a methodologist judges publishable without correction.
- Item 24c (protocol amendments) generated truthfully from the history.

**Non-Goals:**

- PRISMA extensions (PRISMA-S, PRISMA-ScR, PRISMA-IPD) — post-1.0.
- GRADE certainty assessment (item 22) — flagged as author work.
- Any generated Discussion or Conclusion.

## Decisions

- **Counts are derived, never typed**, and the generator asserts every
  reconciliation identity rather than trusting the arithmetic.
- **`marked_ineligible_by_automation` exists at 0 in v1** because the PRISMA
  2020 diagram has a box for it and adding a field later would be a schema bump.
- **Generated prose is a draft for the author**, marked with its commit hash,
  and never makes causal or significance claims; guardrail caveats are
  carried into the text automatically.
- **The line is held at Methods and Results** (Q8 in
  [docs/open-questions.md](../../../docs/open-questions.md)): a Discussion is an argument, and a tool that drafts arguments makes the
  literature worse.

## Risks / Trade-offs

- PRISMA box labels and checklist wording reproduced from memory may differ
  from the official template; verification against prisma-statement.org is a
  release task.

## Reference: flow-diagram structure (PRISMA 2020, new reviews)

```
IDENTIFICATION
  Records identified from:              Records identified from:
    Databases (n = )                      Websites (n = )
    Registers (n = )                      Organisations (n = )
                                          Citation searching (n = )
  Records removed before screening:
    Duplicate records removed (n = )
    Records marked as ineligible
      by automation tools (n = )
    Records removed for other
      reasons (n = )

SCREENING
  Records screened (n = )  ------------>  Records excluded (n = )
  Reports sought for retrieval (n = ) -->  Reports not retrieved (n = )
  Reports assessed for eligibility (n = ) -> Reports excluded, with reasons:
                                              Reason 1 (n = )
                                              Reason 2 (n = )
INCLUDED
  Studies included in review (n = )
  Reports of included studies (n = )
```

Labels are reproduced from the published PRISMA 2020 materials (Page et al.,
*BMJ* 2021;372:n71) to the best of our knowledge and must be verified against
the official template before shipping; the materials are CC BY 4.0, so generated
output carries the attribution.

## Reference: checklist items `strata` can fill

| Item | Topic | Source in the repository |
|---|---|---|
| 5 | Eligibility criteria | `protocol/criteria.yaml`, including the full amendment history |
| 6 | Information sources | `protocol/searches/*.yaml` |
| 7 | Search strategy | The verbatim `query` blocks |
| 8 | Selection process | `strata.toml` screening config + adjudication events |
| 9 | Data collection process | `extraction/schema.yaml` + reconciliation events |
| 10a/10b | Data items | `protocol/outcomes.yaml`, `protocol/moderators.yaml` |
| 11 | Risk of bias assessment | `rob/instrument.yaml` + assessment events |
| 12 | Effect measures | `analysis/*.yaml` `effect_size` |
| 13a–13f | Synthesis methods | `analysis/*.yaml` model, dependency, heterogeneity, sensitivity |
| 14 | Reporting bias assessment | `analysis/*.yaml` `publication_bias` |
| 16a/16b | Study selection | `derived/counts.json`, flow diagram, exclusion-reason table |
| 17 | Study characteristics | Generated characteristics table |
| 18 | Risk of bias in studies | Generated traffic-light plot |
| 19/20 | Results of individual studies and syntheses | Forest plots, `estimates.json` |
| 21 | Reporting biases | Funnel plot, Egger, trim-and-fill |
| 22 | Certainty of evidence | GRADE — not generated; author work |
| 24a | Registration and protocol | `strata.toml` `[project.registry]` |
| 24c | Amendments | `criteria-change` events and commit trailers |
| 25/26 | Competing interests, funding | `strata.toml` (added in this change) |
| 27 | Availability of data and code | The repository URL and commit hash |

Item 24c — amendments to the protocol — is the item this whole tool exists to
make truthful, and the one most often reported as "none" in published reviews
simply because nobody kept track.

## Reference: the reproducibility package

`strata export package` produces what PRISMA item 27 asks to be made available —
search strategies, criteria with their history, the decision log, extraction
data, analysis specifications, results, and a README naming the source commit —
for deposit with a journal submission or on OSF or Zenodo. Because full texts
are never committed, it contains no third-party copyrighted material.

## Coordination with `add-ai-participation`

`add-ai-participation` amended the Methods and checklist code this change specifies. Two fixed sentences
(`no records were removed by other automation tools` in the Methods; `no machine-learning prioritisation
was used` in checklist item 8) became false the day an AI agent takes part, so they are now written from
the ledger of what agents did (`strata.core.ledger`, `strata.report.disclosure`). For a review in which no
agent took part the text is byte-identical to what this change specifies; with one, items 8, 9 and 11 and the
Methods name each model (as self-reported), the kinds of work and the mode, the suggestions adopted and
rejected and the decisions counted, and count people and models apart. `Facts.reviewers()` now lists
people only. Anything this change adds that states a fact about who or what did the work should read it from
the ledger rather than assert it.
