# Tasks

## 1. Specification

- [x] 1.1 Reword `openspec:deduplication#performance` to the 120 s target / 300 s hard limit of `openspec:performance#scale-targets`, deferring memory to the same table
- [x] 1.2 Add a scenario for a run between the target and the hard limit

## 2. Tests

- [x] 2.1 The nightly 50k dedup benchmark fails only past the 300 s hard limit and warns past 144 s (commit `7f3a31e`)
- [x] 2.2 Update the benchmark docstring, which described the contradiction this change removes

## 3. Checks

- [x] 3.1 `openspec validate --all --strict` and `scripts/check_docs.py` pass; all `openspec:deduplication#performance` references still resolve
