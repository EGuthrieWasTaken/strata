# Proposal: Align the dedup performance requirement with the scale targets

## Why

Two requirements state the 50,000-record dedup budget and disagree.
`openspec:performance#scale-targets` gives `strata dedup` a *target* of 120 s and
a *hard limit* of 300 s, and `openspec:performance#benchmarks-run-in-ci` says only
a breach of the hard limit fails CI. `openspec:deduplication#performance` says
dedup MUST finish in under 120 s. The roadmap's M1 acceptance bar (under 300 s)
agrees with the hard limit.

The benchmark test followed the stricter requirement, so the nightly
`benchmark-50k` job failed intermittently from late September (21 auto-filed
issues). The latest failure measured dedup at 129.0 s on a GitHub-hosted runner
against the 120 s budget: over the soft target, nowhere near the hard limit. The
test has since been corrected to the performance spec; this change removes the
contradiction at its source so the two specs, the test, and the roadmap say the
same thing.

## What Changes

- `openspec:deduplication#performance` is reworded so that 50,000-record dedup
  MUST meet the hard limits and SHOULD meet the targets that
  `openspec:performance#scale-targets` sets, naming the time figures (120 s target,
  300 s hard limit). Memory is deferred to the same table rather than restated,
  so the two specs cannot drift apart again. The "SHOULD parallelise scoring across
  blocks" guidance is kept.
- A scenario records the case that caused the failure: a run between the target
  and the hard limit meets the requirement and does not fail the nightly job.
- The requirement keeps its name, so every `openspec:deduplication#performance`
  reference still resolves.

Milestone: M1 (deduplication), already shipped.

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `deduplication`: the "Performance" requirement.

## Impact

- No code under `src/` changes and no runtime behaviour changes. The dedup
  implementation is unchanged; only the figure it is held to is.
- `tests/benchmark/test_dedup_performance.py`: the docstring no longer describes
  a contradiction between the specs (the assertions were already corrected).
- Does not alter identity, normalisation, canonical serialisation, the fold, or
  the staleness rules; no schema-version bump.
- Known and unchanged: dedup still misses the 120 s *target* on CI-class hardware
  (the per-record MinHash cost). Closing that gap is performance work, not a
  specification question.
