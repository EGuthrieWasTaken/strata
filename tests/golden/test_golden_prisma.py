"""Golden flow diagrams: byte-identical across runs, hash seeds and platforms
(openspec:prisma-reporting#flow-diagram, openspec:test-suite).

The diagrams of a fixed review are compared byte for byte with committed files in
`tests/golden/prisma/`; CI runs the suite on Linux, macOS and Windows. Regenerate after an intended
change with `STRATA_UPDATE_GOLDEN=1 uv run pytest tests/golden/test_golden_prisma.py` and review
the diff.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from strata.report import counts as counts_mod
from strata.report import flow
from tests.unit._m5 import finished_review

GOLDEN = Path(__file__).parent / "prisma"
UPDATE = bool(os.environ.get("STRATA_UPDATE_GOLDEN"))
CASES = {
    "final-one.svg": (True, "one", "svg"),
    "final-both.svg": (True, "both", "svg"),
    "draft-one.svg": (False, "one", "svg"),
    "final-both.pdf": (True, "both", "pdf"),
}


@pytest.fixture(scope="module")
def drawn(tmp_path_factory: pytest.TempPathFactory) -> dict[str, bytes]:
    out: dict[str, bytes] = {}
    for finish in (True, False):
        repo, _ = finished_review(tmp_path_factory.mktemp("golden"), finish=finish)
        counts = counts_mod.compute(repo)
        for name, (wants_finish, columns, fmt) in CASES.items():
            if wants_finish == finish:
                out[name] = flow.render(counts, fmt=fmt, columns=columns)
    return out


@pytest.mark.parametrize("name", CASES)
def test_a_diagram_matches_its_committed_bytes(name: str, drawn: dict[str, bytes]) -> None:
    path = GOLDEN / name
    if UPDATE:
        path.write_bytes(drawn[name])
    assert path.exists(), f"{name} is missing; generate it with STRATA_UPDATE_GOLDEN=1"
    assert drawn[name] == path.read_bytes()
