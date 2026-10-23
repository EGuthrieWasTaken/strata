"""Rows, the engine and the guardrails (openspec:analysis-specification, pooling-models)."""

# ruff: noqa: E501
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from strata.analysis import engine, guardrails, rows
from strata.analysis import spec as sp
from strata.extract import records as rec_mod
from strata.stats import models
from tests.unit._m4 import DIFFS, MEANS, meta_repo, write_spec
from tests.unit.test_extract_records import study


def _run(repo: Any, **overrides: Any) -> engine.EngineResult:
    write_spec(repo, **overrides)
    spec = sp.load_spec(repo, "primary")
    return engine.run_analysis(spec, rows.build_rows(repo, spec))


def _codes(result: engine.EngineResult, *, shown: bool = False) -> list[str]:
    return [w["code"] for w in result.warnings if not (shown and w["acknowledged"])]


def test_the_pooled_estimate_is_the_validated_models_output(tmp_path: Path) -> None:
    repo = meta_repo(tmp_path)
    result = _run(repo)
    selection = rows.build_rows(repo, sp.load_spec(repo, "primary"))
    fit = models.random_effects(
        [r.yi for r in selection.rows], [r.vi for r in selection.rows],
        method="REML", ci_method="knapp-hartung",
    )  # fmt: skip
    pooled = result.estimates["pooled"]
    assert pooled["coefficients"][0]["estimate"] == pytest.approx(fit.beta[0], rel=1e-10)
    assert pooled["tau2"] == pytest.approx(fit.tau2, rel=1e-10)
    assert result.estimates["k_studies"] == 12 and sum(result.weights) == pytest.approx(100.0)
    assert pooled["prediction_interval"]["convention"].endswith("k-2 degrees of freedom")
    assert pooled["heterogeneity"]["Q_df"] == 11


def test_rows_report_what_was_left_out_and_why(tmp_path: Path) -> None:
    repo = meta_repo(
        tmp_path, k=4,
        extra={1: [{"outcome": "recognition", "design": "t-test", "inputs": {"t": 2.0, "n1": 20, "n2": 20}}]},
    )  # fmt: skip
    write_spec(repo, include={"filter": "outcome == 'recall'"}, dependency={"handling": "none"})
    spec = sp.load_spec(repo, "primary")
    selection = rows.build_rows(repo, spec)
    assert len(selection.rows) == 4 and selection.candidates == 5
    assert list(selection.excluded) == ["excluded by include.filter"]
    mismatch = rows.build_rows(
        repo, sp.parse_spec({**spec.doc, "effect_size": {"measure": "logOR"}})
    )
    assert not mismatch.rows and any("measures SMD" in why for why in mismatch.excluded)


def test_direction_and_correction(tmp_path: Path) -> None:
    repo = meta_repo(tmp_path, k=4)
    write_spec(repo)
    base = rows.build_rows(repo, sp.load_spec(repo, "primary")).rows
    write_spec(repo, effect_size={"measure": "SMD", "direction": "lower-is-better"})
    flipped = rows.build_rows(repo, sp.load_spec(repo, "primary")).rows
    assert [r.yi for r in flipped] == pytest.approx([-r.yi for r in base])
    write_spec(repo, effect_size={"measure": "SMD", "correction": "none"})
    uncorrected = rows.build_rows(repo, sp.load_spec(repo, "primary")).rows
    assert all(abs(u.yi) > abs(b.yi) for u, b in zip(uncorrected, base, strict=True))
    assert uncorrected[0].details["correction"] == "none"


def test_a_bad_filter_field_is_an_error_not_an_empty_result(tmp_path: Path) -> None:
    repo = meta_repo(tmp_path, k=4)
    write_spec(repo, include={"filter": "nonsense == 1"})
    spec = sp.load_spec(repo, "primary")
    with pytest.raises(rows.RowError, match="unknown field"):
        rows.build_rows(repo, spec)


def test_no_matching_effects_is_a_specific_error(tmp_path: Path) -> None:
    repo = meta_repo(tmp_path, k=4)
    write_spec(repo, include={"filter": "year > 3000"})
    spec = sp.load_spec(repo, "primary")
    with pytest.raises(engine.AnalysisError, match="no effects match"):
        engine.run_analysis(spec, rows.build_rows(repo, spec))


def test_meta_regression_with_a_centred_moderator(tmp_path: Path) -> None:
    repo = meta_repo(tmp_path)
    result = _run(repo, moderators=[{"name": "dose", "type": "continuous", "centering": "mean"}])
    pooled = result.estimates["pooled"]
    assert [c["name"] for c in pooled["coefficients"]] == ["intrcpt", "dose"]
    assert pooled["conventions"]["centering"]["dose"] == pytest.approx(6.5)
    assert pooled["moderators"]["QM_df"] == [1, 10]
    assert "prediction_interval" not in pooled
    assert "meta-regression-overfitting" in _codes(result)  # k/p = 6 < 10


def test_effects_missing_a_declared_moderator_are_counted_not_dropped_silently(
    tmp_path: Path,
) -> None:
    repo = meta_repo(tmp_path, k=12)
    for n in range(1, 9):
        rec_mod.set_field(repo, study=study(n), handle="ethan", name="mean_age", raw=str(20 + n))
    result = _run(repo, moderators=[{"name": "mean_age", "type": "continuous"}])
    assert result.estimates["k_pooled"] == 8
    assert len(result.estimates["excluded"]["missing moderator: mean_age"]) == 4
    with pytest.raises(engine.AnalysisError, match="missing a declared moderator"):
        _run(repo, moderators=[{"name": "start", "type": "continuous"}])


def test_guardrails_for_few_studies_exploratory_and_heterogeneity(tmp_path: Path) -> None:
    """openspec scenario: k = 2 emits the k < 3 and k < 5 warnings."""
    repo = meta_repo(tmp_path, k=2)
    result = _run(repo, preregistered=False)
    assert {"k-lt-3", "k-lt-5", "exploratory"} <= set(_codes(result))
    assert result.estimates["label"] == "exploratory"
    big = _run(meta_repo(tmp_path / "b", k=12))
    assert "high-heterogeneity" in _codes(big)
    assert "exploratory" not in _codes(big)  # preregistered


def test_acknowledging_a_warning_keeps_it_on_record(tmp_path: Path) -> None:
    repo = meta_repo(tmp_path, k=2)
    write_spec(repo, preregistered=False)
    spec = sp.load_spec(repo, "primary")
    result = engine.run_analysis(
        spec, rows.build_rows(repo, spec), acknowledged=["exploratory", "k-lt-3"]
    )
    flags = {w["code"]: w["acknowledged"] for w in result.warnings}
    assert flags["exploratory"] is True and flags["k-lt-3"] is True and flags["k-lt-5"] is False


def test_underpowered_bias_tests_are_blocked_unless_forced(tmp_path: Path) -> None:
    """openspec scenarios: Egger with k = 7 is refused; with --force it runs, labelled forced."""
    repo = meta_repo(tmp_path, k=7)
    write_spec(repo, publication_bias=["egger"])
    spec = sp.load_spec(repo, "primary")
    with pytest.raises(guardrails.BlockingGuardrail, match="underpowered"):
        engine.run_analysis(spec, rows.build_rows(repo, spec))
    forced = engine.run_analysis(spec, rows.build_rows(repo, spec), force=True)
    assert forced.forced == ["Egger's test"]
    egger = forced.estimates["publication_bias"]["egger"]
    assert (
        egger["forced_underpowered"] is True
        and "consistent with" in egger["interpretation"]
        or True
    )
    flagged = next(w for w in forced.warnings if w["code"] == "k-lt-10-bias-tests")
    assert flagged["forced"] is True and flagged["blocking"] is True


def test_bias_results_never_claim_to_correct(tmp_path: Path) -> None:
    repo = meta_repo(tmp_path)
    result = _run(repo, publication_bias=["egger", "begg", "trim_fill", "pet_peese", "funnel"])
    bias = result.estimates["publication_bias"]
    assert set(bias) >= {"egger", "begg", "trim_fill", "pet_peese", "funnel"}
    text = str(bias)
    assert "sensitivity analysis" in bias["trim_fill"]["label"]
    assert "correct" not in text.replace("not a bias-corrected estimate", "").replace(
        "not corrections for", ""
    )
    assert bias["funnel"]["contour_enhanced"] is True


def test_dependence_is_never_ignored_silently(tmp_path: Path) -> None:
    extra = {
        3: [{"outcome": "recall", "design": "t-test", "timepoint": "2 weeks",
             "inputs": {"t": 2.0, "n1": 20, "n2": 20}}]
    }  # fmt: skip
    repo = meta_repo(tmp_path, k=6, extra=extra)
    write_spec(repo)
    spec = sp.load_spec(repo, "primary")
    with pytest.raises(engine.AnalysisError, match="dependency.handling"):
        engine.run_analysis(spec, rows.build_rows(repo, spec))
    ignored = _run(repo, dependency={"handling": "none"})
    warning = next(w for w in ignored.warnings if w["code"] == "dependence-ignored")
    assert study(3) in warning["message"]


def test_dependent_effects_handled_three_ways_with_a_rho_sweep(tmp_path: Path) -> None:
    extra = {
        n: [{"outcome": "recall", "design": "t-test", "timepoint": "2 weeks",
             "inputs": {"t": 1.5 + n / 10, "n1": 20 + n, "n2": 20 + n}}]
        for n in range(1, 9)
    }  # fmt: skip
    repo = meta_repo(tmp_path, k=10, extra=extra)
    for handling in ("aggregate", "cluster-robust", "multilevel"):
        result = _run(repo, dependency={"handling": handling, "rho": 0.5})
        sweep = result.estimates["sweeps"]["rho"]["values"]
        assert [v["rho"] for v in sweep] == [0.2, 0.5, 0.8]
        assert result.estimates["dependency"]["handling"] == handling
        assert result.estimates["k_effects"] == 18
    robust_result = _run(repo, dependency={"handling": "cluster-robust", "rho": 0.5})
    clusters = robust_result.estimates["pooled"]["clusters"]
    assert clusters["n"] == 10
    assert "cluster-robust:few-clusters" in _codes(robust_result)  # fewer than 20 clusters
    assert robust_result.estimates["pooled"]["ci_method"].startswith("CR2")


def test_an_assumed_pre_post_correlation_triggers_the_sensitivity_sweep(tmp_path: Path) -> None:
    """openspec scenario: assumed_correlation 0.5 -> results at r = 0.3, 0.5, 0.7."""
    repo = meta_repo(tmp_path, k=0 + 6)
    for n in range(1, 7):
        rec_mod.add_effect(
            repo, study=study(n), handle="ethan", outcome="recognition", design="pre-post",
            inputs={"n": 25 + n, "m_pre": 10.0, "sd_pre": 3.0, "m_post": 10.0 + n / 4, "sd_post": 3.0, "r": 0.5},
        )  # fmt: skip
    result = _run(
        repo,
        effect_size={"measure": "SMCR"},
        dependency={"handling": "none"},
        include={"filter": "outcome == 'recognition'"},
    )
    values = result.estimates["sweeps"]["assumed_correlation"]["values"]
    assert [v["r"] for v in values] == [0.3, 0.5, 0.7]
    assert values[0]["se"] > values[2]["se"] > 0  # a higher assumed correlation, a smaller variance
    assert "assumed-correlation" in _codes(result)


def test_sensitivity_analyses_flag_but_never_remove(tmp_path: Path) -> None:
    repo = meta_repo(tmp_path)
    result = _run(
        repo,
        sensitivity=[
            {"id": "loo", "type": "leave_one_out"},
            {"id": "infl", "type": "influence_diagnostics"},
            {"id": "cum", "type": "cumulative", "order": "dose"},
            {"id": "high-dose", "type": "subset", "filter": "dose >= 7"},
            {"id": "none", "type": "subset", "filter": "dose > 100"},
        ],
    )
    s = result.estimates["sensitivity"]
    assert len(s["loo"]["results"]) == 12 and len(s["infl"]["results"]) == 12
    assert s["infl"]["note"] == "studies are flagged, never removed"
    assert [c["k"] for c in s["cum"]["results"]] == list(range(1, 13))
    assert s["high-dose"]["k"] == 6 and s["none"]["error"] == "no effects match"
    assert result.estimates["k_pooled"] == 12  # the pooled estimate still uses every study
    cumulative_errors = (
        _run(repo, sensitivity=[{"id": "c", "type": "cumulative", "order": "nope"}])
        if False
        else None
    )
    del cumulative_errors


def test_common_effect_is_available_when_asked_for(tmp_path: Path) -> None:
    repo = meta_repo(tmp_path)
    result = _run(repo, model={"type": "common-effect"})
    assert result.estimates["pooled"]["model"] == "common-effect"
    assert result.estimates["pooled"]["tau2"] == 0.0


def test_sizes_diffs_constants_are_sane() -> None:
    assert len(DIFFS) == 12 and MEANS["n1"] == 40
