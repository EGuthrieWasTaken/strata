# provenance-queries Specification

## Purpose

The commands that answer "why is this paper in (or out of) the review?" and
"what changed?" from the event log and structured git history: `strata why`,
`strata log`, and `strata diff`.

Rationale and example output: `docs/spec/04-git-integration.md` §6.

## Requirements

### Requirement: strata why

`strata why <id>` MUST reconstruct the full history of a record (and, as the
entities exist, a report, study, or effect) from the event log plus git
history: which searches and imports found it, which duplicates it absorbed and
with what score and features, who screened it under which criteria version,
any criteria change that made it stale with the commit and rationale, retrieval,
full-text decisions, study grouping, and extraction. Each line MUST cite the
event id and, with `-v`, the commit that carried it. Record ids MAY be
abbreviated to any unambiguous prefix.

_Source: `docs/spec/04-git-integration.md` §6.1_

#### Scenario: Record found by two searches

- **GIVEN** a record imported from `S-01-medline` that absorbed a duplicate from `S-02-embase`
- **WHEN** `strata why <record>` runs
- **THEN** it shows both imports, the absorbed id, and the dedup score and features

#### Scenario: Record made stale by a criteria change

- **GIVEN** an inclusion made stale by adding `EXC-07`
- **WHEN** `strata why -v <record>` runs
- **THEN** it shows the criteria change, the commit that carried it, and the user's rationale

### Requirement: strata log

`strata log` MUST render history as a list of methodological events read from
`Strata-` trailers rather than as commits. `--criteria` MUST filter to protocol
changes, `--stage` to one screening stage, and `--actor` to one person.

_Source: `docs/spec/04-git-integration.md` §6.2_

#### Scenario: Protocol changes only

- **WHEN** `strata log --criteria` runs
- **THEN** only commits whose trailers record criteria changes are listed

### Requirement: strata diff

`strata diff <ref>..<ref>` MUST report a domain-level diff between two points in
history: criteria versions and deltas, records identified and duplicates, pool
changes per stage, included studies, and — once analyses exist — the change in
each committed pooled estimate.

_Source: `docs/spec/04-git-integration.md` §6.3_

#### Scenario: Criteria and pool changes between two tags

- **WHEN** `strata diff v1-protocol..HEAD` runs
- **THEN** it reports the criteria version change with counts of added, tightened, and retired criteria, and the pool entering and leaving counts
