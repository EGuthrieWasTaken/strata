"""Compare freshly generated `metafor` fixtures with the committed ones, tolerantly.

    STRATA_FIXTURE_DIR=fresh Rscript tests/statistical/generate.R
    python tests/statistical/compare_fixtures.py tests/statistical/fixtures fresh

Used by the nightly `metafor-live` job (openspec:ci-gate#nightly-checks). A different R, BLAS or
`metafor` release moves the last digits of a float without any change in meaning, so byte
equality would raise false alarms every time a runner image updates; the comparison instead
fails when a number moves by more than `RTOL`/`ATOL` (tighter than the tolerances the test suite
itself applies), or when a key, a length or a type differs. The models fitted by an optimizer get
the looser `OPTIMIZER_RTOL`, explained below. Exit code 0 means no drift.
"""

from __future__ import annotations

import json
import math
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

RTOL = 1e-9
ATOL = 1e-12

# `rma.mv` finds the variance components of the multilevel models with an optimizer, and the
# likelihood is almost flat around its optimum. Refitting the CHE model on the committed data from
# other starting values, or with another optimizer, moves a variance component by up to about 1e-7
# relative and its standard error by about 4e-8, while the log-likelihood agrees to 1e-15: the fit
# is determined no more finely than that. The first live run, with `metafor` 5.2-1 against the
# 4.4.0 that wrote the fixtures, moved three values of the CHE fit by 1e-9 to 4e-9, which RTOL
# reported as drift. These models therefore use 1e-6, the tolerance `tests/statistical` applies to
# their coefficients and standard errors (it allows 1e-5 for their variance components and CR2
# values); a change of method or convention moves them by far more. Every other value keeps RTOL.
OPTIMIZER_RTOL = 1e-6
OPTIMIZER_FITS: dict[str, tuple[str, ...]] = {
    "dependence.json": ("assink_che", "konstantopoulos_three_level"),
}

Tolerance = Callable[[str], float]


def _top_key(where: str) -> str:
    """The first key of a `$.key...` path: `$.assink_che.results.0.5.se[0]` is `assink_che`."""
    return where.removeprefix("$.").split(".", 1)[0].split("[", 1)[0]


def tolerance_for(name: str) -> Tolerance:
    """The relative tolerance for each value of the fixture file `name`, by its path."""
    fitted = OPTIMIZER_FITS.get(name, ())
    return lambda where: OPTIMIZER_RTOL if _top_key(where) in fitted else RTOL


def differences(
    committed: Any, fresh: Any, where: str = "$", tolerance: Tolerance | None = None
) -> list[str]:
    """Every place `fresh` departs from `committed`, as a short human-readable line each."""
    if isinstance(committed, dict) and isinstance(fresh, dict):
        found = []
        for key in sorted(set(committed) | set(fresh)):
            if key not in committed:
                found.append(f"{where}.{key}: new in the regenerated fixture")
            elif key not in fresh:
                found.append(f"{where}.{key}: missing from the regenerated fixture")
            else:
                found.extend(differences(committed[key], fresh[key], f"{where}.{key}", tolerance))
        return found
    if isinstance(committed, list) and isinstance(fresh, list):
        if len(committed) != len(fresh):
            return [f"{where}: length {len(committed)} became {len(fresh)}"]
        found = []
        for index, (a, b) in enumerate(zip(committed, fresh, strict=True)):
            found.extend(differences(a, b, f"{where}[{index}]", tolerance))
        return found
    numbers = (int, float)
    if (
        isinstance(committed, numbers)
        and isinstance(fresh, numbers)
        and not isinstance(committed, bool)
        and not isinstance(fresh, bool)
    ):
        rel_tol = tolerance(where) if tolerance else RTOL
        if math.isclose(committed, fresh, rel_tol=rel_tol, abs_tol=ATOL):
            return []
        return [f"{where}: {committed!r} became {fresh!r}"]
    if committed == fresh:
        return []
    return [f"{where}: {committed!r} became {fresh!r}"]


def compare(committed_dir: Path, fresh_dir: Path) -> list[str]:
    found = []
    committed = {p.name for p in committed_dir.glob("*.json")}
    fresh = {p.name for p in fresh_dir.glob("*.json")}
    for name in sorted(committed - fresh):
        found.append(f"{name}: not regenerated")
    for name in sorted(fresh - committed):
        found.append(f"{name}: a new fixture with no committed counterpart")
    for name in sorted(committed & fresh):
        a = json.loads((committed_dir / name).read_text(encoding="utf-8"))
        b = json.loads((fresh_dir / name).read_text(encoding="utf-8"))
        found.extend(f"{name} {line}" for line in differences(a, b, tolerance=tolerance_for(name)))
    return found


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: compare_fixtures.py <committed-dir> <fresh-dir>", file=sys.stderr)
        return 2
    found = compare(Path(argv[1]), Path(argv[2]))
    for line in found[:50]:
        print(line)
    if len(found) > 50:
        print(f"... and {len(found) - 50} more")
    if found:
        print(f"{len(found)} difference(s) between the committed and regenerated fixtures")
        return 1
    print("no drift: the regenerated fixtures agree with the committed ones")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
