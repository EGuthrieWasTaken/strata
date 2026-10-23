"""Golden plots: the analysis plots are byte-identical across runs, hash seeds and platforms
(openspec:analysis-plots#deterministic-output, openspec:test-suite).

Each plot of a fixed analysis is compared byte for byte with a committed file in
`tests/golden/plots/`. CI runs the suite on Linux, macOS and Windows, so a plot that differed by
platform (a float formatted differently, an unordered set, a locale) fails there. After an
intended change to the drawing code, regenerate the files with
`STRATA_UPDATE_GOLDEN=1 uv run pytest tests/golden/test_golden_plots.py` and review the diff.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from strata.analysis import engine, plots, rows
from strata.analysis import spec as sp
from tests.unit._m4 import meta_repo, write_spec

GOLDEN = Path(__file__).parent / "plots"
PLOTS = ["forest", "funnel", "baujat", "bubble"]
UPDATE = bool(os.environ.get("STRATA_UPDATE_GOLDEN"))


@pytest.fixture(scope="module")
def drawn(tmp_path_factory: pytest.TempPathFactory) -> dict[str, bytes]:
    repo = meta_repo(tmp_path_factory.mktemp("golden"))
    write_spec(
        repo,
        plots=PLOTS,
        publication_bias=["egger", "trim_fill"],
        moderators=[{"name": "dose", "type": "continuous"}],
        model={"type": "random-effects", "tau2_estimator": "REML", "ci_method": "wald"},
    )
    spec = sp.load_spec(repo, "primary")
    result = engine.run_analysis(spec, rows.build_rows(repo, spec), force=True)
    out: dict[str, bytes] = {}
    for fmt in ("svg", "pdf"):
        for name in PLOTS:
            out[f"{name}.{fmt}"] = plots.render(plots.BUILDERS[name](spec, result), fmt)
    return out


@pytest.mark.parametrize("name", [f"{n}.{f}" for n in PLOTS for f in ("svg", "pdf")])
def test_a_plot_matches_its_committed_bytes(name: str, drawn: dict[str, bytes]) -> None:
    path = GOLDEN / name
    if UPDATE:
        path.write_bytes(drawn[name])
    assert path.exists(), f"{name} is missing; generate it with STRATA_UPDATE_GOLDEN=1"
    assert drawn[name] == path.read_bytes()


def test_drawing_twice_gives_the_same_bytes(drawn: dict[str, bytes], tmp_path: Path) -> None:
    repo = meta_repo(tmp_path)
    write_spec(
        repo,
        plots=PLOTS,
        publication_bias=["egger", "trim_fill"],
        moderators=[{"name": "dose", "type": "continuous"}],
        model={"type": "random-effects", "tau2_estimator": "REML", "ci_method": "wald"},
    )
    spec = sp.load_spec(repo, "primary")
    result = engine.run_analysis(spec, rows.build_rows(repo, spec), force=True)
    again = {f"{n}.svg": plots.render(plots.BUILDERS[n](spec, result), "svg") for n in PLOTS}
    assert again == {k: v for k, v in drawn.items() if k.endswith(".svg")}


def test_a_different_hash_seed_gives_the_same_bytes(tmp_path: Path) -> None:
    """Python randomises str hashing per process; no plot may depend on set or dict order of
    strings."""
    script = (
        "import sys; from pathlib import Path\n"
        "sys.path.insert(0, sys.argv[2])\n"
        "from strata.analysis import engine, plots, rows, spec as sp\n"
        "from tests.unit._m4 import meta_repo, write_spec\n"
        "repo = meta_repo(Path(sys.argv[1]))\n"
        "write_spec(repo, plots=['forest', 'funnel', 'baujat', 'bubble'], publication_bias=['egger', 'trim_fill'],\n"
        "  moderators=[{'name': 'dose', 'type': 'continuous'}],\n"
        "  model={'type': 'random-effects', 'tau2_estimator': 'REML', 'ci_method': 'wald'})\n"
        "spec = sp.load_spec(repo, 'primary')\n"
        "result = engine.run_analysis(spec, rows.build_rows(repo, spec), force=True)\n"
        "import hashlib\n"
        "for n in ['forest', 'funnel', 'baujat', 'bubble']:\n"
        "    print(n, hashlib.sha256(plots.render(plots.BUILDERS[n](spec, result), 'svg')).hexdigest())\n"
    )
    root = str(Path(__file__).resolve().parents[2])
    outputs = []
    for seed in ("1", "12345"):
        work = tmp_path / f"seed{seed}"
        work.mkdir()
        done = subprocess.run(
            [sys.executable, "-I", "-c", script, str(work), root],
            capture_output=True, text=True, check=True,
            env={**os.environ, "PYTHONHASHSEED": seed},
        )  # fmt: skip
        outputs.append(done.stdout)
    assert outputs[0] == outputs[1] and outputs[0].count("\n") == 4
