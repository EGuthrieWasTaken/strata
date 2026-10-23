"""Acceptance tests for strata.extract.quality (openspec:data-extraction#data-quality-guards)."""

from __future__ import annotations

import pytest

from strata.extract import quality

PEERS = [2.0, 2.5, 3.0]  # median 2.5 -> fine range is [2.5/3, 7.5]


def test_codes_are_the_six_guards() -> None:
    assert quality.CODES == (
        "sd-outlier",
        "large-effect",
        "zero-cell",
        "n-inconsistent",
        "p-derived",
        "stat-p-inconsistent",
    )


def test_warning_is_frozen() -> None:
    warning = quality.check_large_effect(4.2)
    assert warning is not None
    with pytest.raises(AttributeError):
        warning.code = "other"  # type: ignore[misc]


@pytest.mark.parametrize("sd", [10.0, 7.6, 0.5, 0.0])
def test_sd_outliers_warn(sd: float) -> None:
    warning = quality.check_sd_outlier(sd, PEERS)
    assert warning is not None
    assert warning.code == "sd-outlier"
    assert warning.message


@pytest.mark.parametrize("sd", [2.5, 4.0, 7.5, 0.9])
def test_sd_within_range_is_fine(sd: float) -> None:
    assert quality.check_sd_outlier(sd, PEERS) is None


def test_sd_needs_at_least_two_peers() -> None:
    assert quality.check_sd_outlier(100.0, []) is None
    assert quality.check_sd_outlier(100.0, [2.0]) is None


def test_sd_with_non_positive_peer_median_is_ignored() -> None:
    assert quality.check_sd_outlier(5.0, [0.0, 0.0, 0.0]) is None


def test_large_effect() -> None:
    assert quality.check_large_effect(3.0) is None
    assert quality.check_large_effect(-3.0) is None
    assert quality.check_large_effect(0.4) is None
    for g in (3.01, -3.01, 4.2):
        warning = quality.check_large_effect(g)
        assert warning is not None
        assert warning.code == "large-effect"
    warning = quality.check_large_effect(4.2)
    assert warning is not None
    assert "4.2" in warning.message


def test_zero_cell_warns_and_explains_the_correction() -> None:
    for args in [(0, 20, 5, 20), (20, 20, 5, 20), (3, 20, 0, 20), (3, 20, 20, 20)]:
        warning = quality.check_zero_cell(*args)
        assert warning is not None, args
        assert warning.code == "zero-cell"
        assert "0.5" in warning.message


def test_no_zero_cell_is_fine() -> None:
    assert quality.check_zero_cell(3, 20, 5, 20) is None


@pytest.mark.parametrize("args", [(-1, 20, 5, 20), (21, 20, 5, 20), (3, 20, -2, 20), (3, 20, 6, 5)])
def test_zero_cell_rejects_impossible_counts(args: tuple[int, int, int, int]) -> None:
    with pytest.raises(ValueError):
        quality.check_zero_cell(*args)


def test_n_consistency() -> None:
    assert quality.check_n_consistency(148, [74, 74]) is None
    assert quality.check_n_consistency(None, [74, 74]) is None
    assert quality.check_n_consistency(148, []) is None
    warning = quality.check_n_consistency(148, [74, 73])
    assert warning is not None
    assert warning.code == "n-inconsistent"
    assert "147" in warning.message
    assert "148" in warning.message


def test_p_derived() -> None:
    warning = quality.check_p_derived("p-value-only")
    assert warning is not None
    assert warning.code == "p-derived"
    assert quality.check_p_derived("two-group-means") is None


# Reference values from scipy.stats: 2*t.sf(2.20, 30) = 0.035648, 2*t.sf(2.00, 20) = 0.059266,
# f.sf(4.0, 2, 30) = 0.028845, f.sf(3.5, 1, 40) = 0.068697.
@pytest.mark.parametrize(
    ("t", "df", "p"),
    [(2.20, 30, 0.036), (2.00, 20, 0.059), (-2.20, 30, 0.036), (2.20, 30, 0.035), (2.0, 20, 0.06)],
)
def test_t_consistent_with_p(t: float, df: float, p: float) -> None:
    assert quality.check_t_p(t, df, p) is None


@pytest.mark.parametrize(
    ("t", "df", "p"), [(2.20, 30, 0.05), (2.00, 20, 0.05), (2.20, 30, 0.01), (2.20, 30, 0.9)]
)
def test_t_inconsistent_with_p(t: float, df: float, p: float) -> None:
    warning = quality.check_t_p(t, df, p)
    assert warning is not None
    assert warning.code == "stat-p-inconsistent"
    assert warning.message


def test_t_p_decimals_widen_the_tolerance() -> None:
    assert quality.check_t_p(2.0, 20, 0.06, p_decimals=2) is None
    assert quality.check_t_p(2.0, 20, 0.05, p_decimals=2) is not None
    assert quality.check_t_p(2.0, 20, 0.05, p_decimals=1) is None


def test_t_zero_statistic_has_p_one() -> None:
    assert quality.check_t_p(0.0, 10, 1.0) is None
    assert quality.check_t_p(0.0, 10, 0.5) is not None


@pytest.mark.parametrize("args", [(2.2, 0, 0.04), (2.2, -3, 0.04), (2.2, 30, 1.5), (2.2, 30, -0.1)])
def test_t_p_rejects_impossible_inputs(args: tuple[float, float, float]) -> None:
    with pytest.raises(ValueError):
        quality.check_t_p(*args)


@pytest.mark.parametrize(("f", "df1", "df2", "p"), [(4.0, 2, 30, 0.029), (3.5, 1, 40, 0.069)])
def test_f_consistent_with_p(f: float, df1: float, df2: float, p: float) -> None:
    assert quality.check_f_p(f, df1, df2, p) is None


@pytest.mark.parametrize(
    ("f", "df1", "df2", "p"),
    [(4.0, 2, 30, 0.01), (3.5, 1, 40, 0.04), (3.5, 1, 40, 0.5), (4.0, 2, 30, 0.028)],
)
def test_f_inconsistent_with_p(f: float, df1: float, df2: float, p: float) -> None:
    warning = quality.check_f_p(f, df1, df2, p)
    assert warning is not None
    assert warning.code == "stat-p-inconsistent"


@pytest.mark.parametrize("args", [(4.0, 0, 30, 0.03), (4.0, 2, 0, 0.03), (4.0, 2, 30, 2.0)])
def test_f_p_rejects_impossible_inputs(args: tuple[float, float, float, float]) -> None:
    with pytest.raises(ValueError):
        quality.check_f_p(*args)
