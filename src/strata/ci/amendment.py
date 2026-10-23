"""Protocol-amendment detection: did a pull request change the criteria?

Implements openspec:review-repository-ci#protocol-amendment-detection. The criteria are read from
the two commits with `git show`, so the answer does not depend on the working tree, and compared as
data (formatting-only edits are not an amendment).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from strata import gitio
from strata.core.canon import load_yaml_str

CRITERIA_PATH = "protocol/criteria.yaml"
_FIELDS = ("kind", "label", "definition", "applies_at", "status")


@dataclass
class Amendment:
    """What a change did to the review criteria."""

    changed: bool
    version_before: int | None = None
    version_after: int | None = None
    added: list[str] = field(default_factory=list)
    changed_criteria: dict[str, list[str]] = field(default_factory=dict)  # id -> fields
    retired: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "changed": self.changed,
            "version_before": self.version_before,
            "version_after": self.version_after,
            "added": self.added,
            "changed_criteria": self.changed_criteria,
            "retired": self.retired,
        }


def _criteria_at(root: Path, ref: str) -> dict[str, Any] | None:
    result = gitio.run(["show", f"{ref}:{CRITERIA_PATH}"], cwd=root, check=False)
    if result.returncode != 0:
        return None
    data = load_yaml_str(result.stdout)
    return data if isinstance(data, dict) else None


def compare(before: dict[str, Any] | None, after: dict[str, Any] | None) -> Amendment:
    """The amendment between two parsed criteria files (either may be absent)."""
    old = {c["id"]: c for c in (before or {}).get("criteria", []) or []}
    new = {c["id"]: c for c in (after or {}).get("criteria", []) or []}
    added = sorted(new.keys() - old.keys())
    changed: dict[str, list[str]] = {}
    retired: list[str] = []
    for criterion_id in sorted(new.keys() & old.keys()):
        fields = [
            name for name in _FIELDS if old[criterion_id].get(name) != new[criterion_id].get(name)
        ]
        if not fields:
            continue
        if fields == ["status"] and new[criterion_id].get("status") == "retired":
            retired.append(criterion_id)
        else:
            changed[criterion_id] = fields
    removed = sorted(old.keys() - new.keys())  # not something strata does; report it all the same
    if removed:
        retired.extend(removed)
    return Amendment(
        changed=bool(added or changed or retired),
        version_before=(before or {}).get("version"),
        version_after=(after or {}).get("version"),
        added=added,
        changed_criteria=changed,
        retired=sorted(retired),
    )


def detect(root: Path, base: str, head: str) -> Amendment:
    """Compare the criteria at `base` and `head` in the repository at `root`."""
    return compare(_criteria_at(root, base), _criteria_at(root, head))
