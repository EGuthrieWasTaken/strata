# Proposal: Make the hooks find `strata`, and say so when they cannot

## Why

The hook scripts in `.strata/hooks` run `strata` by name. When `strata` is not on
`PATH` -- the usual case when it is started by an absolute path, such as
`/opt/venv/bin/strata`, or from an environment that is not activated -- git runs the
hook with the caller's `PATH`, the hook fails with `exec: strata: not found`, and the
commit is blocked. `strata init` dies this way at its first commit and leaves a
repository with nothing committed and every file staged, and the CLI shows a raw
`GitError` instead of an explanation.

`openspec:git-integration#versioned-hooks` already says every hook "MUST print that
the variable [`STRATA_SKIP_HOOKS`] exists when they block an operation". A hook that
blocks because `strata` is missing says nothing of the kind.

A `python -m strata` fallback in the hooks would not help: the hooks are committed
and shared, so they cannot name an interpreter, and an environment that lacks
`strata` on `PATH` usually lacks it on the system Python too. (It would also need a
`__main__` module, which does not exist.)

## What Changes

- When `strata` runs git, it makes the `strata` that is running findable by the hooks
  git triggers: if `strata` does not resolve on `PATH`, the directory of the running
  script (or, failing that, of the interpreter) is appended to the end of `PATH` for
  that git process. It is appended, so it can never shadow anything the user has on
  `PATH`. This repairs repositories that already exist, as the hook scripts do not
  change.
- The hook scripts check for `strata` first. `pre-commit` and `commit-msg` block with a
  message that says `strata` was not found and names `STRATA_SKIP_HOOKS=1`;
  `post-merge` and `post-checkout`, which never fail an operation, print a warning and
  succeed. New repositories (and a `strata doctor --fix` that reinstalls a missing
  hook) get the new scripts; existing hooks are not rewritten.

Milestone: M0 (git integration), already shipped.

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `git-integration`: the "Versioned hooks" requirement.

## Impact

- `src/strata/core/hooks.py`: the hook scripts. `src/strata/gitio/__init__.py`: the
  environment git is run with.
- No change to what any hook checks, to the repository layout, or to the schema version.
- `strata doctor` still checks that hooks exist, not what they contain.
