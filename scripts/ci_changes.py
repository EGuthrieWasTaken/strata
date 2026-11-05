"""Decide whether a pull request changes code or only documentation
(openspec:ci-gate#documentation-only-pull-requests-skip-the-test-jobs).

The `code-changes` job in `.github/workflows/ci.yml` runs this and writes `code=true` or
`code=false` to `$GITHUB_OUTPUT`. `test-fast` runs only when it says `true`, and so does every job
that waits for it (`test`, `statistical`, `determinism`, `coverage`, `benchmark`, `traceability`).
`lint`, `docs` and `gate` always run.

The set of documentation is small and the default is the safe one: a file that is not listed, a
change that cannot be read, or no change at all counts as code, so the worst a mistake here does is
run tests that did not need to run. It never skips a test that did.

A path is documentation only if no test reads it. The `docs` job (`scripts/check_docs.py`,
`scripts/check_wiki.py`, `openspec validate`) runs on every pull request and is what checks these
files. If a test starts to read a file under one of these paths, move that path out of
`DOC_DIRS` or `DOC_FILES` in the same change.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable

# Files at the repository root, and directories at the repository root. Matching is exact and
# case-sensitive, so `src/docs/x.py` and `Docs/x.md` are code.
DOC_FILES = frozenset({"README.md", "CHANGELOG.md", "CONTRIBUTING.md"})
DOC_DIRS = ("docs/", "wiki/", "openspec/")

# How many code files the log names, so a reader can see why the tests ran without a wall of text.
SHOWN = 10


def is_documentation(path: str) -> bool:
    return path in DOC_FILES or path.startswith(DOC_DIRS)


def changes_code(paths: list[str]) -> bool:
    """True unless there is at least one changed file and every one is documentation."""
    return not paths or not all(is_documentation(path) for path in paths)


def changed_paths(base_sha: str) -> list[str]:
    """The files that differ between `base_sha` and `HEAD`.

    Renames are reported as a deletion and an addition (`--no-renames`), so moving a source file
    into `docs/` still names the source path, and `-z` keeps unusual file names unquoted.
    """
    out = subprocess.run(
        ["git", "diff", "--name-only", "--no-renames", "-z", base_sha, "HEAD"],
        check=True,
        capture_output=True,
    ).stdout
    return [p for p in out.decode("utf-8", "surrogateescape").split("\0") if p]


def decide(
    event: str, base_sha: str, diff: Callable[[str], list[str]] = changed_paths
) -> tuple[bool, str]:
    """Whether the tests must run, and a sentence saying why."""
    if event != "pull_request":
        return True, f"{event or 'this event'} is not a pull request: every job runs"
    if not base_sha:
        return True, "no base commit was given: every job runs"
    try:
        paths = diff(base_sha)
    except (OSError, subprocess.CalledProcessError) as exc:
        return True, f"the changed files could not be read ({exc}): every job runs"
    if not paths:
        return True, "no changed files were found: every job runs"
    code = [path for path in paths if not is_documentation(path)]
    if not code:
        return False, f"only documentation changed ({len(paths)} files): the test jobs are skipped"
    shown = ", ".join(code[:SHOWN]) + (", ..." if len(code) > SHOWN else "")
    return True, f"{len(code)} of {len(paths)} changed files are not documentation ({shown})"


def main() -> int:
    code, reason = decide(os.environ.get("EVENT", ""), os.environ.get("BASE_SHA", ""))
    print(reason)
    line = f"code={'true' if code else 'false'}\n"
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            handle.write(line)
    else:
        print(line, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
