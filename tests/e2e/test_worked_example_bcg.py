"""The BCG worked example (`examples/bcg-vaccine/`), rebuilt through the command line and held to
the published analysis and to its committed results (add-distribution-and-adoption task 3.1)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from strata.core.repo import open_repo
from strata.core.verify import verify_repository

EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "bcg-vaccine"


def _build(target: Path) -> Path:
    spec = importlib.util.spec_from_file_location("bcg_build", EXAMPLE / "build.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    root = target / "review"
    module.build(root)
    return root


@pytest.fixture(scope="module")
def review(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return _build(tmp_path_factory.mktemp("bcg"))


def _estimates(root: Path, analysis: str) -> dict:  # type: ignore[type-arg]
    return json.loads(
        (root / "analysis" / "results" / analysis / "estimates.json").read_text(encoding="utf-8")
    )


def test_the_pooled_risk_ratio_is_the_published_one(review: Path) -> None:
    estimates = _estimates(review, "primary")
    (coefficient,) = estimates["pooled"]["coefficients"]
    assert estimates["k_studies"] == 13
    assert coefficient["estimate"] == pytest.approx(-0.7145, abs=5e-5)
    assert coefficient["se"] == pytest.approx(0.1798, abs=5e-5)
    assert (coefficient["ci_lb"], coefficient["ci_ub"]) == pytest.approx(
        (-1.0669, -0.3622), abs=5e-5
    )
    assert estimates["pooled"]["heterogeneity"]["tau2"] == pytest.approx(0.3132, abs=5e-5)
    assert estimates["pooled"]["heterogeneity"]["Q"] == pytest.approx(152.233, abs=5e-3)
    assert estimates["back_transformed"]["estimate"] == pytest.approx(0.489, abs=5e-4)


def test_latitude_explains_most_of_the_heterogeneity_as_published(review: Path) -> None:
    estimates = _estimates(review, "latitude")
    by_name = {c["name"]: c for c in estimates["pooled"]["coefficients"]}
    assert by_name["intrcpt"]["estimate"] == pytest.approx(0.2515, abs=5e-4)
    assert by_name["ablat"]["estimate"] == pytest.approx(-0.0291, abs=5e-5)
    assert estimates["pooled"]["heterogeneity"]["tau2"] == pytest.approx(0.0764, abs=5e-4)


@pytest.mark.parametrize(
    "path",
    sorted(str(p.relative_to(EXAMPLE / "results")) for p in (EXAMPLE / "results").rglob("*")
           if p.is_file()),
)  # fmt: skip
def test_a_rebuild_reproduces_the_committed_results(review: Path, path: str) -> None:
    built = review / path if path.startswith("reports/") else review / "analysis" / "results" / path
    assert built.read_bytes() == (EXAMPLE / "results" / path).read_bytes()


def test_the_rebuilt_review_verifies(review: Path) -> None:
    report = verify_repository(open_repo(review))
    assert report.ok, report.issues
