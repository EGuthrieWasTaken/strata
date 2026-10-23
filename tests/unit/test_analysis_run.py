"""Running an analysis: outputs, the reproducibility record and staleness
(openspec:analysis-specification#running-analyses, #reproducibility-record)."""

# ruff: noqa: E501
from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from strata import __version__
from strata.analysis import plots as plots_mod
from strata.analysis import run as run_mod
from strata.analysis import spec as sp
from strata.extract import records as rec_mod
from tests.unit._m4 import meta_repo, write_spec
from tests.unit.test_extract_records import study

ALL_PLOTS = ["forest", "funnel", "baujat", "bubble"]
MODERATORS = [{"name": "dose", "type": "continuous", "centering": "mean"}]


def test_a_run_writes_the_documented_files(tmp_path: Path) -> None:
    repo = meta_repo(tmp_path)
    write_spec(repo, plots=["forest", "funnel", "baujat"])
    outcome = run_mod.run_analysis(repo, "primary")
    directory = sp.results_dir(repo, "primary")
    assert outcome.written == [
        "estimates.json", "studies.tsv", "summary.md", "run.json",
        "plots/forest.svg", "plots/funnel.svg", "plots/baujat.svg",
    ]  # fmt: skip
    for name in outcome.written:
        assert (directory / name).stat().st_size > 0
    estimates = json.loads((directory / "estimates.json").read_text())
    assert estimates["analysis"] == "primary" and estimates["label"] == "preregistered"
    table = (directory / "studies.tsv").read_text().splitlines()
    assert table[0].split("\t")[:3] == ["study_id", "effect_id", "label"]
    assert len(table) == 13 and len(table[1].split("\t")) == len(table[0].split("\t"))


def test_run_json_is_the_reproducibility_record(tmp_path: Path) -> None:
    repo = meta_repo(tmp_path)
    write_spec(repo, seed=20260911)
    run = run_mod.run_analysis(repo, "primary", acknowledged=["high-heterogeneity"]).run
    assert run["analysis"] == "primary" and run["engine"] == "native" and run["seed"] == 20260911
    assert run["strata_version"] == __version__ and run["input_digest"].startswith("sha256:")
    assert run["inputs"] == {
        "studies": 12,
        "effects": 12,
        "criteria_version": run["inputs"]["criteria_version"],
    }
    assert set(run["dependencies"]) == {"numpy", "scipy"} and "python" in run["platform"]
    assert run["acknowledged"] == ["high-heterogeneity"]
    codes = {w["code"]: w for w in run["warnings"]}
    assert codes["high-heterogeneity"]["acknowledged"] is True
    assert run["conventions"]["prediction_df"] == "k-2"
    assert "generated_from_commit" in run


def test_the_same_data_gives_byte_identical_output(tmp_path: Path) -> None:
    repo = meta_repo(tmp_path)
    write_spec(
        repo, plots=ALL_PLOTS, moderators=MODERATORS,
        publication_bias=["egger", "begg", "trim_fill", "pet_peese"],
        sensitivity=[{"id": "loo", "type": "leave_one_out"}],
    )  # fmt: skip
    run_mod.run_analysis(repo, "primary")
    directory = sp.results_dir(repo, "primary")
    first = {p.name: p.read_bytes() for p in sorted(directory.rglob("*")) if p.is_file()}
    run_mod.run_analysis(repo, "primary")
    second = {p.name: p.read_bytes() for p in sorted(directory.rglob("*")) if p.is_file()}
    assert first == second and "forest.svg" in first


def test_exploratory_analyses_say_so_in_every_output(tmp_path: Path) -> None:
    """openspec scenario: preregistered: false -> every output labels the analysis exploratory."""
    repo = meta_repo(tmp_path)
    write_spec(repo, "sensitivity-rct-only", preregistered=False, plots=["forest"])
    run_mod.run_analysis(repo, "sensitivity-rct-only")
    directory = sp.results_dir(repo, "sensitivity-rct-only")
    assert "Exploratory analysis" in (directory / "summary.md").read_text()
    assert json.loads((directory / "estimates.json").read_text())["label"] == "exploratory"
    assert json.loads((directory / "run.json").read_text())["label"] == "exploratory"
    assert "Exploratory analysis" in (directory / "plots" / "forest.svg").read_text()


def test_summary_leads_with_the_estimate_and_never_claims_to_correct(tmp_path: Path) -> None:
    repo = meta_repo(tmp_path)
    write_spec(repo, publication_bias=["egger", "trim_fill"])
    run_mod.run_analysis(repo, "primary")
    text = (sp.results_dir(repo, "primary") / "summary.md").read_text()
    assert "the pooled SMD was" in text and "tau =" in text and "prediction interval" in text
    assert "consistent with small-study effects" in text
    assert "none corrects for publication bias" in text
    assert "corrected for" not in text and "bias-corrected estimate" in text  # only "not a ..."


def test_results_become_stale_when_the_data_change_not_when_other_things_do(tmp_path: Path) -> None:
    """openspec scenario: an included study's extraction changes -> stale because its data changed."""
    repo = meta_repo(tmp_path)
    write_spec(repo)
    assert run_mod.results_state(repo, "primary") == "missing"
    run_mod.run_analysis(repo, "primary")
    assert run_mod.results_state(repo, "primary") == "fresh"
    # An unrelated extraction field changes: the pooled rows do not.
    rec_mod.set_field(repo, study=study(1), handle="ethan", name="n_total", raw="999")
    assert run_mod.results_state(repo, "primary") == "fresh"
    rec_mod.add_effect(
        repo, study=study(1), handle="ethan", outcome="recall", design="two-group-means",
        timepoint="1 week",
        inputs={"n1": 31, "m1": 0.9, "sd1": 0.18, "n2": 31, "m2": 0.5, "sd2": 0.21},
    )  # fmt: skip
    assert run_mod.results_state(repo, "primary") == "stale-data"
    run_mod.run_analysis(repo, "primary")
    run_json = sp.results_dir(repo, "primary") / "run.json"
    recorded = json.loads(run_json.read_text())
    recorded["strata_version"] = "0.0.0"
    run_json.write_text(json.dumps(recorded))
    assert run_mod.results_state(repo, "primary") == "stale-tool"


def test_changing_the_options_changes_the_digest(tmp_path: Path) -> None:
    repo = meta_repo(tmp_path)
    write_spec(repo)
    first = run_mod.run_analysis(repo, "primary", write=False).run["input_digest"]
    write_spec(repo, model={"tau2_estimator": "DL"})
    second = run_mod.run_analysis(repo, "primary", write=False).run["input_digest"]
    assert first != second


def test_not_writing_leaves_the_repository_untouched(tmp_path: Path) -> None:
    repo = meta_repo(tmp_path)
    write_spec(repo)
    run_mod.run_analysis(repo, "primary", write=False)
    assert not sp.results_dir(repo, "primary").exists()


# --- plots ----------------------------------------------------------------------------------------


def _svg(repo: object, name: str) -> ET.Element:
    spec = sp.load_spec(repo, "primary")  # type: ignore[arg-type]
    outcome = run_mod.run_analysis(repo, "primary", write=False)  # type: ignore[arg-type]
    return ET.fromstring(plots_mod.BUILDERS[name](spec, outcome.result).render_svg())


def _texts(root: ET.Element) -> list[str]:
    return ["".join(e.itertext()) for e in root.iter() if e.tag.endswith("text")]


def test_the_forest_plot_has_the_required_contents(tmp_path: Path) -> None:
    """openspec scenario: pooled diamond, a distinct prediction-interval band, heterogeneity footer."""
    repo = meta_repo(tmp_path)
    write_spec(repo)
    root = _svg(repo, "forest")
    texts = _texts(root)
    assert any(t.startswith("Forest plot") for t in texts)
    assert sum(1 for t in texts if t.startswith("Author")) == 12  # a label per study
    assert "Pooled" in texts and "Prediction interval" in texts
    assert any(t.startswith("k = 12; tau =") and "I2 =" in t and "Q(11)" in t for t in texts)
    polygons = [e for e in root.iter() if e.tag.endswith("polygon")]
    assert len(polygons) == 1 and polygons[0].get("class") == "f-accent2"  # the diamond
    bands = [e for e in root.iter() if e.get("class") == "f-band"]
    assert len(bands) == 1  # the prediction interval, in its own class


def test_forest_subgroups_follow_a_categorical_moderator(tmp_path: Path) -> None:
    repo = meta_repo(tmp_path)
    write_spec(repo, moderators=[{"name": "design", "type": "categorical", "reference": "rct"}])
    texts = _texts(_svg(repo, "forest"))
    assert "design = rct" in texts


def test_the_funnel_plot_is_contour_enhanced_by_default(tmp_path: Path) -> None:
    repo = meta_repo(tmp_path)
    write_spec(repo)
    root = _svg(repo, "funnel")
    classes = {e.get("class") for e in root.iter()}
    assert {"f-tint1", "f-tint2", "f-tint3"} <= classes
    assert (
        sum(1 for e in root.iter() if e.tag.endswith("circle") and e.get("class") == "f-accent")
        == 12
    )
    assert any("p < .01" in t for t in _texts(root))


def test_baujat_and_bubble_plots(tmp_path: Path) -> None:
    repo = meta_repo(tmp_path)
    write_spec(repo, moderators=MODERATORS)
    baujat = _svg(repo, "baujat")
    assert sum(1 for e in baujat.iter() if e.tag.endswith("polygon")) == 12
    bubble = _svg(repo, "bubble")
    assert (
        sum(1 for e in bubble.iter() if e.tag.endswith("circle") and e.get("class") == "f-accent")
        == 12
    )
    assert "dose" in _texts(bubble)
    write_spec(repo)
    with pytest.raises(plots_mod.PlotError, match="continuous moderator"):
        _svg(repo, "bubble")


def test_plot_formats(tmp_path: Path) -> None:
    repo = meta_repo(tmp_path)
    write_spec(repo, plots=["forest"])
    outcome = run_mod.run_analysis(repo, "primary", plot_format="pdf")
    pdf = (sp.results_dir(repo, "primary") / "plots" / "forest.pdf").read_bytes()
    assert pdf.startswith(b"%PDF-1.4") and "plots/forest.pdf" in outcome.written
    with pytest.raises(plots_mod.PlotError, match="one of svg, pdf, png"):
        plots_mod.render(plots_mod.BUILDERS["forest"](outcome.spec, outcome.result), "gif")
    try:
        import cairosvg  # noqa: F401
    except ImportError:
        with pytest.raises(plots_mod.PlotError, match="cairosvg"):
            plots_mod.render(plots_mod.BUILDERS["forest"](outcome.spec, outcome.result), "png")
    else:
        png = plots_mod.render(plots_mod.BUILDERS["forest"](outcome.spec, outcome.result), "png")
        assert png.startswith(b"\x89PNG")
