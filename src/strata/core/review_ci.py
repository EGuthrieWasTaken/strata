"""Pool-impact comment for review-repository pull requests.

openspec:review-repository-ci#pool-impact-comment and
openspec:review-repository-ci#protocol-amendment-detection. Pure functions over two
`strata --json status` payloads (the base branch and the pull request); only `main` does I/O.
"""

from __future__ import annotations

import json
import sys
from typing import Any

MARKER = "<!-- strata-pool-impact -->"


def criteria_changed(base: dict[str, Any], head: dict[str, Any]) -> bool:
    base_v = int(base.get("criteria_version", 0))
    head_v = int(head.get("criteria_version", 0))
    return base_v != head_v


def render_pool_impact_comment(base: dict[str, Any], head: dict[str, Any]) -> str:
    b_count = base.get("record_count", 0)
    h_count = head.get("record_count", 0)
    entered = max(h_count - b_count, 0)
    left = max(b_count - h_count, 0)

    base_stages = {s.get("stage"): s for s in base.get("stages", [])}
    invalidated_map: dict[str, int] = {}
    opened_map: dict[str, int] = {}

    total_invalidated = 0
    total_opened = 0

    for h_stage in head.get("stages", []):
        name = h_stage.get("stage")
        if not name:
            continue
        b_stage = base_stages.get(name, {"stale": 0, "conflicts": 0})

        new_stale = max(h_stage.get("stale", 0) - b_stage.get("stale", 0), 0)
        new_conflicts = max(h_stage.get("conflicts", 0) - b_stage.get("conflicts", 0), 0)

        invalidated_map[name] = new_stale
        opened_map[name] = new_conflicts
        total_invalidated += new_stale
        total_opened += new_conflicts

    criteria_changed_bool = criteria_changed(base, head)

    if not criteria_changed_bool and entered == left == total_invalidated == total_opened == 0:
        return (
            f"{MARKER}\n"
            "### strata: effect of this change on the review\n\n"
            "No effect on the records, decisions, or conflicts.\n"
        )

    lines = [MARKER, "### strata: effect of this change on the review", ""]

    if criteria_changed_bool:
        v_base = base.get("criteria_version", 0)
        v_head = head.get("criteria_version", 0)
        lines.append(f"- **Protocol amendment:** criteria v{v_base} → v{v_head}")

    lines.append(f"- **Records:** {b_count} → {h_count} ({entered} entered, {left} left)")

    lines.append(f"- **Decisions invalidated:** {total_invalidated}")
    for name, count in invalidated_map.items():
        if count > 0:
            lines.append(f"  - {name}: {count}")

    lines.append(f"- **Conflicts opened:** {total_opened}")
    for name, count in opened_map.items():
        if count > 0:
            lines.append(f"  - {name}: {count}")

    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    if not argv or argv[0] not in ("comment", "criteria-changed"):
        sys.stderr.write(
            "Usage: comment <base.json> <head.json> | criteria-changed <base.json> <head.json>\n"
        )
        return 2

    subcommand = argv[0]
    if len(argv) != 3:
        sys.stderr.write(
            "Usage: comment <base.json> <head.json> | criteria-changed <base.json> <head.json>\n"
        )
        return 2

    try:
        with open(argv[1], encoding="utf-8") as f:
            base = json.load(f)
        with open(argv[2], encoding="utf-8") as f:
            head = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        sys.stderr.write(f"Error reading files: {e}\n")
        return 2

    if subcommand == "comment":
        sys.stdout.write(render_pool_impact_comment(base, head))
    else:
        sys.stdout.write(str(criteria_changed(base, head)).lower() + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
