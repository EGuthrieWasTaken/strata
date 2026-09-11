"""Structured commit message construction.

Implements docs/spec/04-git-integration.md §2.2. Building the message text is
domain logic and stays out of `strata.gitio`, which only ever shells out to
git with a message already decided (docs/spec/12-architecture.md §2).
"""

from __future__ import annotations

import textwrap
from dataclasses import dataclass, field

MIN_RATIONALE_LENGTH = 12
_RATIONALE_STOPLIST = frozenset({".", "x", "fix", "update", "wip", "asdf"})


class RationaleRejectedError(ValueError):
    """The supplied rationale fails docs/spec/04-git-integration.md §2.3."""


def validate_rationale(text: str | None) -> str:
    if text is None:
        raise RationaleRejectedError("a rationale is required for this operation")
    stripped = text.strip()
    if not stripped:
        raise RationaleRejectedError("the rationale must not be empty or whitespace")
    # Checked before the length floor: every stop-listed word is short enough
    # that the length check would otherwise mask it behind a generic
    # "too short" message instead of this more instructive one.
    if stripped.lower() in _RATIONALE_STOPLIST:
        raise RationaleRejectedError(
            f"{stripped!r} is not a rationale — say what changed and why, "
            "because this is what a peer reviewer or your future self reads"
        )
    if len(stripped) < MIN_RATIONALE_LENGTH:
        raise RationaleRejectedError(
            f"the rationale must be at least {MIN_RATIONALE_LENGTH} characters "
            "(this goes in the permanent record)"
        )
    return stripped


@dataclass
class StructuredCommit:
    op: str
    scope: str | None
    summary: str
    body: str | None
    trailers: dict[str, str] = field(default_factory=dict)

    def subject(self) -> str:
        scope = f"({self.scope})" if self.scope else ""
        subject = f"{self.op}{scope}: {self.summary}"
        if len(subject) > 72:
            raise ValueError(f"commit subject exceeds 72 characters: {subject!r}")
        return subject

    def message(self) -> str:
        parts = [self.subject()]
        if self.body:
            wrapped = "\n".join(
                textwrap.fill(paragraph, width=72) if paragraph else ""
                for paragraph in self.body.splitlines()
            )
            parts.append("")
            parts.append(wrapped)
        if self.trailers:
            parts.append("")
            parts.extend(f"Strata-{key}: {value}" for key, value in self.trailers.items())
        return "\n".join(parts) + "\n"
