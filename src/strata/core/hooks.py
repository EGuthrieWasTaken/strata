"""Git hook content and commit-message trailer validation.

Implements openspec:git-integration#versioned-hooks (hooks) and the trailer-block
half of openspec:git-integration#structured-commit-messages (structured commit messages). The hooks
themselves are thin
shell scripts that call back into `strata internal hook-*`, so the checks
they run are exactly the checks `strata verify` runs — there is only one
implementation of each.
"""

from __future__ import annotations

import re

HOOKS_DIR = ".strata/hooks"

_TRAILER_LINE_RE = re.compile(r"^Strata-[A-Za-z-]+: .+$")
_ANY_TRAILER_RE = re.compile(r"^Strata-[A-Za-z-]*:?")

_SHEBANG = "#!/bin/sh\n"
_SKIP_GUARD = (
    'if [ -n "$STRATA_SKIP_HOOKS" ]; then\n'
    "    echo 'strata: STRATA_SKIP_HOOKS is set, skipping hook' >&2\n"
    "    exit 0\n"
    "fi\n"
)

HOOK_SCRIPTS: dict[str, str] = {
    "pre-commit": _SHEBANG + _SKIP_GUARD + "exec strata internal hook-pre-commit\n",
    "commit-msg": _SHEBANG + _SKIP_GUARD + 'exec strata internal hook-commit-msg "$1"\n',
    "post-merge": _SHEBANG + _SKIP_GUARD + "strata internal hook-post-merge; exit 0\n",
    "post-checkout": _SHEBANG + _SKIP_GUARD + "strata internal hook-post-checkout; exit 0\n",
}


def validate_commit_message_trailers(message: str, *, structured: bool) -> list[str]:
    """Return a list of problems with the trailer block; empty means it's fine.

    Only malformed trailer blocks are rejected. A message with no
    `Strata-`-prefixed lines at all is not this hook's business — a human is
    allowed to hand-author a commit.
    """
    if not structured:
        return []
    lines = message.splitlines()
    trailer_line_indices = [i for i, line in enumerate(lines) if _ANY_TRAILER_RE.match(line)]
    if not trailer_line_indices:
        return []

    errors: list[str] = []
    first = trailer_line_indices[0]
    last = trailer_line_indices[-1]

    if list(range(first, last + 1)) != trailer_line_indices:
        errors.append("Strata- trailers must form one contiguous block")

    if first > 0 and lines[first - 1].strip() != "":
        errors.append("the trailer block must be preceded by a blank line")

    for i in trailer_line_indices:
        if not _TRAILER_LINE_RE.match(lines[i]):
            errors.append(f"malformed trailer on line {i + 1}: {lines[i]!r}")

    return errors
