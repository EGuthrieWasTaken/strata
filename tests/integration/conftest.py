"""Fixtures shared by the integration tests."""

from __future__ import annotations

from datetime import date

import pytest

from tests.integration._equivalence import PINNED_DAY, pin_day


@pytest.fixture
def same_day(monkeypatch: pytest.MonkeyPatch) -> date:
    """Hold the day still, so two reviews built minutes apart record the same one.

    The tests that run an action on two identical reviews and compare what each committed
    (`committed_snapshot`) use it for the whole module with
    `pytestmark = pytest.mark.usefixtures("same_day")`. See `tests/integration/_equivalence.py`.
    """
    pin_day(monkeypatch)
    return PINNED_DAY
