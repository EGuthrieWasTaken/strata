"""The analysis results screens (openspec:web-ui, M4)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from strata import gitio
from strata.analysis import run as analysis_run
from strata.core.repo import Repo
from strata.extract import records as rec_mod
from strata.web.app import create_app
from tests.unit._m4 import MEANS, meta_repo, write_spec
from tests.unit.test_extract_records import study

_TOKEN = "test-session-token-0123456789"


def _client(repo: Repo) -> TestClient:
    app = create_app(repo_root=repo.root, actor="ethan", session_token=_TOKEN)
    client = TestClient(app, base_url="http://127.0.0.1:8000")
    assert client.get(f"/?token={_TOKEN}").status_code == 200
    return client


def _run(repo: Repo, **spec: Any) -> None:
    write_spec(repo, **spec)
    analysis_run.run_analysis(repo, "primary", force=True)
    gitio.add_all(repo.root)


def test_the_index_lists_analyses_and_their_state(tmp_path: Path) -> None:
    repo = meta_repo(tmp_path)
    write_spec(repo)
    page = _client(repo).get("/analysis")
    assert page.status_code == 200
    assert "Effect of spaced practice on recall" in page.text
    assert "not run yet" in page.text
    analysis_run.run_analysis(repo, "primary")
    assert "current" in _client(repo).get("/analysis").text


def test_the_dashboard_links_to_analyses_only_when_there_are_some(tmp_path: Path) -> None:
    repo = meta_repo(tmp_path)
    assert 'href="/analysis"' not in _client(repo).get("/").text
    write_spec(repo)
    assert 'href="/analysis"' in _client(repo).get("/").text


def test_a_result_screen_shows_the_estimate_and_heterogeneity(tmp_path: Path) -> None:
    repo = meta_repo(tmp_path)
    _run(repo, plots=["forest"])
    page = _client(repo).get("/analysis/primary")
    assert page.status_code == 200
    assert "Pooled estimate" in page.text
    assert "Heterogeneity" in page.text
    assert "prediction interval" in page.text
    assert "Values behind the plots" in page.text
    assert "Author1" in page.text
    assert "out of date" not in page.text


def test_guardrail_warnings_are_displayed_with_the_results(tmp_path: Path) -> None:
    repo = meta_repo(tmp_path, k=6)
    _run(repo, publication_bias=["egger"])
    page = _client(repo).get("/analysis/primary")
    assert "Guardrail warnings" in page.text
    assert "k-lt-10-bias-tests" in page.text
    assert "computed with --force" in page.text
    assert "underpowered" in page.text


def test_an_exploratory_analysis_is_labelled(tmp_path: Path) -> None:
    repo = meta_repo(tmp_path)
    _run(repo, preregistered=False)
    assert "Exploratory analysis" in _client(repo).get("/analysis/primary").text


def test_stale_results_are_reported_never_recomputed(tmp_path: Path) -> None:
    repo = meta_repo(tmp_path)
    _run(repo, dependency={"handling": "aggregate", "rho": 0.5})
    run_json = repo.path("analysis", "results", "primary", "run.json")
    before = run_json.read_bytes()
    rec_mod.add_effect(
        repo, study=study(1), handle="ethan", outcome="recall", design="two-group-means",
        inputs={**MEANS, "m1": 0.9}, timepoint="1 month", moderators={"dose": 1},
    )  # fmt: skip
    page = _client(repo).get("/analysis/primary")
    assert "out of date" in page.text
    assert "strata analyze primary" in page.text
    assert run_json.read_bytes() == before


def test_an_analysis_without_results_says_so(tmp_path: Path) -> None:
    repo = meta_repo(tmp_path)
    write_spec(repo)
    page = _client(repo).get("/analysis/primary")
    assert page.status_code == 200
    assert "No results have been produced" in page.text
    assert "Pooled estimate" not in page.text


def test_plots_are_served_with_their_own_policy(tmp_path: Path) -> None:
    repo = meta_repo(tmp_path)
    _run(repo, plots=["forest", "funnel"])
    client = _client(repo)
    page = client.get("/analysis/primary")
    assert '<img src="/analysis/primary/plots/forest.svg"' in page.text
    plot = client.get("/analysis/primary/plots/forest.svg")
    assert plot.status_code == 200
    assert plot.headers["content-type"].startswith("image/svg+xml")
    assert "style-src 'unsafe-inline'" in plot.headers["content-security-policy"]
    assert "script" not in plot.headers["content-security-policy"]
    assert plot.content.startswith(b"<svg") or b"<svg" in plot.content[:200]
    # The pages themselves keep the strict policy.
    assert "style-src 'self'" in page.headers["content-security-policy"]


def test_unknown_analyses_and_plot_names_are_404(tmp_path: Path) -> None:
    repo = meta_repo(tmp_path)
    _run(repo, plots=["forest"])
    client = _client(repo)
    assert client.get("/analysis/nope").status_code == 404
    assert client.get("/analysis/primary/plots/missing.svg").status_code == 404
    assert client.get("/analysis/primary/plots/..%2Frun.json").status_code == 404
    assert client.get("/analysis/primary/plots/run.json").status_code == 404
    assert client.get("/analysis/nope/plots/forest.svg").status_code == 404


def test_analysis_screens_need_the_session(tmp_path: Path) -> None:
    repo = meta_repo(tmp_path)
    _run(repo, plots=["forest"])
    app = create_app(repo_root=repo.root, actor="ethan", session_token=_TOKEN)
    anonymous = TestClient(app, base_url="http://127.0.0.1:8000")
    assert anonymous.get("/analysis").status_code == 403
    assert anonymous.get("/analysis/primary/plots/forest.svg").status_code == 403
