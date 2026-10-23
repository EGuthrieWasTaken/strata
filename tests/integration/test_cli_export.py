"""`strata export bibliography` and `strata export package` (M5)."""

# ruff: noqa: E501
from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from typing import Any

from typer.testing import CliRunner

from strata import gitio
from strata.cli.main import EXIT_OK, EXIT_USAGE, app
from strata.core.repo import Repo
from strata.report import bibliography as bib
from tests.unit._m5 import finished_review, full_review

runner = CliRunner()
WHY = ("--why", "Exporting for the supplement.")


def _cli(repo: Repo, *args: str, code: int = EXIT_OK) -> Any:
    result = runner.invoke(app, [*WHY, "-C", str(repo.root), *args])
    assert result.exit_code == code, result.output
    return result


def _commit_all(repo: Repo) -> None:
    gitio.add_all(repo.root)
    if gitio.is_dirty(repo.root):
        gitio.commit(repo.root, "test: fixture\n\nStrata-Op: test\nStrata-Actor: ethan")


def test_the_appendix_of_full_text_exclusions_is_exactly_those_records(tmp_path: Path) -> None:
    repo, _ = finished_review(tmp_path)
    result = _cli(
        repo, "export", "bibliography", "--format", "ris", "--set", "excluded-at-fulltext"
    )
    assert result.output.count("TY  - JOUR") == 4
    assert result.output == bib.render(repo, fmt="ris", set_name="excluded-at-fulltext")
    for record in bib.records(repo, "excluded-at-fulltext"):
        assert f"ID  - {record['id']}" in result.output


def test_bibliography_can_be_written_to_a_file(tmp_path: Path) -> None:
    repo, _ = finished_review(tmp_path)
    target = tmp_path / "included.json"
    out = json.loads(_cli(repo, "--json", "export", "bibliography", "--out", str(target)).output)
    assert out["records"] == 11 and out["set"] == "included" and out["format"] == "csl"
    assert len(json.loads(target.read_text())) == 11
    _cli(
        repo,
        "export",
        "bibliography",
        "--format",
        "bibtex",
        "--set",
        "not-retrieved",
        "--out",
        str(tmp_path / "nr.bib"),
    )
    assert (tmp_path / "nr.bib").read_text().count("@article{") == 2


def test_bad_bibliography_options_are_usage_errors(tmp_path: Path) -> None:
    repo, _ = finished_review(tmp_path)
    _cli(repo, "export", "bibliography", "--set", "everything", code=EXIT_USAGE)
    _cli(repo, "export", "bibliography", "--format", "endnote", code=EXIT_USAGE)


def test_the_package_needs_a_licence_then_writes_without_full_text(tmp_path: Path) -> None:
    repo, _ = full_review(tmp_path)
    (repo.root / "fulltext").mkdir(exist_ok=True)
    (repo.root / "fulltext" / "paper.pdf").write_bytes(b"%PDF-1.4 a full text")
    _commit_all(repo)
    target = tmp_path / "supplement.zip"
    refused = _cli(repo, "export", "package", "--out", str(target), code=EXIT_USAGE)
    assert "project.license" in refused.output and not target.exists()
    _cli(repo, "config", "project.license", "CC-BY-4.0")
    _commit_all(repo)
    out = json.loads(_cli(repo, "--json", "export", "package", "--out", str(target)).output)
    archive = zipfile.ZipFile(io.BytesIO(target.read_bytes()))
    names = archive.namelist()
    assert out["files"] == len(names) and not [n for n in names if n.lower().endswith(".pdf")]
    assert gitio.current_commit(repo.root) in archive.read("README.md").decode()
    assert "CC-BY-4.0" in archive.read("LICENSE-DATA.txt").decode()
