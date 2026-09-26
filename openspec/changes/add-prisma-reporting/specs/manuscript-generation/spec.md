# manuscript-generation Specification

## Purpose

Generated manuscript material — Methods, Results, the study characteristics
table, and the protocol-amendment section — under strict rules that keep
generated prose a factual draft, plus bibliography export and the
reproducibility package that satisfies PRISMA item 27.

## ADDED Requirements

### Requirement: Generated sections

`strata report methods|results|characteristics|amendments` MUST generate:
Methods from the protocol and configuration (databases and dates, full
eligibility criteria, screening process and reviewer count, extraction process
and agreement, RoB instrument, synthesis model with estimator, CI method, and
dependency handling); Results (flow counts, study characteristics, pooled
estimate with CI and prediction interval, heterogeneity, moderator,
publication-bias, and sensitivity analyses); a characteristics table with one
row per included study, exportable to `docx` and `latex`; and Amendments from
`criteria-change` events joined to their commit rationales.
`strata report manuscript --format docx|latex|md|html` MUST assemble them.

_Source: `docs/spec/09-reporting.md` §5_

#### Scenario: Amendments from the origin scenario

- **GIVEN** the age criterion was added with a rationale and 180 decisions were re-screened
- **WHEN** `strata report amendments` runs
- **THEN** the paragraph states the date, the criterion, the number of invalidated decisions, and the number excluded, around the user's own rationale

### Requirement: Rules for generated prose

Generated text MUST:

- Be marked as generated, with the commit hash it came from.
- Render numbers to the precision the data supports (two decimals for
  standardised effect sizes, whole percentages for `I2`), taken only from
  `estimates.json`.
- Contain no causal language and avoid statistical-significance language in
  favour of estimates and intervals.
- Include the caveat for every analysis guardrail that fired.

`strata` MUST NOT generate a Discussion or Conclusion.

_Source: `docs/spec/09-reporting.md` §5.1; `docs/spec/16-open-questions.md` Q8_

#### Scenario: Pooled estimate sentence

- **WHEN** Results prose describes the primary analysis
- **THEN** it reads like "the pooled standardised mean difference was 0.38 (95% CI 0.28 to 0.48)" and makes no causal claim

#### Scenario: Guardrail caveat

- **GIVEN** the `k < 10` guardrail fired in the primary analysis
- **WHEN** Results prose is generated
- **THEN** it includes the corresponding caveat

#### Scenario: Discussion requested

- **WHEN** a user asks `strata report` for a discussion section
- **THEN** it is refused with an explanation

### Requirement: Bibliography export

`strata export bibliography --format bibtex|csl|ris --set S` MUST support the
sets `included`, `excluded-at-fulltext`, `all-screened`, and `not-retrieved`.
CSL-JSON output MUST feed pandoc directly.

_Source: `docs/spec/09-reporting.md` §6_

#### Scenario: Appendix of full-text exclusions

- **WHEN** `strata export bibliography --format ris --set excluded-at-fulltext` runs
- **THEN** it emits exactly the records excluded at full text

### Requirement: Reproducibility package

`strata export package --out <file>` MUST produce the search strategies, the
criteria with full version history, the screening decision log, the extraction
data, the analysis specifications, the results, the review data licence, and a
README naming the commit it came from. It MUST contain no full texts.

_Source: `docs/spec/09-reporting.md` §7; `docs/spec/13-nonfunctional.md` §6_

#### Scenario: Package contents

- **WHEN** `strata export package --out supplement.zip` runs in a repository with local PDFs under `fulltext/`
- **THEN** the archive contains no PDF and its README names the source commit

### Requirement: Funding and competing-interest metadata

`strata.toml` MUST accept competing-interest and funding metadata, which MUST
flow into generated output for PRISMA items 25 and 26.

_Source: `docs/spec/16-open-questions.md` Q7_

#### Scenario: Funding statement

- **GIVEN** funding sources recorded in `strata.toml`
- **WHEN** the checklist is generated
- **THEN** item 25 is auto-filled from them
