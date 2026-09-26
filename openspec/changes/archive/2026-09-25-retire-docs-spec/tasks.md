# Tasks

## 1. Move the content

- [x] 1.1 Write `design.md` for every capability in `openspec/specs/` from the retired rationale
- [x] 1.2 Move reference material for unbuilt milestones into the changes' `design.md`
- [x] 1.3 Move the overview, roadmap, and open questions to `docs/`
- [x] 1.4 Remove `_Source:_` citation lines from specs; point each Purpose at its `design.md`

## 2. Rewrite references

- [x] 2.1 Rewrite references in `src/`, `tests/`, `scripts/`, `.github/`, `pyproject.toml`, templates, static assets, and JSON Schemas to `openspec:` form
- [x] 2.2 Keep historical milestone plans and past changelog entries as written

## 3. Checks

- [x] 3.1 Rewrite `scripts/check_docs.py` for `openspec/` and `docs/`, `openspec:` reference resolution, the capability index, and retired-path detection
- [x] 3.2 Unit tests for `scripts/check_docs.py`
- [x] 3.3 Delete the retired directory
