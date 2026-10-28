# Tasks

## 1. Specification

- [x] 1.1 State in `openspec:git-integration#versioned-hooks` that a hook which cannot find `strata` says so, naming `STRATA_SKIP_HOOKS=1` where it blocks, and that `strata` makes itself findable by the hooks it triggers
- [x] 1.2 Add scenarios for `strata` missing from `PATH` and for `strata` started by an absolute path

## 2. Implementation

- [x] 2.1 Guard each hook script on `command -v strata`
- [x] 2.2 Append the running `strata`'s directory to `PATH` for the git processes `gitio.run` starts, only when `strata` does not already resolve

## 3. Tests

- [x] 3.1 With `strata` off `PATH`, a commit made by the in-process CLI still succeeds with the hooks enabled
- [x] 3.2 A hook run without `strata` on `PATH` blocks (`pre-commit`, `commit-msg`) or warns (`post-merge`, `post-checkout`), naming `STRATA_SKIP_HOOKS=1` where it blocks
- [x] 3.3 `PATH` is untouched when `strata` already resolves, and the directory is appended, not prepended

## 4. Checks

- [x] 4.1 `openspec validate --all --strict` and `scripts/check_docs.py` pass
