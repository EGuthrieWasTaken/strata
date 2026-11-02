"""The nightly drift comparison tolerates float noise and catches real change."""

from __future__ import annotations

import json
from pathlib import Path

from tests.statistical import compare_fixtures as cf

FIXTURES = Path(__file__).parent / "fixtures"


def _write(directory: Path, name: str, doc: object) -> None:
    directory.mkdir(exist_ok=True)
    (directory / name).write_text(json.dumps(doc), encoding="utf-8")


def test_the_committed_fixtures_do_not_drift_from_themselves() -> None:
    assert cf.compare(FIXTURES, FIXTURES) == []


def test_last_digit_noise_is_tolerated_but_a_real_move_is_not(tmp_path: Path) -> None:
    _write(tmp_path / "a", "x.json", {"beta": [0.123456789012345678], "tau2": 0.5, "n": 3})
    _write(tmp_path / "b", "x.json", {"beta": [0.123456789012346], "tau2": 0.5, "n": 3})
    assert cf.compare(tmp_path / "a", tmp_path / "b") == []
    _write(tmp_path / "c", "x.json", {"beta": [0.12345679], "tau2": 0.5, "n": 3})
    moved = cf.compare(tmp_path / "a", tmp_path / "c")
    assert moved and "$.beta[0]" in moved[0]


# The three values the first live run (metafor 5.2-1 against the committed 4.4.0 fixtures) moved, as
# the nightly job printed them: all in the CHE fit at rho = 0.5, all a consequence of sigma2[0].
LIVE_RUN = {
    "pval": (0.0018734848821053132, 0.001873484880004563),
    "se": (0.09907245035204593, 0.09907245046520247),
    "sigma2": (0.09342191919029687, 0.09342191953851858),
}


def _che(which: int, **scale: float) -> dict[str, object]:
    """A dependence.json with the CHE fit's live-run values (`which` 0: committed, 1: fresh)."""
    cr2 = {"pval": [LIVE_RUN["pval"][which] * scale.get("pval", 1.0)]}
    return {
        "assink_che": {
            "results": {
                "0.5": {
                    "se": [LIVE_RUN["se"][which] * scale.get("se", 1.0)],
                    "sigma2": [LIVE_RUN["sigma2"][which], 0.14574129013917528],
                    "cr2": cr2,
                }
            }
        }
    }


def test_optimizer_noise_in_the_multilevel_fit_is_not_drift(tmp_path: Path) -> None:
    """The nightly job failed on exactly these three numbers (1e-9 to 4e-9 relative). `rma.mv`
    fixes its variance components only to about 1e-7, so they are not a change in `metafor`."""
    _write(tmp_path / "a", "dependence.json", _che(0))
    _write(tmp_path / "b", "dependence.json", _che(1))
    assert cf.compare(tmp_path / "a", tmp_path / "b") == []
    # ... and they are past the strict tolerance, so it is the per-fit tolerance that lets them by.
    strict = cf.differences(_che(0), _che(1))
    assert len(strict) == 3 and all("became" in line for line in strict)


def test_a_real_move_in_the_multilevel_fit_is_still_drift(tmp_path: Path) -> None:
    """Looser is not blind: 1e-5 is the suite's tolerance for the variance components, ten times
    the tolerance used here."""
    _write(tmp_path / "a", "dependence.json", _che(0))
    _write(tmp_path / "b", "dependence.json", _che(0, se=1 + 1e-5))
    moved = cf.compare(tmp_path / "a", tmp_path / "b")
    assert len(moved) == 1 and "$.assink_che.results.0.5.se[0]" in moved[0]


def test_the_looser_tolerance_covers_only_the_optimizer_fits(tmp_path: Path) -> None:
    """The same 4e-9 wobble in a closed-form value (aggregation), or in another file, is drift."""
    wobble = 1 + 4e-9
    for name, key in (("dependence.json", "assink_aggregate"), ("pooling.json", "assink_che")):
        _write(tmp_path / "a", name, {key: {"yi": [0.25]}})
        _write(tmp_path / "b", name, {key: {"yi": [0.25 * wobble]}})
        moved = cf.compare(tmp_path / "a", tmp_path / "b")
        assert len(moved) == 1 and f"$.{key}.yi[0]" in moved[0], (name, key)
        for stale in ("a", "b"):
            (tmp_path / stale / name).unlink()


def test_every_optimizer_fit_named_here_is_in_its_committed_fixture() -> None:
    """A renamed fixture key would otherwise quietly put its fit back on the strict tolerance."""
    for name, keys in cf.OPTIMIZER_FITS.items():
        committed = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
        assert set(keys) <= set(committed), (name, keys)


def test_structure_changes_are_reported(tmp_path: Path) -> None:
    _write(tmp_path / "a", "x.json", {"k": [1, 2, 3], "name": "REML", "gone": 1})
    _write(tmp_path / "b", "x.json", {"k": [1, 2], "name": "ML", "new": 1})
    _write(tmp_path / "b", "extra.json", {})
    _write(tmp_path / "a", "missing.json", {})
    lines = "\n".join(cf.compare(tmp_path / "a", tmp_path / "b"))
    for expected in ("length 3 became 2", "'REML' became 'ML'", "$.gone: missing", "$.new: new",
                     "extra.json: a new fixture", "missing.json: not regenerated"):  # fmt: skip
        assert expected in lines


def test_the_command_reports_drift_with_a_nonzero_exit(tmp_path: Path) -> None:
    _write(tmp_path / "a", "x.json", {"v": 1.0})
    _write(tmp_path / "b", "x.json", {"v": 2.0})
    assert cf.main(["compare", str(tmp_path / "a"), str(tmp_path / "a")]) == 0
    assert cf.main(["compare", str(tmp_path / "a"), str(tmp_path / "b")]) == 1
    assert cf.main(["compare"]) == 2
