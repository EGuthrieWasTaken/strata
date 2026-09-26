# study-grouping Specification

## Purpose

Grouping included reports into studies — the unit of extraction and of
clustering in analysis — and splitting reports that describe several
independent studies, so no study is double-counted.

## ADDED Requirements

### Requirement: Grouping and splitting

`strata studies` MUST let the user group several reports into one study
(`study-group` event) and split one report into several studies (`study-split`
event). Both MUST require a rationale.

_Source: `docs/spec/07-workflow-extraction.md` §2_

#### Scenario: Follow-up paper

- **GIVEN** two included reports of the same trial
- **WHEN** the user groups them with a rationale
- **THEN** a `study-group` event records one study with both reports and the rationale

#### Scenario: Multi-experiment paper

- **WHEN** a report describing three independent experiments is split
- **THEN** a `study-split` event records three studies linked to that report

### Requirement: Suggestions only

`strata studies` MUST suggest groupings and splits using shared trial
registration numbers, a shared author set with overlapping sample size and
population description, explicit "follow-up of" or "secondary analysis of"
language, and reports citing each other. Suggestions MUST never be applied
automatically.

_Source: `docs/spec/07-workflow-extraction.md` §2_

#### Scenario: Shared registration number

- **GIVEN** two included reports naming the same NCT id
- **WHEN** `strata studies` runs
- **THEN** it suggests grouping them, shows the evidence, and changes nothing until the user decides
