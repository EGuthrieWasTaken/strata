"""`strata prisma`, the `/prisma` screens, and the diagram check in `strata verify` (M5)."""

# ruff: noqa: E501
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from typer.testing import CliRunner

from strata import gitio
from strata.cli.main import EXIT_GUARDRAIL, EXIT_OK, EXIT_USAGE, EXIT_VALIDATION, app
from strata.core.repo import Repo
from strata.core.verify import verify_repository
from strata.protocol import criteria as criteria_mod
from strata.web.app import create_app
from tests.unit._m5 import finished_review

runner = CliRunner()
WHY = ("--why", "Drawing the flow diagram for the review record.")
_TOKEN = "test-session-token-0123456789"


def _cli(repo: Repo, *args: str, code: int = EXIT_OK) -> Any:
    result = runner.invoke(app, [*WHY, "-C", str(repo.root), *args])
    assert result.exit_code == code, result.output
    return result


def _commit_all(repo: Repo) -> None:
    gitio.add_all(repo.root)
    if gitio.is_dirty(repo.root):
        gitio.commit(repo.root, "test: fixture\n\nStrata-Op: test\nStrata-Actor: ethan")


def _review(tmp_path: Path, **kwargs: Any) -> Repo:
    repo, _ = finished_review(tmp_path, **kwargs)
    _commit_all(repo)
    return repo


def _stale(repo: Repo) -> None:
    criteria_mod.add_criterion(
        repo, kind="exclusion", label="Older than 2005", definition="Published before 2005.",
        applies_at=["title-abstract", "full-text"], actor="ethan", rationale="Amendment.",
    )  # fmt: skip
    _commit_all(repo)


def test_prisma_writes_and_commits_the_diagram(tmp_path: Path) -> None:
    repo = _review(tmp_path)
    before = len(gitio.log(repo.root))
    _cli(repo, "prisma")
    svg = repo.path("reports", "prisma.svg")
    assert svg.is_file() and b"Records screened (n = 23)" in svg.read_bytes()
    assert b"DRAFT" not in svg.read_bytes()
    assert len(gitio.log(repo.root)) == before + 1
    body = gitio.run(["log", "-1", "--format=%B"], cwd=repo.root).stdout
    assert "Strata-Op: prisma" in body
    assert not gitio.is_dirty(repo.root)
    _cli(repo, "prisma")  # unchanged: no empty commit
    assert len(gitio.log(repo.root)) == before + 1


def test_the_formats_and_columns(tmp_path: Path) -> None:
    repo = _review(tmp_path)
    _cli(repo, "prisma", "--format", "pdf", "--columns", "both")
    assert repo.path("reports", "prisma.pdf").read_bytes().startswith(b"%PDF")
    out = _cli(repo, "prisma", "--format", "json", "--out", "-").output
    document = json.loads(out)
    assert document["counts"]["totals"]["records_screened"] == 23
    assert {r["data"] for r in document["prisma2020"]} >= {"database_results", "dbr_excluded"}
    both = _cli(repo, "prisma", "--columns", "both", "--out", "-").output
    assert "Identification of studies via other methods" in both
    _cli(repo, "prisma", "--format", "gif", code=EXIT_USAGE)
    _cli(repo, "prisma", "--columns", "three", code=EXIT_USAGE)
    _cli(repo, "prisma", "--format", "pdf", "--out", "-", code=EXIT_USAGE)


def test_a_custom_out_is_not_committed(tmp_path: Path) -> None:
    repo = _review(tmp_path)
    before = len(gitio.log(repo.root))
    target = tmp_path / "figure1.svg"
    _cli(repo, "prisma", "--out", str(target))
    assert target.is_file() and len(gitio.log(repo.root)) == before


def test_stale_decisions_refuse_the_final_diagram(tmp_path: Path) -> None:
    repo = _review(tmp_path)
    _stale(repo)
    refused = _cli(repo, "prisma", code=EXIT_GUARDRAIL)
    assert "--allow-stale" in refused.output
    assert not repo.path("reports", "prisma.svg").exists()
    _cli(repo, "prisma", "--allow-stale")
    assert b"DRAFT" in repo.path("reports", "prisma.svg").read_bytes()


def test_an_unfinished_review_is_drawn_as_a_draft_without_a_flag(tmp_path: Path) -> None:
    repo = _review(tmp_path, finish=False)
    result = _cli(repo, "prisma")
    assert "screening incomplete" in result.output
    assert b"DRAFT" in repo.path("reports", "prisma.svg").read_bytes()


def test_broken_counts_are_e_count_reconcile(tmp_path: Path) -> None:
    repo = _review(tmp_path)
    path = repo.path("records", "records.ndjson")
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    stray = json.loads(json.dumps(rows[0]))
    stray["id"], stray["strata"]["canonical_key"] = "rec_" + "0" * 16, "sig:stray"
    path.write_text("\n".join(json.dumps(r) for r in [*rows, stray]) + "\n", encoding="utf-8")
    result = _cli(repo, "prisma", code=EXIT_VALIDATION)
    assert "E_COUNT_RECONCILE" in result.output and "duplicates_removed" in result.output
    assert not repo.path("reports", "prisma.svg").exists()


def test_no_exclusion_table_is_written_when_nothing_collapses(tmp_path: Path) -> None:
    from strata.report import counts as counts_mod
    from strata.report import flow

    repo = _review(tmp_path)
    assert not flow.collapse_reasons(counts_mod.compute(repo).exclusion_reasons)[1]
    assert not repo.path("reports", "prisma-exclusion-reasons.tsv").exists()


def test_verify_compares_the_committed_diagram_with_a_fresh_one(tmp_path: Path) -> None:
    repo = _review(tmp_path)
    _cli(repo, "prisma", "--columns", "both")
    assert not [i for i in verify_repository(repo).issues if i.code == "W_DIAGRAM_STALE"]
    _stale(repo)
    stale = [i for i in verify_repository(repo).issues if i.code == "W_DIAGRAM_STALE"]
    assert stale and stale[0].severity == "warning" and verify_repository(repo).ok
    _cli(repo, "prisma", "--allow-stale", "--columns", "both")
    assert not [i for i in verify_repository(repo).issues if i.code == "W_DIAGRAM_STALE"]


def _client(repo: Repo) -> TestClient:
    client = TestClient(
        create_app(repo_root=repo.root, actor="ethan", session_token=_TOKEN),
        base_url="http://127.0.0.1:8000",
    )
    assert client.get(f"/?token={_TOKEN}").status_code == 200
    return client


def test_the_web_screen_draws_the_current_counts(tmp_path: Path) -> None:
    repo = _review(tmp_path)
    client = _client(repo)
    page = client.get("/prisma")
    assert page.status_code == 200
    assert '<img src="/prisma.svg?columns=one"' in page.text
    assert "Studies included" in page.text and "all hold" in page.text
    assert "DRAFT" not in page.text
    assert 'href="/prisma"' in client.get("/").text
    svg = client.get("/prisma.svg?columns=both")
    assert svg.status_code == 200 and svg.headers["content-type"].startswith("image/svg+xml")
    assert "style-src 'unsafe-inline'" in svg.headers["content-security-policy"]
    assert "style-src 'self'" in page.headers["content-security-policy"]
    assert b"Identification of studies via other methods" in svg.content


def test_the_web_screen_updates_after_screening_and_flags_a_draft(tmp_path: Path) -> None:
    repo = _review(tmp_path)
    client = _client(repo)
    assert "DRAFT" not in client.get("/prisma").text
    _stale(repo)
    page = client.get("/prisma")
    assert "DRAFT" in page.text and "strata rescreen" in page.text
    assert b"DRAFT" in client.get("/prisma.svg").content


def test_the_web_screen_names_a_broken_identity(tmp_path: Path) -> None:
    repo = _review(tmp_path)
    path = repo.path("records", "records.ndjson")
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    stray = json.loads(json.dumps(rows[0]))
    stray["id"], stray["strata"]["canonical_key"] = "rec_" + "0" * 16, "sig:stray"
    path.write_text("\n".join(json.dumps(r) for r in [*rows, stray]) + "\n", encoding="utf-8")
    client = _client(repo)
    page = client.get("/prisma")
    assert "E_COUNT_RECONCILE" in page.text and "<img" not in page.text
    assert client.get("/prisma.svg").status_code == 409
