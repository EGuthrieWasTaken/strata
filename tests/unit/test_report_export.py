"""Bibliography export by set and the reproducibility package (openspec:manuscript-generation)."""

# ruff: noqa: E501
from __future__ import annotations

import io
import json
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

from strata import gitio
from strata.core import records as records_mod
from strata.core.ids import normalise_doi
from strata.ingest.parsers import bibtex as bibtex_parser
from strata.ingest.parsers import csl_json as csl_parser
from strata.ingest.parsers import ris as ris_parser
from strata.protocol import retrieval as retrieval_mod
from strata.protocol import screening as screening_mod
from strata.report import bibliography as bib
from strata.report import package
from tests.unit._m5 import finished_review, full_review


def test_the_sets_are_the_ones_the_flow_diagram_counts(tmp_path: Path) -> None:
    repo, _ = finished_review(tmp_path)
    sizes = {name: len(bib.record_ids(repo, name)) for name in bib.SETS}
    assert sizes == {
        "included": 11,
        "excluded-at-fulltext": 4,
        "all-screened": 23,
        "not-retrieved": 2,
    }


def test_excluded_at_fulltext_is_exactly_the_records_excluded_at_full_text(tmp_path: Path) -> None:
    repo, _ = finished_review(tmp_path)
    ids = canonical = [r["id"] for r in records_mod.read_records(repo) if r["strata"]["canonical"]]
    states = screening_mod.stage_states(repo, "full-text", ids)
    expected = sorted(r for r in canonical if states[r].status == "exclude")
    assert bib.record_ids(repo, "excluded-at-fulltext") == expected and len(expected) == 4
    assert {r["id"] for r in bib.records(repo, "excluded-at-fulltext")} == set(expected)


def test_not_retrieved_matches_the_retrieval_log(tmp_path: Path) -> None:
    repo, _ = finished_review(tmp_path)
    assert bib.record_ids(repo, "not-retrieved") == sorted(
        retrieval_mod.not_retrieved_record_ids(repo)
    )


def test_an_unknown_set_or_format_is_refused(tmp_path: Path) -> None:
    repo, _ = finished_review(tmp_path)
    with pytest.raises(bib.BibliographyError, match="--set must be one of"):
        bib.record_ids(repo, "everything")
    with pytest.raises(bib.BibliographyError, match="--format must be one of"):
        bib.render(repo, fmt="endnote", set_name="included")


def test_csl_json_drops_the_internal_namespace_and_reads_back(tmp_path: Path) -> None:
    repo, _ = finished_review(tmp_path)
    text = bib.render(repo, fmt="csl", set_name="included")
    items = json.loads(text)
    assert len(items) == 11 and all("strata" not in i and i["id"].startswith("rec_") for i in items)
    assert [i["id"] for i in items] == sorted(i["id"] for i in items)
    parsed = csl_parser.parse(text)
    assert {r["title"] for r in parsed.records} == {
        i["title"] for i in items
    } and not parsed.rejected


def test_bibtex_has_unique_readable_keys_and_reads_back(tmp_path: Path) -> None:
    repo, _ = finished_review(tmp_path)
    text = bib.render(repo, fmt="bibtex", set_name="included")
    keys = [line.split("{", 1)[1].rstrip(",") for line in text.splitlines() if line.startswith("@")]
    assert len(keys) == len(set(keys)) == 11 and all(k.startswith("Author") for k in keys)
    assert "journal = {Journal of Testing}" in text and "doi = {10.5555/m5." in text
    parsed = bibtex_parser.parse(text)
    assert not parsed.rejected and len(parsed.records) == 11
    original = {normalise_doi(r["DOI"]) for r in bib.records(repo, "included")}
    assert {normalise_doi(r.get("DOI")) for r in parsed.records} == original


def test_bibtex_escapes_what_latex_would_choke_on() -> None:
    row = {
        "id": "rec_1",
        "type": "article-journal",
        "title": "Cost & benefit: 50% of #1_study",
        "author": [{"family": "Müller", "given": "A."}],
        "issued": {"date-parts": [[2020]]},
    }
    text = bib.to_bibtex([row])
    assert r"Cost \& benefit: 50\% of \#1\_study" in text and text.startswith(
        "@article{Muller2020,"
    )


def test_repeated_author_and_year_get_distinct_keys() -> None:
    rows = [
        {
            "id": f"rec_{i}",
            "title": "T",
            "author": [{"family": "Lee"}],
            "issued": {"date-parts": [[2020]]},
        }
        for i in (1, 2, 3)
    ]
    assert [
        line.split("{")[1].rstrip(",")
        for line in bib.to_bibtex(rows).splitlines()
        if line.startswith("@")
    ] == ["Lee2020", "Lee2020b", "Lee2020c"]


def test_ris_has_one_block_per_record_and_reads_back(tmp_path: Path) -> None:
    repo, _ = finished_review(tmp_path)
    text = bib.render(repo, fmt="ris", set_name="excluded-at-fulltext")
    assert text.count("TY  - JOUR") == 4 and text.count("ER  - ") == 4
    assert "ID  - rec_" in text
    parsed = ris_parser.parse(text)
    assert not parsed.rejected and len(parsed.records) == 4
    assert {r["title"] for r in parsed.records} == {
        r["title"] for r in bib.records(repo, "excluded-at-fulltext")
    }


def test_ris_pages_split_into_start_and_end() -> None:
    row = {
        "id": "rec_1",
        "title": "T",
        "page": "1097–1104",
        "author": [{"family": "Lee", "given": "A."}],
        "issued": {"date-parts": [[2008]]},
    }
    text = bib.to_ris([row])
    assert (
        "SP  - 1097" in text
        and "EP  - 1104" in text
        and "AU  - Lee, A." in text
        and "PY  - 2008" in text
    )


def test_output_is_deterministic(tmp_path: Path) -> None:
    repo, _ = finished_review(tmp_path)
    for fmt in bib.FORMATS:
        assert bib.render(repo, fmt=fmt, set_name="all-screened") == bib.render(
            repo, fmt=fmt, set_name="all-screened"
        )


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")
def test_csl_output_feeds_pandoc_directly(tmp_path: Path) -> None:
    repo, _ = finished_review(tmp_path)
    (tmp_path / "included.json").write_text(
        bib.render(repo, fmt="csl", set_name="included"), encoding="utf-8"
    )
    key = bib.record_ids(repo, "included")[0]
    done = subprocess.run(
        ["pandoc", "-f", "markdown", "-t", "plain", "--citeproc", "--bibliography", str(tmp_path / "included.json")],
        input=f"Spacing helps [@{key}].\n".encode(), capture_output=True, check=True,
    )  # fmt: skip
    assert b"Author" in done.stdout and key.encode() not in done.stdout


# --- the reproducibility package ------------------------------------------------------------


def _names(payload: bytes) -> list[str]:
    return zipfile.ZipFile(io.BytesIO(payload)).namelist()


def test_a_licence_is_required(tmp_path: Path) -> None:
    repo, _ = finished_review(tmp_path)
    with pytest.raises(package.PackageError, match="project.license"):
        package.build(repo)


def test_the_package_holds_what_item_27_asks_for_and_no_full_text(tmp_path: Path) -> None:
    repo, _ = full_review(tmp_path)
    repo.config["project"]["license"] = "CC-BY-4.0"
    (repo.root / "fulltext").mkdir(exist_ok=True)
    (repo.root / "fulltext" / "cepeda-2008.pdf").write_bytes(b"%PDF-1.4 a full text")
    (repo.root / "fulltext" / "sub").mkdir(exist_ok=True)
    (repo.root / "fulltext" / "sub" / "other.PDF").write_bytes(b"%PDF-1.4 another")
    (repo.root / "fulltext" / "manifest.ndjson").write_text(
        '{"report":"rpt_x"}\n', encoding="utf-8"
    )
    payload = package.build(repo)
    names = _names(payload)
    assert not [n for n in names if n.lower().endswith(".pdf")]
    assert "fulltext/manifest.ndjson" in names and "fulltext/cepeda-2008.pdf" not in names
    for expected in (
        "README.md",
        "LICENSE-DATA.txt",
        "strata.toml",
        "protocol/criteria.yaml",
        "analysis/primary.yaml",
        "analysis/results/primary/estimates.json",
        "derived/counts.json",
    ):
        assert expected in names, expected
    assert any(n.startswith("protocol/searches/") for n in names)
    assert any(n.startswith("events/screen/") for n in names) and any(
        n.startswith("events/criteria/") for n in names
    )
    assert (
        any(
            n.startswith("extraction/consensus/")
            or n.startswith("extraction/by-reviewer/")
            or n.startswith("extraction/working/")
            for n in names
        )
        or "extraction/schema.yaml" in names
    )
    assert not any(".git/" in n or ".strata/" in n or "/raw/" in n for n in names)


def test_the_readme_names_the_commit_and_the_licence_is_included(tmp_path: Path) -> None:
    repo, _ = full_review(tmp_path)
    repo.config["project"]["license"] = "CC-BY-4.0"
    gitio.add_all(repo.root)
    gitio.commit(repo.root, "test: fixture\n\nStrata-Op: test\nStrata-Actor: ethan")
    archive = zipfile.ZipFile(io.BytesIO(package.build(repo)))
    readme = archive.read("README.md").decode()
    assert gitio.current_commit(repo.root) in readme and "no full texts" in readme
    assert "CC-BY-4.0" in readme and "CC-BY-4.0" in archive.read("LICENSE-DATA.txt").decode()


def test_the_package_is_deterministic(tmp_path: Path) -> None:
    repo, _ = full_review(tmp_path)
    repo.config["project"]["license"] = "CC0-1.0"
    assert package.build(repo) == package.build(repo)
    infos = zipfile.ZipFile(io.BytesIO(package.build(repo))).infolist()
    assert {i.date_time for i in infos} == {(1980, 1, 1, 0, 0, 0)} and [
        i.filename for i in infos
    ] == sorted(i.filename for i in infos)
