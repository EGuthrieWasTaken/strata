"""Structured commit message construction.

Implements openspec:git-integration#structured-commit-messages. Building the message text is
domain logic and stays out of `strata.gitio`, which only ever shells out to
git with a message already decided (openspec:architecture#module-boundaries).
"""

from __future__ import annotations

import textwrap
from dataclasses import dataclass, field

MIN_RATIONALE_LENGTH = 12
_RATIONALE_STOPLIST = frozenset({".", "x", "fix", "update", "wip", "asdf"})

SUBJECT_LIMIT = 72
_MIN_SUMMARY = 16
_MIN_SCOPE = 8


def _ellipsise(text: str, width: int) -> str:
    if len(text) <= width:
        return text
    if width <= 3:
        return text[:width]
    return text[: width - 3] + "..."


def fit_subject(op: str, scope: str | None, summary: str) -> tuple[str | None, str]:
    """Shorten `scope` and `summary` so `op(scope): summary` fits `SUBJECT_LIMIT`.

    A subject built from something a person chose (a file name, a search id derived from a database
    name) can be longer than the limit. Refusing it would fail the operation *after* it had written
    its files, so callers fit it instead; the full values stay in the trailers and in the data. The
    summary gives way first, down to a floor, then the scope. Text that already fits is returned
    unchanged, so ordinary commit messages are byte-identical.
    """

    def length(sc: str | None, su: str) -> int:
        return len(op) + (len(sc) + 2 if sc else 0) + 2 + len(su)

    over = length(scope, summary) - SUBJECT_LIMIT
    if over <= 0:
        return scope, summary
    summary = _ellipsise(summary, max(len(summary) - over, _MIN_SUMMARY))
    over = length(scope, summary) - SUBJECT_LIMIT
    if over > 0 and scope:
        scope = _ellipsise(scope, max(len(scope) - over, _MIN_SCOPE))
    return scope, summary


class RationaleRejectedError(ValueError):
    """The supplied rationale fails openspec:git-integration#eliciting-the-rationale."""


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
