# performance Specification

## Purpose

Scale targets for a large but ordinary review (four databases, 50,000 raw
records, 40,000 after deduplication, 400 full texts, 60 included studies, 120
effects) on reference hardware, and how they are enforced in CI.

Rationale and worked examples: [design.md](design.md).

## Requirements

### Requirement: Scale targets

Operations MUST meet these hard limits, and SHOULD meet these targets, on a
2020 laptop with 4 cores, 16 GB RAM, and an SSD:

| Operation | Target | Hard limit |
|---|---|---|
| `strata import` of a 20,000-record RIS file | < 30 s | 60 s |
| `strata dedup` over 50,000 records | < 120 s | 300 s |
| `strata status` | < 1 s | 3 s |
| Staleness computation over 50,000 decisions | < 2 s | 5 s |
| Fold from cold (no cache) | < 5 s | 15 s |
| Derived-view regeneration | < 10 s | 30 s |
| `strata verify --fast` (pre-commit) | < 2 s | 5 s |
| `strata verify` (full) | < 60 s | 180 s |
| Screening decision round trip | < 100 ms p95 | 250 ms |
| `strata analyze` (60 studies, RE + moderators + diagnostics) | < 5 s | 20 s |
| Peak RSS, any operation at 50k records | < 2 GB | 4 GB |
| Repository size at 50k records | < 200 MB | 500 MB |

#### Scenario: Status on a large review

- **WHEN** `strata status` runs on a 50,000-record repository
- **THEN** it completes in under 3 seconds

#### Scenario: Cold fold

- **GIVEN** no `.strata/cache/`
- **WHEN** the event log of a 50,000-record review is folded
- **THEN** it completes in under 15 seconds

### Requirement: Benchmarks run in CI

`pytest-benchmark` MUST run the scale-target operations against generated
repositories at 1k, 10k, and 50k records. On pull requests the benchmark job is
warn-only; the nightly 50k benchmark is blocking. A regression above the hard
limit MUST fail CI; a regression above 20% of the target MUST produce a warning.

#### Scenario: Regression beyond the hard limit

- **WHEN** a change makes the nightly 50k dedup benchmark exceed 300 seconds
- **THEN** the nightly `benchmark-50k` job fails
