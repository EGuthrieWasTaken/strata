# Design: repository-verification

*Informative.* The requirements are in [spec.md](spec.md).

## Report everything, not the first problem

A researcher fixing a repository after a bad merge should see every problem at
once, not discover them one `strata verify` run at a time. Each check is
independent and every violation is reported with its code.

## Error codes are identified requirements

Each `E_*` code is an identified requirement that a test must name
(`openspec:test-suite#requirement-traceability`). Some codes
(`E_ORPHAN_EXTRACTION`, `E_MISSING_EXTRACTION`, `E_UNIT`, `E_EFFECT_INPUTS`,
`E_COUNT_RECONCILE`) guard data that only exists once later milestones ship;
they are catalogued now so the format does not need a schema bump to add them.

## Why `--fast` exists

The pre-commit hook runs on every commit, so it must be quick enough that nobody
is tempted to set `STRATA_SKIP_HOOKS=1` permanently. `--fast` checks what
corrupts a repository (schemas, chains, dangling references, derived drift) in
under two seconds at 50,000 records; the full check runs in CI.

## Recovery is a first-class path

`strata` must not wrap git so tightly that ordinary git use can break it. Users
who know git will cherry-pick, reset, and resolve conflicts by hand. The promise
is that after any amount of that, `strata verify --fix` regenerates every
derived artefact, re-links event chains, and truncates partial lines, returning
the repository to a valid state (end-to-end scenario E2E-08).

## Nothing is deleted by default

Deduplication absorbs, retirement retains, exclusion records. The only
destructive command is `strata gc --imports`, which exists for reviews that
genuinely cannot keep raw exports, and it says plainly that it breaks
reproducibility.
