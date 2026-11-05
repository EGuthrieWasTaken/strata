"""The tests that compare two reviews do not depend on the clock.

An import, a retrieval, a search and `strata init` stamp the day on what they commit. The
equivalence tests build two identical reviews one after the other and compare what each recorded, so
a run that crossed 00:00 UTC between the two builds recorded two different days and failed with
nothing wrong (CI run 41928702528: `"retrieved":"2026-11-04"` against `"retrieved":"2026-11-05"`).
The `same_day` fixture holds the day still for the whole test (`tests/integration/_equivalence.py`).

These tests stand a clock that a test moves in the place of the real one, and move it past midnight
between the two builds: without the pin the two reviews record different days (so the failure is
reproduced, not assumed), and with it they record the same one.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from importlib import import_module
from pathlib import Path

import pytest
from typer.testing import CliRunner

import strata
from strata import gitio
from strata.cli.main import EXIT_OK, app
from strata.core import operations as ops
from strata.core import records as records_mod
from strata.core.ids import report_id
from tests.integration._equivalence import (
    DAY_STAMPS,
    OTHER_CLOCKS,
    PINNED_DAY,
    committed_snapshot,
    install_clock,
    mask,
    pin_day,
)
from tests.unit._m3 import decide, init_review

runner = CliRunner()
_WHY = "recorded for the test of the clock"
_PAPERS = json.dumps(
    [
        {"title": "First paper", "DOI": "10.1000/aaa"},
        {"title": "Second paper", "DOI": "10.1000/bbb"},
    ]
)
_SEARCHED_ON = "2026-03-04"  # given, not read from the clock
_DAY = re.compile(r"\d{4}-\d{2}-\d{2}")
_BEFORE_MIDNIGHT = datetime(2026, 11, 4, 23, 59, 50, tzinfo=UTC)


class _Wall:
    """The real clock, as a test sees it: still until it is moved."""

    def __init__(self) -> None:
        self.now = _BEFORE_MIDNIGHT

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **delta: float) -> None:
        self.now += timedelta(**delta)


def _build(tmp_path: Path, name: str) -> Path:
    """A review taken through every action that stamps a day: `init`, a search, an import and a
    retrieval."""
    home = tmp_path / name
    home.mkdir()
    repo = init_review(home)
    ops.record_search(
        repo,
        database="MEDLINE",
        platform="Ovid",
        executed=_SEARCHED_ON,
        executed_by="ethan",
        query="q",
        rationale=_WHY,
    )
    export = home / "export.json"  # beside the review, and named alike in both
    export.write_text(_PAPERS, encoding="utf-8")
    ops.import_file(repo, export, imported_by="ethan", search_id="S-01-medline", rationale=_WHY)
    ids = [r["id"] for r in records_mod.read_records(repo)]
    decide(repo, "title-abstract", ids)
    gitio.add_all(repo.root)
    gitio.commit(repo.root, "test: fixture\n\nStrata-Op: test\nStrata-Actor: ethan")
    result = runner.invoke(
        app,
        ["--why", _WHY, "-C", str(repo.root), "retrieve", "--by", "ethan"]
        + ["--report", report_id(ids[0]), "--outcome", "retrieved"]
        + ["--source", "institutional-access", "--version", "version-of-record"],
    )
    assert result.exit_code == EXIT_OK, result.output
    return repo.root


def _days_recorded(root: Path) -> set[str]:
    """Every day the review's committed files carry, other than the one it was given."""
    found: set[str] = set()
    for name in gitio.run(["ls-files"], cwd=root).stdout.splitlines():
        text = (root / name).read_text(encoding="utf-8", errors="replace")
        found.update(_DAY.findall(mask(text)))  # a timestamp is masked: it is not a day stamped
    return found - {_SEARCHED_ON}


def test_without_the_pin_a_review_built_after_midnight_records_the_next_day(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    wall = _Wall()
    install_clock(monkeypatch, wall)

    before = _build(tmp_path, "before")
    wall.advance(minutes=1)
    after = _build(tmp_path, "after")

    # This is the failure the pin removes: the same actions, recorded on two different days.
    assert _days_recorded(before) == {"2026-11-04"}
    assert _days_recorded(after) == {"2026-11-05"}


def test_with_the_pin_a_review_built_after_midnight_is_the_same_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    wall = _Wall()
    install_clock(monkeypatch, wall)
    pin_day(monkeypatch)

    before = _build(tmp_path, "before")
    wall.advance(minutes=1)
    after = _build(tmp_path, "after")

    assert _days_recorded(before) == _days_recorded(after) == {PINNED_DAY.isoformat()}
    assert len(gitio.log(before)) == len(gitio.log(after)) == 5
    # The retrieval, the import and the search; not `init` or the fixture commit, which hold
    # `strata.toml` and so the project's random id, which the comparison does not mask.
    for revision in ("HEAD", "HEAD~2", "HEAD~3"):
        assert committed_snapshot(before, revision) == committed_snapshot(after, revision)


@pytest.mark.parametrize(("module", "name"), DAY_STAMPS)
def test_the_fixture_holds_every_read_of_the_clock_that_stamps_a_day(
    same_day: object, module: str, name: str
) -> None:
    clock = getattr(import_module(module), name)

    assert (clock.today() if name == "date" else clock.now(UTC).date()) == same_day == PINNED_DAY


def test_every_read_of_the_clock_in_the_source_is_pinned_or_left_alone_on_purpose() -> None:
    package = Path(strata.__file__).parent
    read = re.compile(r"\b(?:date\.today|datetime\.(?:now|today|utcnow))\(")
    readers = {
        ".".join(path.relative_to(package.parent).with_suffix("").parts)
        for path in package.rglob("*.py")
        if read.search(path.read_text(encoding="utf-8"))
    }

    assert readers == {module for module, _ in DAY_STAMPS} | set(OTHER_CLOCKS), (
        "a module reads the clock that `tests/integration/_equivalence.py` knows nothing about: "
        "add it to DAY_STAMPS if what it reads is stamped on something committed, or to "
        "OTHER_CLOCKS (with the reason) if it is not"
    )


def test_two_reviews_are_not_compared_while_the_day_can_still_move(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="same_day"):
        committed_snapshot(tmp_path)
