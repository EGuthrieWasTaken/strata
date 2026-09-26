# Design: test-suite

*Informative.* The requirements are in [spec.md](spec.md).

A meta-analysis tool's failure mode is a wrong number in a published paper. The
testing strategy is proportionate to that.

## Test levels

| Level | Scope | Gate |
|---|---|---|
| Unit | Pure functions: normalisation, ids, canonical serialisation, effect-size formulae | Every commit |
| Property | Invariants under generated input (`hypothesis`) | Every commit |
| Golden | Parsers and generated artefacts against committed expected output | Every commit |
| Statistical | Every estimator against `metafor` and published worked examples | Every commit (fixtures) + nightly (live R) |
| Integration | Multi-command flows against a real git repository | Every commit |
| End-to-end | Full review scenarios, including the origin scenario | Every commit |
| Performance | Benchmarks against the scale targets | Every commit, non-blocking; nightly, blocking |
| Fuzz | Parsers against mutated real exports | Nightly |
| Cross-platform | Linux, macOS, Windows | Every commit |
| Manual | Usability sessions with real reviewers | Per milestone |

## Why five modules get 100% branch coverage

`core/fold.py`, `core/ids.py`, `core/canon.py`, `protocol/staleness.py`, and
`stats/escalc.py` are where a bug silently corrupts a published result.

## Why P10 and P11 are sacred

Staleness soundness (P10) and count reconciliation (P11) protect the claims the
product is sold on: that unflagged decisions are still valid, and that the
funnel always closes. Weakening either to make the suite pass would make the
product's central promise untrue.

## Two statistical oracles

Agreement with `metafor` proves `strata` implements the same convention;
agreement with textbook worked examples proves the convention is the right one.
Where `strata` deliberately differs (the prediction-interval df), the fixture
pins `metafor`'s matching option with a comment — a silent tolerance bump to
paper over a convention mismatch is exactly the failure the rule exists to
prevent.

## Why diff coverage as well as floors

A global floor lets a large, well-covered codebase absorb an uncovered new
feature without the number moving. Checking coverage of the changed lines
closes that gap.

## Why requirement traceability

Every identified requirement (P1–P13, E2E-01–E2E-12, `E_*`) should have a test
that names it, so coverage of the *specification* is measurable rather than
asserted. Once everything current is covered, an uncovered requirement becomes a
gate failure.

## Why usability testing is a release gate

The entire premise is that the tool is usable by people the current
alternatives fail. At each milestone three people who have not used the tool
try it:

- **M1**: can a non-git user install and complete a screening session?
- **M2**: does a user understand what the staleness report is telling them, and
  do they trust it?
- **M3**: does a methodologist agree the generated Methods text is accurate and
  publishable?
