"""The pull-request comment: what a change does to the review.

Implements openspec:review-repository-ci#pool-impact-comment. The input is two `strata status
--json` documents, one for the pull request's base and one for its head; the output is Markdown.
The comment carries a marker so the workflow updates one comment rather than adding a new one with
every push.
"""

from __future__ import annotations

from typing import Any

from strata.ci.amendment import Amendment

MARKER = "<!-- strata-review-ci -->"

Stage = dict[str, Any]


def _stages(status: dict[str, Any] | None) -> dict[str, Stage]:
    return {s["stage"]: s for s in (status or {}).get("stages", [])}


def _count(stage: Stage | None, key: str) -> int:
    return int((stage or {}).get(key, 0))


def _excluded(stage: Stage | None) -> int:
    return _count(stage, "resolved") - _count(stage, "included")


def _stale_excluded(stage: Stage | None) -> int:
    return _count(stage, "stale") - _count(stage, "stale_included")


def _plural(n: int, noun: str) -> str:
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"


def _pool(status: dict[str, Any]) -> int:
    stages = status.get("stages") or []
    return int(stages[0]["total"]) if stages else int(status.get("record_count", 0))


def _rise(head: dict[str, Stage], base: dict[str, Stage], count: Any) -> int:
    """How much `count(stage)` went up, summed over stages, ignoring stages where it went down."""
    return sum(max(count(s) - count(base.get(name)), 0) for name, s in head.items())


def _fall(head: dict[str, Stage], base: dict[str, Stage], count: Any) -> int:
    return sum(max(count(base.get(name)) - count(s), 0) for name, s in head.items())


def _changed(before: int | None, after: int) -> str:
    return str(after) if before is None or before == after else f"{before} → {after}"


def render(
    base: dict[str, Any] | None,
    head: dict[str, Any],
    *,
    amendment: Amendment | None = None,
    methodologist: str | None = None,
) -> str:
    """The comment body. `base` is None when the base commit is not a strata repository."""
    lines = [MARKER, "### strata: what this change does to the review", ""]
    if base is None:
        lines += [
            "The base branch has no strata repository, so this change is shown as it stands.",
            "",
        ]
    base_stages, head_stages = _stages(base), _stages(head)

    pool = _pool(head)
    if base is None:
        lines.append(f"- **Records in the pool:** {pool}.")
    elif _pool(base) == pool:
        lines.append(f"- **Records in the pool:** none enter or leave ({pool}).")
    else:
        delta = pool - _pool(base)
        lines.append(
            f"- **Records in the pool:** {_plural(abs(delta), 'record')} "
            f"{'enter' if delta > 0 else 'leave'} it ({_pool(base)} → {pool})."
        )

    invalidated = _rise(head_stages, base_stages, lambda s: _count(s, "stale"))
    revalidated = _fall(head_stages, base_stages, lambda s: _count(s, "stale"))
    line = f"- **Decisions invalidated:** {invalidated}"
    if invalidated:
        leaving = _rise(head_stages, base_stages, lambda s: _count(s, "stale_included"))
        entering = _rise(head_stages, base_stages, _stale_excluded)
        parts = []
        if leaving:
            parts.append(f"{_plural(leaving, 'included paper')} could leave the pool")
        if entering:
            parts.append(f"{_plural(entering, 'excluded paper')} could re-enter it")
        if parts:
            line += " (" + " and ".join(parts) + " once re-screened)"
    if revalidated:
        line += f"; {revalidated} no longer stale"
    lines.append(line + ".")

    opened = _rise(head_stages, base_stages, lambda s: _count(s, "conflicts"))
    closed = _fall(head_stages, base_stages, lambda s: _count(s, "conflicts"))
    lines.append(
        f"- **Screening conflicts opened:** {opened}"
        + (f"; {closed} closed" if closed else "")
        + "."
    )

    if head_stages:
        lines += ["", "| Stage | Included | Excluded | Unscreened | Conflicts | Stale decisions |"]
        lines.append("|---|---:|---:|---:|---:|---:|")
        for name, s in head_stages.items():
            was = base_stages.get(name)
            cells = [
                (_count(was, "included"), _count(s, "included")),
                (_excluded(was), _excluded(s)),
                (
                    _count(was, "unscreened") + _count(was, "partial"),
                    _count(s, "unscreened") + _count(s, "partial"),
                ),
                (_count(was, "conflicts"), _count(s, "conflicts")),
                (_count(was, "stale"), _count(s, "stale")),
            ]
            shown = [_changed(None if was is None else old, now) for old, now in cells]
            lines.append(f"| {name} | " + " | ".join(shown) + " |")

    before = {a["id"]: a.get("state") for a in (base or {}).get("analyses", [])}
    made_stale = [
        a.get("label") or a["id"]
        for a in head.get("analyses", [])
        if a.get("state") in ("stale-data", "stale-tool")
        and before.get(a["id"], "fresh") not in ("stale-data", "stale-tool")
    ]
    if made_stale:
        lines += [
            "",
            f"**Analyses made stale:** {', '.join(made_stale)} (run `strata analyze --all`).",
        ]

    if amendment is not None and amendment.changed:
        lines += ["", "#### Protocol amendment", ""]
        version = ""
        if amendment.version_before is not None and amendment.version_after is not None:
            version = f" (criteria version {amendment.version_before} → {amendment.version_after})"
        lines.append(f"This change edits the review criteria{version}.")
        if amendment.added:
            lines.append(f"- Added: {', '.join(amendment.added)}")
        for criterion_id, fields in amendment.changed_criteria.items():
            lines.append(f"- Changed: {criterion_id} ({', '.join(fields)})")
        if amendment.retired:
            lines.append(f"- Retired: {', '.join(amendment.retired)}")
        if methodologist:
            ask = f" and review is requested from @{methodologist.lstrip('@')}"
        else:
            ask = "; no methodologist is configured, so nobody was asked to review it"
        lines.append(f"It is labelled `protocol-amendment`{ask}.")

    lines += [
        "",
        "<sub>Built from `strata status --json`; the check itself is `strata verify`.</sub>",
    ]
    return "\n".join(lines) + "\n"
