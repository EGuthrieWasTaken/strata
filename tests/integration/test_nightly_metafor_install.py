"""The nightly `metafor-live` job's R install (openspec:ci-gate#nightly-checks).

The job cannot run in the pull-request gate (it needs CRAN), so these structural checks pin what
its first scheduled runs showed it needs. With `--no-install-recommends` and only `r-base-core`,
Ubuntu's R has no `Matrix` ("dependency 'Matrix' is not available for package 'metafor'") and no
`libblas.so` or `liblapack.so`, so `mvtnorm` fails to link ("cannot find -llapack").
`install.packages` only warns when a package fails, so the step must also check that each package
loads.
"""

from __future__ import annotations

import re
from pathlib import Path

from strata.core.canon import load_yaml_str

ROOT = Path(__file__).resolve().parents[2]
PACKAGES = ("metafor", "clubSandwich", "mvtnorm")


def _install_step() -> str:
    nightly = load_yaml_str(
        (ROOT / ".github" / "workflows" / "nightly.yml").read_text(encoding="utf-8")
    )
    steps = nightly["jobs"]["metafor-live"]["steps"]
    (step,) = [s for s in steps if str(s.get("name", "")).startswith("Install R")]
    return str(step["run"])


def _apt_packages(script: str) -> set[str]:
    """The packages named by the step's `apt-get install` line."""
    (line,) = [ln for ln in script.splitlines() if "apt-get install" in ln]
    words = {word for word in line.split() if not word.startswith("-")}
    return words - {"sudo", "apt-get", "install"}


def test_the_r_install_provides_matrix_and_the_blas_and_lapack_development_libraries() -> None:
    packages = _apt_packages(_install_step())
    assert "r-base-core" in packages
    assert "r-recommended" in packages  # Matrix, nlme, lattice: metafor depends on Matrix
    assert "r-base-dev" in packages  # libblas-dev, liblapack-dev, gfortran: mvtnorm links them


def test_the_r_install_names_every_package_the_fixtures_need() -> None:
    script = _install_step()
    for package in PACKAGES:
        assert f'"{package}"' in script


def test_a_package_that_fails_to_install_stops_the_step() -> None:
    """`install.packages` exits 0 when a package fails, so the step has to check for itself."""
    script = _install_step()
    assert re.search(r"requireNamespace", script) and re.search(r"stop\(", script)
    assert script.index("install.packages") < script.index("requireNamespace")
