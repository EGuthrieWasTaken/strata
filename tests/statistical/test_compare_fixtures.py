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
