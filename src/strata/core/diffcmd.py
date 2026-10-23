"""`strata diff <ref>..<ref>`: a domain-level diff between two points in history.

Implements openspec:provenance-queries#strata-diff. Each side is exported from git (no checkout, no
index) and folded by the same code that answers `strata status`, so a count here is the count the
dashboard would have shown at that commit. Committed analysis results are read as files, which is
what lets a protocol change show up as a pooled estimate moving.
"""

from __future__ import annotations

import json
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from strata import gitio
from strata.core import records as records_mod
from strata.core import status as status_mod
from strata.core.repo import Repo, load_config
from strata.protocol import criteria as criteria_mod
from strata.protocol import rescreen as rescreen_mod
from strata.protocol import screening as screening_mod
from strata.protocol import studies as studies_mod


class DiffError(ValueError):
    pass


@dataclass
class Snapshot:
    ref: str
    commit: str
    criteria_version: int
    records_identified: int
    duplicates: int
    pools: dict[str, tuple[frozenset[str], frozenset[str]]]
    studies: int
    estimates: dict[str, dict[str, Any]]
    criteria_changes: list[dict[str, Any]]


@dataclass
class PoolChange:
    stage: str
    before: int
    after: int
    entered: int
    left: int


@dataclass
class EstimateChange:
    analysis: str
    status: str  # changed | unchanged | added | removed
    before: dict[str, Any] | None
    after: dict[str, Any] | None


@dataclass
class Diff:
    base: str
    head: str
    base_commit: str
    head_commit: str
    criteria_versions: tuple[int, int]
    criteria_deltas: dict[str, int]
    records_identified: tuple[int, int]
    duplicates: tuple[int, int]
    pools: list[PoolChange]
    studies: tuple[int, int]
    analyses: list[EstimateChange] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


def parse_range(text: str) -> tuple[str, str]:
    """`a..b`; either side may be empty (HEAD), and a lone ref means `ref..HEAD`."""
    if "..." in text:
        raise DiffError("use <ref>..<ref>; three-dot ranges are not supported")
    left, sep, right = text.partition("..")
    if not sep:
        return text, "HEAD"
    return left or "HEAD", right or "HEAD"


def _summary(estimates: dict[str, Any]) -> dict[str, Any]:
    pooled = estimates.get("pooled", {})
    first = pooled.get("coefficients", [{}])[0]
    het = pooled.get("heterogeneity") or {}
    back = estimates.get("back_transformed")
    shown = back if back else first
    return {
        "measure": estimates.get("measure"),
        "scale": back["scale"] if back else estimates.get("measure"),
        "estimate": shown.get("estimate"),
        "ci_lb": shown.get("ci_lb"),
        "ci_ub": shown.get("ci_ub"),
        "I2": het.get("I2"),
        "tau2": het.get("tau2"),
        "k_studies": estimates.get("k_studies"),
        "k_effects": estimates.get("k_effects"),
    }


def _committed_estimates(root: Path) -> dict[str, dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    for path in sorted(root.glob("analysis/results/*/estimates.json")):
        try:
            found[path.parent.name] = _summary(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError, KeyError, IndexError):
            continue
    return found


def _stage_pools(repo: Repo) -> dict[str, tuple[frozenset[str], frozenset[str]]]:
    """For each stage, the records that entered it and the ones it included."""
    canonical = sorted(
        r["id"]
        for r in records_mod.read_records(repo)
        if r.get("strata", {}).get("canonical", True)
    )
    stale: dict[str, set[str]] = {}
    for item in rescreen_mod.compute_stale_records(repo):
        stale.setdefault(item.record_id, set()).add(item.stage)
    pools: dict[str, tuple[frozenset[str], frozenset[str]]] = {}
    entering = frozenset(canonical)
    for stage in screening_mod.configured_stages(repo):
        _, included = status_mod._compute_stage_status(repo, stage, canonical, stale)
        pools[stage] = (entering, frozenset(included))
        entering = frozenset(included)
    return pools


def snapshot(source: Repo, ref: str) -> Snapshot:
    """Fold the repository as it stood at `ref`."""
    try:
        commit = gitio.resolve_commit(source.root, ref)
    except gitio.GitError as exc:
        raise DiffError(f"unknown revision: {ref}") from exc
    with tempfile.TemporaryDirectory(prefix="strata-diff-") as tmp:
        root = Path(tmp)
        gitio.export_tree(source.root, commit, root)
        if not (root / "strata.toml").is_file():
            raise DiffError(f"{ref} is not a strata repository (no strata.toml)")
        repo = Repo(root=root, config=load_config(root))
        records = records_mod.read_records(repo)
        duplicates = sum(1 for r in records if not r.get("strata", {}).get("canonical", True))
        return Snapshot(
            ref=ref,
            commit=commit,
            criteria_version=status_mod._read_criteria_version(repo),
            records_identified=len(records),
            duplicates=duplicates,
            pools=_stage_pools(repo),
            studies=len(studies_mod.study_map(repo).members),
            estimates=_committed_estimates(root),
            criteria_changes=[e["body"] for e in criteria_mod.all_criteria_change_events(repo)],
        )


def _criteria_deltas(before: Snapshot, after: Snapshot) -> dict[str, int]:
    """Counts of what the criteria changes between the two versions did."""
    counts = {"added": 0, "tightened": 0, "loosened": 0, "both": 0, "editorial": 0, "retired": 0}
    for change in after.criteria_changes:
        if not before.criteria_version < int(change["to_version"]) <= after.criteria_version:
            continue
        for delta in change["deltas"]:
            if delta["origin"] == "added":
                counts["added"] += 1
            elif delta["origin"] == "retired":
                counts["retired"] += 1
            elif delta["direction"] in counts:
                counts[delta["direction"]] += 1
    return counts


def _estimate_changes(before: Snapshot, after: Snapshot) -> list[EstimateChange]:
    changes = []
    for analysis in sorted(set(before.estimates) | set(after.estimates)):
        old, new = before.estimates.get(analysis), after.estimates.get(analysis)
        if old is None:
            status = "added"
        elif new is None:
            status = "removed"
        else:
            status = "unchanged" if old == new else "changed"
        changes.append(EstimateChange(analysis, status, old, new))
    return changes


def diff_refs(source: Repo, base: str, head: str) -> Diff:
    before, after = snapshot(source, base), snapshot(source, head)
    pools = []
    for stage in screening_mod.configured_stages(source):
        was_in = before.pools.get(stage, (frozenset(), frozenset()))[0]
        now_in = after.pools.get(stage, (frozenset(), frozenset()))[0]
        pools.append(
            PoolChange(stage, len(was_in), len(now_in), len(now_in - was_in), len(was_in - now_in))
        )
    return Diff(
        base=base,
        head=head,
        base_commit=before.commit,
        head_commit=after.commit,
        criteria_versions=(before.criteria_version, after.criteria_version),
        criteria_deltas=_criteria_deltas(before, after),
        records_identified=(before.records_identified, after.records_identified),
        duplicates=(before.duplicates, after.duplicates),
        pools=pools,
        studies=(before.studies, after.studies),
        analyses=_estimate_changes(before, after),
    )
