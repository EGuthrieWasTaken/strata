# deduplication Specification Delta

## MODIFIED Requirements

### Requirement: Performance

Deduplicating 50,000 records on a 2020-era laptop, single-threaded, MUST meet
the hard limits, and SHOULD meet the targets, that
`openspec:performance#scale-targets` sets for `strata dedup` and for peak memory:
it SHOULD complete in under 120 seconds and MUST complete in under 300 seconds.
Implementations SHOULD parallelise scoring across blocks.

#### Scenario: 50,000-record dedup

- **WHEN** `strata dedup` runs over 50,000 records on reference hardware
- **THEN** it completes in under 300 seconds, within the memory limits of
  `openspec:performance#scale-targets`

#### Scenario: Target missed, hard limit met

- **WHEN** a 50,000-record dedup takes more than 120 seconds but less than 300
- **THEN** the requirement is met, and the nightly `benchmark-50k` job does not
  fail (it warns only above 120% of the target, per
  `openspec:performance#benchmarks-run-in-ci`)
