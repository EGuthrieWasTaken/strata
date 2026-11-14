"""What a refused action is told in the browser: the reviewer's words first.

The domain modules raise errors written for whoever is at the command line or reading a log:
they name the setting that caused the refusal, list stored codes, cite the specification. In the
browser the reader is a reviewer in the middle of a task, so each such error is said as what is
wrong and what to do, and the setting or code follows as a muted second line for whoever has to
look it up. An error with no entry here is shown as it is.

A domain error opts in by carrying a `code` (a short stable name); the words live here, with the
screens, not in the domain modules, whose messages the command line and the MCP server still use.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Shown:
    """An error as a page shows it: `text` in the alert, `detail` muted beneath it."""

    text: str
    detail: str | None = None


_WORDS: dict[str, Shown] = {
    "exclusion-needs-reason": Shown(
        "Tick at least one reason before excluding. This review records why each record is "
        "excluded.",
        "Setting: screening.require_exclusion_reason",
    ),
    "full-text-exclusion-needs-reason": Shown(
        "Tick at least one reason before excluding. An exclusion at full text always needs one, "
        "because the PRISMA flow diagram reports them by reason.",
        "Requirement: screening#screening-surface-contract",
    ),
    "not-retrieved-needs-reason": Shown(
        "Choose why the report could not be retrieved, under “Why not”, then record it again. "
        "The flow diagram reports the reports not retrieved by reason.",
        "Field: reason",
    ),
    "not-retrieved-other-needs-text": Shown(
        "You chose “Other”: say what happened in the box beside it.",
        "Field: reason_text",
    ),
    "not-an-adjudicator": Shown(
        "You can read this disagreement but not settle it: that is for the review’s "
        "adjudicators and its lead.",
        "Setting: screening.adjudicators, or the role adjudicator or lead",
    ),
}


def named(code: str) -> Shown:
    """The words for a refusal a page shows without an exception having been raised."""
    return _WORDS[code]


def sentence(text: str) -> str:
    """`text` ending as a sentence, so another can follow it."""
    stripped = text.rstrip()
    return stripped if stripped.endswith((".", "!", "?", ";", ":")) else stripped + "."


def for_reviewer(error: Exception) -> Shown:
    """`error` as a reviewer should read it."""
    code = getattr(error, "code", None)
    shown = _WORDS.get(code) if isinstance(code, str) else None
    return shown if shown is not None else Shown(str(error))
