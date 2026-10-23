"""Builders for analysis tests: a review with extracted effects and an analysis specification."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from strata.core.canon import dump_yaml_str
from strata.core.repo import Repo
from strata.extract import records as rec_mod
from tests.unit.test_extract_records import _review, study

MEANS = {"n1": 40, "m1": 0.62, "sd1": 0.18, "n2": 40, "m2": 0.48, "sd2": 0.21}

# Twelve small studies with a spread of effects (m1 - m2) and the same sampling design.
DIFFS = [0.30, 0.05, 0.22, 0.41, 0.12, 0.35, 0.18, 0.50, 0.08, 0.27, 0.15, 0.33]


def meta_repo(
    tmp_path: Path, *, k: int = 12, extra: dict[int, list[dict[str, Any]]] | None = None
) -> Repo:
    """`k` included studies, each with one two-group-means SMD effect (and `extra` further
    effects by study number), committed state not required."""
    repo = _review(tmp_path, studies=k)
    for n in range(1, k + 1):
        diff = DIFFS[(n - 1) % len(DIFFS)]
        inputs = {**MEANS, "m1": 0.5 + diff, "m2": 0.5, "n1": 30 + n, "n2": 30 + n}
        rec_mod.set_field(
            repo, study=study(n), handle="ethan", name="n_total", raw=str(2 * (30 + n))
        )
        rec_mod.set_field(repo, study=study(n), handle="ethan", name="design", raw="rct")
        rec_mod.set_field(
            repo, study=study(n), handle="ethan", name="retention_interval", raw=f"{n} days"
        )
        rec_mod.add_effect(
            repo, study=study(n), handle="ethan", outcome="recall", design="two-group-means",
            inputs=inputs, timepoint="1 week", moderators={"dose": n},
        )  # fmt: skip
        for extra_effect in (extra or {}).get(n, []):
            rec_mod.add_effect(repo, study=study(n), handle="ethan", **extra_effect)
    return repo


def write_spec(repo: Repo, analysis_id: str = "primary", **overrides: Any) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "id": analysis_id,
        "title": "Effect of spaced practice on recall",
        "preregistered": True,
        "effect_size": {"measure": "SMD"},
        "model": {"type": "random-effects", "tau2_estimator": "REML", "ci_method": "knapp-hartung"},
    }
    doc.update(overrides)
    repo.path("analysis").mkdir(exist_ok=True)
    repo.path("analysis", f"{analysis_id}.yaml").write_text(dump_yaml_str(doc), encoding="utf-8")
    return doc
