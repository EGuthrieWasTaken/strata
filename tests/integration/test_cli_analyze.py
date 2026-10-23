"""`strata analyze`, `strata diff`, and analyses in `strata status` and `strata verify` (M4)."""

# ruff: noqa: E501
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from typer.testing import CliRunner

from strata import gitio
from strata.cli.main import EXIT_GUARDRAIL, EXIT_OK, EXIT_USAGE, app
from strata.core.ids import report_id
from strata.core.repo import Repo
from strata.core.verify import verify_repository
from strata.extract import records as rec_mod
from strata.protocol import retrieval
from tests.unit._m3 import add_records, decide, rec
from tests.unit._m4 import MEANS, meta_repo, write_spec
from tests.unit.test_extract_records import study

runner = CliRunner()
WHY = ("--why", "Running this analysis for the review record.")


def _cli(repo: Repo, *args: str, code: int = EXIT_OK) -> Any:
    result = runner.invoke(app, [*WHY, "-C", str(repo.root), *args])
    assert result.exit_code == code, result.output
    return result


def _json(repo: Repo, *args: str, code: int = EXIT_OK) -> Any:
    return json.loads(_cli(repo, "--json", *args, code=code).output)


def _commit_all(repo: Repo, message: str = "test: fixture") -> None:
    gitio.add_all(repo.root)
    if gitio.is_dirty(repo.root):
        gitio.commit(repo.root, f"{message}\n\nStrata-Op: test\nStrata-Actor: ethan")


def _subjects(repo: Repo) -> list[str]:
    return gitio.log(repo.root, fmt="%s")


def _review(tmp_path: Path, *, k: int = 12, **spec: Any) -> Repo:
    """A review whose screening and retrieval are finished, so analysis is what is left to do."""
    repo = meta_repo(tmp_path, k=k)
    ids = [rec(n) for n in range(1, k + 1)]
    decide(repo, "title-abstract", ids)
    for record_id in ids:
        retrieval.record_retrieval(
            repo, report=report_id(record_id), status="retrieved", actor="ethan",
            source="institutional-access", version="version-of-record",
        )  # fmt: skip
    write_spec(repo, **spec)
    _commit_all(repo)
    return repo


# --- strata analyze --------------------------------------------------------------------------


def test_check_validates_and_writes_nothing(tmp_path: Path) -> None:
    repo = _review(tmp_path)
    before = _subjects(repo)
    out = _json(repo, "analyze", "primary", "--check")
    assert out["checked"][0]["analysis"] == "primary"
    assert out["checked"][0]["effects"] == 12
    assert not repo.path("analysis", "results", "primary").exists()
    assert _subjects(repo) == before


def test_running_an_analysis_writes_results_and_makes_one_commit(tmp_path: Path) -> None:
    repo = _review(tmp_path, plots=["forest", "funnel", "baujat"])
    before = len(_subjects(repo))
    _cli(repo, "analyze", "primary")
    results = repo.path("analysis", "results", "primary")
    for name in ("estimates.json", "studies.tsv", "summary.md", "run.json"):
        assert (results / name).is_file(), name
    assert sorted(p.name for p in (results / "plots").iterdir()) == [
        "baujat.svg", "forest.svg", "funnel.svg"
    ]  # fmt: skip
    assert len(_subjects(repo)) == before + 1
    body = gitio.run(["log", "-1", "--format=%B"], cwd=repo.root).stdout
    assert "Strata-Op: analyze" in body
    assert "ran primary" in body.splitlines()[0]
    assert not gitio.is_dirty(repo.root)


def test_json_output_reports_the_pooled_estimate(tmp_path: Path) -> None:
    repo = _review(tmp_path)
    ran = _json(repo, "analyze", "primary")["ran"][0]
    assert ran["analysis"] == "primary"
    assert ran["k_studies"] == 12
    assert ran["ci_lb"] < ran["estimate"] < ran["ci_ub"]


def test_all_runs_every_specification(tmp_path: Path) -> None:
    repo = _review(tmp_path)
    write_spec(
        repo,
        "second",
        model={"type": "random-effects", "tau2_estimator": "DL", "ci_method": "wald"},
    )
    _commit_all(repo)
    ran = _json(repo, "analyze", "--all")["ran"]
    assert [r["analysis"] for r in ran] == ["primary", "second"]
    assert repo.path("analysis", "results", "second", "estimates.json").is_file()


def test_unknown_analysis_and_unknown_warning_are_usage_errors(tmp_path: Path) -> None:
    repo = _review(tmp_path)
    _cli(repo, "analyze", "nope", code=EXIT_USAGE)
    _cli(repo, "analyze", "primary", "--ack", "not-a-warning", code=EXIT_USAGE)
    assert not repo.path("analysis", "results", "primary").exists()


def test_a_blocking_guardrail_exits_8_and_writes_nothing(tmp_path: Path) -> None:
    repo = _review(tmp_path, k=6, publication_bias=["egger"])
    before = _subjects(repo)
    result = _cli(repo, "analyze", "primary", code=EXIT_GUARDRAIL)
    assert "k-lt-10-bias-tests" in result.output
    assert not repo.path("analysis", "results", "primary").exists()
    assert _subjects(repo) == before


def test_force_bypasses_the_guardrail_and_records_it(tmp_path: Path) -> None:
    repo = _review(tmp_path, k=6, publication_bias=["egger"])
    out = _cli(repo, "analyze", "primary", "--force")
    assert "forced" in out.output
    run = json.loads(repo.path("analysis", "results", "primary", "run.json").read_text())
    assert run["forced_bypasses"] == ["Egger's test"]
    assert {"code": "k-lt-10-bias-tests", "acknowledged": False, "forced": True} in run["warnings"]


def test_acknowledging_a_warning_is_recorded(tmp_path: Path) -> None:
    repo = _review(tmp_path, preregistered=False)
    shown = _cli(repo, "analyze", "primary")
    assert "exploratory" in shown.output
    _cli(repo, "analyze", "primary", "--ack", "exploratory")
    run = json.loads(repo.path("analysis", "results", "primary", "run.json").read_text())
    assert run["acknowledged"] == ["exploratory"]
    summary = repo.path("analysis", "results", "primary", "summary.md").read_text()
    assert "Exploratory analysis" in summary


# --- staleness in status and verify ------------------------------------------------------------


def test_status_and_verify_report_a_stale_analysis(tmp_path: Path) -> None:
    repo = _review(tmp_path, dependency={"handling": "aggregate", "rho": 0.5})
    status = _json(repo, "status")
    assert status["analyses"][0]["id"] == "primary"
    assert status["analyses"][0]["state"] == "missing"
    assert status["next_action"] == "strata analyze --all"

    _cli(repo, "analyze", "primary")
    assert _json(repo, "status")["analyses"][0]["state"] == "fresh"
    assert verify_repository(repo).ok

    rec_mod.add_effect(
        repo, study=study(1), handle="ethan", outcome="recall", design="two-group-means",
        inputs={**MEANS, "m1": 0.9}, timepoint="1 month", moderators={"dose": 1},
    )  # fmt: skip
    assert _json(repo, "status")["analyses"][0]["state"] == "stale-data"
    codes = {i.code for i in verify_repository(repo).issues}
    assert "W_ANALYSIS_STALE" in codes
    assert verify_repository(repo).ok  # a warning, not a failure

    _cli(repo, "analyze", "primary")
    assert _json(repo, "status")["analyses"][0]["state"] == "fresh"


def test_screening_does_not_rerun_analyses(tmp_path: Path) -> None:
    repo = _review(tmp_path)
    _cli(repo, "analyze", "primary")
    results = repo.path("analysis", "results", "primary", "run.json")
    before = results.read_bytes()
    decide(repo, "title-abstract", [rec(1)], decision="include")
    _commit_all(repo)
    assert results.read_bytes() == before


# --- strata diff -------------------------------------------------------------------------------


def test_diff_shows_the_pooled_estimate_moving(tmp_path: Path) -> None:
    repo = _review(tmp_path, dependency={"handling": "aggregate", "rho": 0.5})
    ids = add_records(repo, 13)
    _commit_all(repo)
    _cli(repo, "analyze", "primary")
    gitio.run(["tag", "v1"], cwd=repo.root)

    decide(repo, "title-abstract", [ids[12]])
    decide(repo, "full-text", [ids[12]])
    rec_mod.add_effect(
        repo, study=study(1), handle="ethan", outcome="recall", design="two-group-means",
        inputs={**MEANS, "m1": 1.4}, timepoint="1 month", moderators={"dose": 1},
    )  # fmt: skip
    _commit_all(repo, "test: widen the pool")
    _cli(repo, "analyze", "primary")

    diff = _json(repo, "diff", "v1..HEAD")
    assert diff["base"] == "v1"
    pool = {p["stage"]: p for p in diff["pools"]}
    assert pool["full-text"]["entered"] == 1
    assert pool["full-text"]["left"] == 0
    assert diff["studies"] == [12, 13]
    assert diff["records_identified"] == [13, 13]
    primary = diff["analyses"][0]
    assert primary["analysis"] == "primary"
    assert primary["status"] == "changed"
    assert primary["before"]["estimate"] != primary["after"]["estimate"]

    text = _cli(repo, "diff", "v1..HEAD").output
    assert "Included:" in text and "12 -> 13 studies" in text
    assert "primary:" in text and "->" in text


def test_diff_reports_criteria_changes(tmp_path: Path) -> None:
    repo = _review(tmp_path)
    gitio.run(["tag", "v1-protocol"], cwd=repo.root)
    _cli(
        repo,
        "criteria",
        "add",
        "--kind",
        "exclusion",
        "--label",
        "Case reports",
        "--definition",
        "Single-patient reports",
        "--applies-at",
        "title-abstract",
        "--by",
        "ethan",
    )
    diff = _json(repo, "diff", "v1-protocol..HEAD")
    assert diff["criteria_versions"][1] > diff["criteria_versions"][0]
    assert diff["criteria_deltas"]["added"] == 1


def test_diff_with_an_unknown_revision_is_a_usage_error(tmp_path: Path) -> None:
    repo = _review(tmp_path)
    _cli(repo, "diff", "no-such-ref..HEAD", code=EXIT_USAGE)
    _cli(repo, "diff", "--evil..HEAD", code=EXIT_USAGE)
    _cli(repo, "diff", "a...b", code=EXIT_USAGE)


def test_diff_of_identical_points_changes_nothing(tmp_path: Path) -> None:
    repo = _review(tmp_path)
    _cli(repo, "analyze", "primary")
    diff = _json(repo, "diff", "HEAD..HEAD")
    assert diff["analyses"][0]["status"] == "unchanged"
    assert diff["studies"][0] == diff["studies"][1]
