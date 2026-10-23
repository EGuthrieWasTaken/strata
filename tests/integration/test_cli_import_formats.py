"""`strata import` of EndNote XML, Excel workbooks and plain-text citation lists
(openspec:literature-import#supported-import-formats)."""

# ruff: noqa: E501
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from typer.testing import CliRunner

from strata.cli.main import EXIT_OK, EXIT_USAGE, app
from strata.core import records as records_mod
from strata.core.canon import load_yaml_str
from strata.core.repo import Repo, open_repo
from strata.dedup import engine as dedup_engine
from strata.ingest.pipeline import IMPORTS_DIR
from tests.unit._m3 import init_review
from tests.unit._m5 import import_papers, paper, search
from tests.unit._xlsx import build_xlsx

runner = CliRunner()
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "exports"


def _import(repo: Repo, *args: str, code: int = EXIT_OK) -> Any:
    result = runner.invoke(
        app,
        [
            "--json",
            "--why",
            "Importing this export for the review.",
            "-C",
            str(repo.root),
            "import",
            *args,
            "--by",
            "ethan",
        ],
    )
    assert result.exit_code == code, result.output
    return result


def _manifest(repo: Repo, import_id: str) -> dict[str, Any]:
    return dict(load_yaml_str(repo.path(*IMPORTS_DIR, import_id, "manifest.yaml").read_text()))


MAPPING = "title=Title,author=Authors,year=Year,DOI=DOI"
WORKBOOK = {
    "Export": [
        ["Title", "Authors", "Year", "DOI"],
        [
            "Spacing effects in learning",
            "Cepeda, Nicholas",
            2008,
            "10.1111/j.1467-9280.2008.02209.x",
        ],
        ["Retrieval practice and recall", "Roediger, Henry", 2006, None],
    ],
    "Other": [
        ["Title", "Authors", "Year", "DOI"],
        ["A different sheet", "Someone, A.", 1999, None],
    ],
}


def test_an_excel_export_is_imported_from_its_first_sheet(tmp_path: Path) -> None:
    repo = init_review(tmp_path)
    book = tmp_path / "export.xlsx"
    book.write_bytes(build_xlsx(WORKBOOK))
    out = json.loads(_import(repo, str(book), "--via", "website", "--map", MAPPING).output)[0]
    assert out["format"] == "xlsx" and out["encoding"] == "xlsx" and out["records_created"] == 2
    manifest = _manifest(repo, out["import_id"])
    assert (manifest["format"], manifest["sheet"]) == ("xlsx", "Export")
    assert sorted(r["title"] for r in records_mod.read_records(repo)) == [
        "Retrieval practice and recall", "Spacing effects in learning",
    ]  # fmt: skip
    assert (
        repo.path(*IMPORTS_DIR, out["import_id"], "raw", "export.xlsx")
    ).read_bytes() == book.read_bytes()


def test_a_sheet_can_be_chosen_by_name_or_position(tmp_path: Path) -> None:
    repo = init_review(tmp_path)
    book = tmp_path / "export.xlsx"
    book.write_bytes(build_xlsx(WORKBOOK))
    out = json.loads(
        _import(repo, str(book), "--via", "website", "--map", MAPPING, "--sheet", "Other").output
    )[0]
    assert _manifest(repo, out["import_id"])["sheet"] == "Other"
    assert [r["title"] for r in records_mod.read_records(repo)] == ["A different sheet"]
    again = tmp_path / "again.xlsx"
    again.write_bytes(build_xlsx({"First": WORKBOOK["Export"], "Second": WORKBOOK["Other"]}))
    out = json.loads(
        _import(
            repo, str(again), "--via", "website", "--map", MAPPING, "--sheet", "2", "--dry-run"
        ).output
    )[0]
    assert out["rows_read"] == 1  # the second sheet's one row, not the first sheet's two


def test_re_importing_the_same_workbook_is_idempotent(tmp_path: Path) -> None:
    repo = init_review(tmp_path)
    book = tmp_path / "export.xlsx"
    book.write_bytes(build_xlsx(WORKBOOK))
    _import(repo, str(book), "--via", "website", "--map", MAPPING)
    second = json.loads(_import(repo, str(book), "--via", "website", "--map", MAPPING).output)[0]
    assert second["already_imported"] is True and second["records_created"] == 0


def test_a_workbook_that_cannot_be_read_is_a_usage_error_naming_the_file(tmp_path: Path) -> None:
    repo = init_review(tmp_path)
    bad = tmp_path / "broken.xlsx"
    bad.write_bytes(b"this is not a zip file")
    out = json.loads(_import(repo, str(bad), "--via", "website", code=EXIT_USAGE).output)[0]
    assert "broken.xlsx" in out["error"] and "not an .xlsx workbook" in out["error"]
    assert not repo.path("imports").exists() or not list(repo.path("imports").iterdir())


def test_sheet_only_applies_to_a_workbook(tmp_path: Path) -> None:
    repo = init_review(tmp_path)
    shutil.copy(FIXTURES / "ris" / "clean.ris", tmp_path / "clean.ris")
    out = json.loads(
        _import(
            repo, str(tmp_path / "clean.ris"), "--via", "website", "--sheet", "1", code=EXIT_USAGE
        ).output
    )[0]
    assert "--sheet only applies" in out["error"]


def test_an_endnote_export_is_detected_by_its_extension_and_bad_records_are_set_aside(
    tmp_path: Path,
) -> None:
    repo = init_review(tmp_path)
    shutil.copy(FIXTURES / "endnote-xml" / "malformed.xml", tmp_path / "library.xml")
    out = json.loads(_import(repo, str(tmp_path / "library.xml"), "--via", "website").output)[0]
    assert (
        out["format"] == "endnote-xml" and out["records_created"] == 2 and out["rows_rejected"] == 2
    )
    rejected = repo.path(*IMPORTS_DIR, out["import_id"], "rejected.txt").read_text(encoding="utf-8")
    assert "line 11" in rejected and "line 16" in rejected and "missing or empty title" in rejected
    assert {r["title"] for r in records_mod.read_records(repo)} == {
        "Salt & pepper: an unescaped ampersand in a title", "A valid record after the bad ones",
    }  # fmt: skip


def test_a_citation_list_is_sniffed_and_every_record_is_flagged_for_a_person(
    tmp_path: Path,
) -> None:
    repo = init_review(tmp_path)
    shutil.copy(FIXTURES / "citation-list" / "mixed.txt", tmp_path / "other-sources.txt")
    out = json.loads(
        _import(repo, str(tmp_path / "other-sources.txt"), "--via", "citation-searching").output
    )[0]
    assert (
        out["format"] == "citation-list"
        and out["records_created"] == 3
        and out["rows_rejected"] == 1
    )
    records = records_mod.read_records(repo)
    assert all(r["strata"]["flags"] == ["best-effort-parse"] for r in records)


def test_a_text_file_that_is_nothing_known_says_how_to_name_its_format(tmp_path: Path) -> None:
    repo = init_review(tmp_path)
    (tmp_path / "notes.txt").write_text("just some notes\nnothing like a list\n", encoding="utf-8")
    out = json.loads(
        _import(repo, str(tmp_path / "notes.txt"), "--via", "website", code=EXIT_USAGE).output
    )[0]
    assert "citation-list" in out["error"]
    forced = json.loads(
        _import(
            repo, str(tmp_path / "notes.txt"), "--via", "website", "--format", "citation-list"
        ).output
    )[0]
    assert forced["records_created"] == 0 and forced["rows_rejected"] >= 1


# --- deduplication leaves such records for a person ---------------------------------------------------


def test_a_best_effort_record_is_never_merged_automatically(tmp_path: Path) -> None:
    repo = init_review(tmp_path)
    search_id = search(repo, "MEDLINE")
    # the same paper once with its DOI and once without: different record ids, a score of 1.0
    full = {
        **paper(1),
        "author": [{"family": "Author1", "given": "A."}, {"family": "Second", "given": "B."}],
        "volume": "5",
        "page": "10-20",
    }
    import_papers(repo, tmp_path, "a.json", [full, {**full, "DOI": ""}], search_id=search_id)
    repo = open_repo(repo.root)

    control = dedup_engine.preview_dedup(repo)
    assert (
        len(control.auto_merged) == 1 and not control.review_queue
    )  # ordinary records merge on their own

    records = records_mod.read_records(repo)
    records[0].setdefault("strata", {})["flags"] = ["best-effort-parse"]
    records_mod.write_records(repo, records)
    flagged = dedup_engine.preview_dedup(open_repo(repo.root))
    assert not flagged.auto_merged
    assert len(flagged.review_queue) == 1  # a person decides
