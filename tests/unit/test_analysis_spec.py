"""Analysis specifications (openspec:analysis-specification#analysis-specification-file)."""

# ruff: noqa: E501
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from strata.analysis import spec as sp
from tests.unit._m4 import meta_repo, write_spec


def _doc(**overrides: Any) -> dict[str, Any]:
    doc: dict[str, Any] = {"id": "a", "title": "T", "effect_size": {"measure": "SMD"}}
    doc.update(overrides)
    return doc


def test_defaults_follow_current_best_practice() -> None:
    spec = sp.parse_spec(_doc())
    assert spec.section("model") == {
        "type": "random-effects", "tau2_estimator": "REML", "ci_method": "knapp-hartung",
        "level": 0.95,
    }  # fmt: skip
    assert spec.section("effect_size")["correction"] == "hedges"
    assert spec.section("effect_size")["direction"] == "higher-is-better"
    assert spec.preregistered is False and spec.label == "exploratory"
    assert spec.section("heterogeneity") == list(sp.DEFAULT_HETEROGENEITY)
    assert spec.section("dependency")["small_sample_correction"] == "CR2"


def test_a_model_type_omitted_is_random_effects_never_common_effect() -> None:
    """openspec scenario: model.type omitted -> a random-effects model."""
    assert sp.parse_spec(_doc(model={})).section("model")["type"] == "random-effects"


def test_fixed_effect_is_an_alias_and_knapp_hartung_is_dropped_for_it() -> None:
    spec = sp.parse_spec(_doc(model={"type": "fixed-effect"}))
    assert spec.section("model")["type"] == "common-effect"
    assert spec.section("model")["ci_method"] == "wald"
    assert "prediction_interval" not in spec.section("heterogeneity")


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"id": "Bad Id"}, "does not match"),
        ({"effect_size": {"measure": "OR"}}, "is not one of"),
        ({"effect_size": {"measure": "logOR", "correction": "none"}}, "SMD measure only"),
        ({"model": {"type": "bayesian"}}, "is not one of"),
        ({"dependency": {"handling": "aggregate"}}, "dependency.rho"),
        ({"dependency": {"handling": "cluster-robust", "rho": 0.5, "cluster": "site"}}, "study_id"),
        (
            {"model": {"type": "common-effect"}, "dependency": {"handling": "multilevel", "rho": 0.5}},
            "common-effect",
        ),
        ({"include": {"filter": "year >"}}, "invalid filter"),
        ({"sensitivity": [{"id": "s", "type": "subset"}]}, "needs a filter"),
        (
            {
                "sensitivity": [
                    {"id": "s", "type": "leave_one_out"},
                    {"id": "s", "type": "cumulative"},
                ]
            },
            "unique",
        ),
        ({"moderators": [{"name": "a", "type": "continuous"}] * 2}, "unique"),
        ({"unexpected": 1}, "Additional properties"),
    ],
)  # fmt: skip
def test_invalid_specifications_are_refused_with_specific_messages(
    overrides: dict[str, Any], message: str
) -> None:
    with pytest.raises(sp.AnalysisSpecError, match=message):
        sp.parse_spec(_doc(**overrides))


def test_unsupported_models_point_at_the_export_and_the_metafor_engine() -> None:
    with pytest.raises(sp.AnalysisSpecError, match="strata export effects"):
        sp.parse_spec(
            _doc(dependency={"handling": "cluster-robust", "rho": 0.5, "cluster": "site"})
        )


def test_a_non_mapping_is_rejected() -> None:
    with pytest.raises(sp.AnalysisSpecError, match="mapping"):
        sp.parse_spec(["not", "a", "mapping"])


def test_loading_from_the_repository(tmp_path: Path) -> None:
    repo = meta_repo(tmp_path, k=3)
    assert sp.list_analyses(repo) == []
    write_spec(repo, "primary")
    write_spec(repo, "second")
    assert sp.list_analyses(repo) == ["primary", "second"]
    assert sp.load_spec(repo, "primary").title.startswith("Effect of spaced practice")
    with pytest.raises(sp.AnalysisSpecError, match="no analysis"):
        sp.load_spec(repo, "nope")
    repo.path("analysis", "mismatch.yaml").write_text(
        repo.path("analysis", "primary.yaml").read_text(), encoding="utf-8"
    )
    with pytest.raises(sp.AnalysisSpecError, match="must match the file name"):
        sp.load_spec(repo, "mismatch")
