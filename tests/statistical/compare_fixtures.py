"""Compare freshly generated `metafor` fixtures with the committed ones, tolerantly.

    STRATA_FIXTURE_DIR=fresh Rscript tests/statistical/generate.R
    python tests/statistical/compare_fixtures.py tests/statistical/fixtures fresh

Used by the nightly `metafor-live` job (openspec:ci-gate#nightly-checks). A different R, BLAS or
`metafor` release moves the last digits of a float without any change in meaning, so byte
equality would raise false alarms every time a runner image updates; the comparison instead
fails when a number moves by more than `RTOL`/`ATOL` (tighter than the tolerances the test suite
itself applies), or when a key, a length or a type differs. Exit code 0 means no drift.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Any

RTOL = 1e-9
ATOL = 1e-12


def differences(committed: Any, fresh: Any, where: str = "$") -> list[str]:
    """Every place `fresh` departs from `committed`, as a short human-readable line each."""
    if isinstance(committed, dict) and isinstance(fresh, dict):
        found = []
        for key in sorted(set(committed) | set(fresh)):
            if key not in committed:
                found.append(f"{where}.{key}: new in the regenerated fixture")
            elif key not in fresh:
                found.append(f"{where}.{key}: missing from the regenerated fixture")
            else:
                found.extend(differences(committed[key], fresh[key], f"{where}.{key}"))
        return found
    if isinstance(committed, list) and isinstance(fresh, list):
        if len(committed) != len(fresh):
            return [f"{where}: length {len(committed)} became {len(fresh)}"]
        found = []
        for index, (a, b) in enumerate(zip(committed, fresh, strict=True)):
            found.extend(differences(a, b, f"{where}[{index}]"))
        return found
    numbers = (int, float)
    if (
        isinstance(committed, numbers)
        and isinstance(fresh, numbers)
        and not isinstance(committed, bool)
        and not isinstance(fresh, bool)
    ):
        if math.isclose(committed, fresh, rel_tol=RTOL, abs_tol=ATOL):
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
        found.extend(f"{name} {line}" for line in differences(a, b))
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
