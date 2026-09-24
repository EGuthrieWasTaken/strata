"""Unit tests for strata.ingest.pipeline (`strata import`'s domain logic)."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from strata.core.events import read_events
from strata.core.init import init_repository
from strata.core.records import read_records
from strata.core.repo import Repo, open_repo
from strata.core.verify import verify_repository
from strata.ingest.pipeline import (
    ImportPipelineError,
    detect_format,
    import_file,
    list_import_manifests,
)
from strata.protocol.searches import add_search

_CLEAN_CSL = """\
[
  {"title": "First paper", "DOI": "10.1000/aaa", "issued": {"date-parts": [[2020]]}},
  {"title": "Second paper", "DOI": "10.1000/bbb", "issued": {"date-parts": [[2021]]}}
]
"""

_MALFORMED_CSL = """\
[
  {"title": "Good paper", "DOI": "10.1000/ccc"},
  {"title": ""}
]
"""

_RIS_TEXT = "TY  - JOUR\nTI  - An RIS paper\nDO  - 10.1000/ris1\nER  - \n"

_MEDLINE_TEXT = "PMID- 1\nTI  - A MEDLINE paper\n"


def _repo(tmp_path: Path, name: str = "review") -> Repo:
    root = tmp_path / name
    init_repository(root, title="T", actor_handle="ethan", actor_name="Ethan")
    return open_repo(root)


def _with_search(repo: Repo) -> str:
    record = add_search(
        repo,
        database="MEDLINE",
        platform="Ovid",
        executed="2026-01-01",
        executed_by="ethan",
        query="q",
    )
    return str(record["id"])


def _write(tmp_path: Path, name: str, content: str) -> Path:
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return path


def test_import_file_creates_records_and_events(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    search_id = _with_search(repo)
    source = _write(tmp_path, "export.json", _CLEAN_CSL)

    outcome = import_file(repo, source, imported_by="ethan", search_id=search_id)

    assert outcome.already_imported is False
    assert outcome.records_created == 2
    assert outcome.rows_rejected == 0
    assert outcome.existing_ids_appended == 0
    assert outcome.format == "csl-json"
    assert outcome.encoding == "utf-8"

    records = read_records(repo)
    assert len(records) == 2
    titles = {r["title"] for r in records}
    assert titles == {"First paper", "Second paper"}
    for record in records:
        assert record["strata"]["canonical"] is True
        assert record["strata"]["sources"][0]["import"] == outcome.import_id
        assert record["strata"]["sources"][0]["search"] == search_id

    events_path = repo.path("events", "import", "ethan.ndjson")
    events = read_events(events_path)
    assert [e["ev"] for e in events] == ["record-add", "record-add", "import"]
    assert events[-1]["body"]["count"] == 2

    manifest_path = repo.path("imports", outcome.import_id, "manifest.yaml")
    assert manifest_path.exists()
    raw_path = repo.path("imports", outcome.import_id, "raw", "export.json")
    assert raw_path.read_text(encoding="utf-8") == _CLEAN_CSL

    report = verify_repository(repo)
    assert report.ok, report.issues


def test_import_file_is_idempotent_by_digest(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    search_id = _with_search(repo)
    source = _write(tmp_path, "export.json", _CLEAN_CSL)

    first = import_file(repo, source, imported_by="ethan", search_id=search_id)
    second = import_file(repo, source, imported_by="ethan", search_id=search_id)

    assert second.already_imported is True
    assert second.import_id == first.import_id
    assert len(read_records(repo)) == 2  # no duplicate records created

    events_path = repo.path("events", "import", "ethan.ndjson")
    assert len(read_events(events_path)) == 3  # unchanged from the first import


def test_import_file_appends_sources_on_exact_id_match(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    search_id = _with_search(repo)
    first_source = _write(tmp_path, "export1.json", _CLEAN_CSL)
    import_file(repo, first_source, imported_by="ethan", search_id=search_id)

    # Same DOI as "First paper" above -> same canonical key -> same record id.
    second_content = '[{"title": "First paper (reimported)", "DOI": "10.1000/aaa"}]'
    second_source = _write(tmp_path, "export2.json", second_content)
    outcome = import_file(repo, second_source, imported_by="ethan", search_id=search_id)

    assert outcome.records_created == 0
    assert outcome.existing_ids_appended == 1
    records = read_records(repo)
    assert len(records) == 2  # still just the original two records
    matching = [r for r in records if r["strata"]["canonical_key"] == "doi:10.1000/aaa"]
    assert len(matching) == 1
    assert len(matching[0]["strata"]["sources"]) == 2
    # No new record-add event for an append-only match.
    events = read_events(repo.path("events", "import", "ethan.ndjson"))
    assert sum(1 for e in events if e["ev"] == "record-add") == 2


def test_import_file_two_rows_in_same_batch_collapse_to_one_record(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    search_id = _with_search(repo)
    content = (
        '[{"title": "A", "DOI": "10.1000/same"}, {"title": "A duplicate", "DOI": "10.1000/same"}]'
    )
    source = _write(tmp_path, "dup.json", content)

    outcome = import_file(repo, source, imported_by="ethan", search_id=search_id)

    assert outcome.records_created == 1
    assert outcome.existing_ids_appended == 1
    records = read_records(repo)
    assert len(records) == 1
    assert len(records[0]["strata"]["sources"]) == 2


def test_import_file_writes_rejected_rows(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    search_id = _with_search(repo)
    source = _write(tmp_path, "export.json", _MALFORMED_CSL)

    outcome = import_file(repo, source, imported_by="ethan", search_id=search_id)

    assert outcome.records_created == 1
    assert outcome.rows_rejected == 1
    rejected_path = repo.path("imports", outcome.import_id, "rejected.txt")
    assert rejected_path.exists()
    assert "missing or empty title" in rejected_path.read_text(encoding="utf-8")


def test_import_file_dry_run_writes_nothing(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    search_id = _with_search(repo)
    source = _write(tmp_path, "export.json", _CLEAN_CSL)

    outcome = import_file(repo, source, imported_by="ethan", search_id=search_id, dry_run=True)

    assert outcome.dry_run is True
    assert outcome.records_created == 2
    assert read_records(repo) == []
    assert not (repo.path("imports", outcome.import_id)).exists()


def test_import_file_ris_and_medline_dispatch(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    search_id = _with_search(repo)
    ris_outcome = import_file(
        repo, _write(tmp_path, "e.ris", _RIS_TEXT), imported_by="ethan", search_id=search_id
    )
    assert ris_outcome.format == "ris"
    medline_outcome = import_file(
        repo, _write(tmp_path, "e.nbib", _MEDLINE_TEXT), imported_by="ethan", search_id=search_id
    )
    assert medline_outcome.format == "medline"


def test_import_file_txt_sniffs_ris_and_medline(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    search_id = _with_search(repo)
    ris_outcome = import_file(
        repo, _write(tmp_path, "e.txt", _RIS_TEXT), imported_by="ethan", search_id=search_id
    )
    assert ris_outcome.format == "ris"

    medline_outcome = import_file(
        repo,
        _write(tmp_path, "e2.txt", _MEDLINE_TEXT),
        imported_by="ethan",
        search_id=search_id,
    )
    assert medline_outcome.format == "medline"


def test_import_file_csv_with_detected_profile(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    search_id = _with_search(repo)
    content = (
        "Authors,Title,Year,Source title,Volume,Issue,DOI,EID\n"
        "Doe; Roe,A Scopus Paper,2020,A Journal,19,11,10.1000/scopus,2-s2.0-1\n"
    )
    outcome = import_file(
        repo, _write(tmp_path, "scopus.csv", content), imported_by="ethan", search_id=search_id
    )
    assert outcome.format == "csv"
    assert outcome.records_created == 1
    assert outcome.column_mapping is not None
    assert outcome.column_mapping["title"] == "Title"
    # The full Scopus profile also maps "abstract"/"keyword"/etc., but this
    # export doesn't have those columns -- only present columns are kept.
    assert "abstract" not in outcome.column_mapping
    assert "keyword" not in outcome.column_mapping
    records = read_records(repo)
    assert records[0]["title"] == "A Scopus Paper"
    assert records[0]["DOI"] == "10.1000/scopus"

    manifest_path = repo.path("imports", outcome.import_id, "manifest.yaml")
    manifest_text = manifest_path.read_text(encoding="utf-8")
    assert "column_mapping" in manifest_text
    assert "Title" in manifest_text


def test_import_file_tsv_with_explicit_map(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    search_id = _with_search(repo)
    content = "MyTitle\tMyAuthor\nA Title\tDoe, Jane\n"
    outcome = import_file(
        repo,
        _write(tmp_path, "custom.tsv", content),
        imported_by="ethan",
        search_id=search_id,
        mapping={"title": "MyTitle", "author": "MyAuthor"},
    )
    assert outcome.format == "tsv"
    records = read_records(repo)
    assert records[0]["title"] == "A Title"
    assert records[0]["author"] == [{"family": "Doe", "given": "Jane"}]


def test_import_file_csv_without_recognised_header_raises(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    search_id = _with_search(repo)
    content = "SomeColumn,OtherColumn\nx,y\n"
    with pytest.raises(ImportPipelineError, match="could not detect a known export platform"):
        import_file(
            repo, _write(tmp_path, "e.csv", content), imported_by="ethan", search_id=search_id
        )


def test_import_file_csv_invalid_map_raises(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    search_id = _with_search(repo)
    content = "Title\nT\n"
    with pytest.raises(ImportPipelineError, match="not found in header"):
        import_file(
            repo,
            _write(tmp_path, "e.csv", content),
            imported_by="ethan",
            search_id=search_id,
            mapping={"title": "Title", "author": "NoSuchColumn"},
        )


def test_detect_format_unrecognisable_txt_raises(tmp_path: Path) -> None:
    path = _write(tmp_path, "plain.txt", "just some free text\nwith no recognisable tags\n")
    with pytest.raises(ImportPipelineError, match="cannot determine the format"):
        detect_format(path, path.read_text(encoding="utf-8"))


def test_detect_format_unsupported_extension_raises(tmp_path: Path) -> None:
    path = _write(tmp_path, "e.xlsx", "n/a")
    with pytest.raises(ImportPipelineError, match="unsupported file extension"):
        detect_format(path, "n/a")


def test_detect_format_blank_txt_raises(tmp_path: Path) -> None:
    """All-blank content exhausts the sniff loop without ever `break`-ing out of it."""
    path = _write(tmp_path, "blank.txt", "\n\n   \n")
    with pytest.raises(ImportPipelineError, match="cannot determine the format"):
        detect_format(path, path.read_text(encoding="utf-8"))


def test_detect_format_skips_leading_blank_lines(tmp_path: Path) -> None:
    path = _write(tmp_path, "e.txt", "\n\n" + _RIS_TEXT)
    assert detect_format(path, path.read_text(encoding="utf-8")) == "ris"


def test_import_file_explicit_format_not_in_parser_table_raises(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    search_id = _with_search(repo)
    source = _write(tmp_path, "e.json", _CLEAN_CSL)
    with pytest.raises(ImportPipelineError, match="unsupported format"):
        import_file(repo, source, imported_by="ethan", search_id=search_id, fmt="endnote-xml")


def test_import_file_invalid_doi_left_unchanged(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    search_id = _with_search(repo)
    content = '[{"title": "T", "DOI": "not-a-real-doi"}]'
    import_file(repo, _write(tmp_path, "e.json", content), imported_by="ethan", search_id=search_id)
    records = read_records(repo)
    assert records[0]["DOI"] == "not-a-real-doi"


def test_list_import_manifests_missing_directory_returns_empty(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    shutil.rmtree(repo.path("imports"))
    assert list_import_manifests(repo) == []


def test_list_import_manifests_skips_blank_manifest_files(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    blank_dir = repo.path("imports", "imp_blank0000000000000000")
    blank_dir.mkdir(parents=True)
    (blank_dir / "manifest.yaml").write_text("", encoding="utf-8")
    assert list_import_manifests(repo) == []


def test_import_file_missing_file_raises(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    search_id = _with_search(repo)
    with pytest.raises(ImportPipelineError, match="no such file"):
        import_file(repo, tmp_path / "nope.json", imported_by="ethan", search_id=search_id)


def test_import_file_requires_exactly_one_of_search_or_via(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    source = _write(tmp_path, "e.json", _CLEAN_CSL)
    with pytest.raises(ImportPipelineError, match="exactly one of"):
        import_file(repo, source, imported_by="ethan")
    with pytest.raises(ImportPipelineError, match="exactly one of"):
        import_file(
            repo,
            source,
            imported_by="ethan",
            search_id=_with_search(repo),
            via="registry",
        )


def test_import_file_rejects_invalid_via(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    source = _write(tmp_path, "e.json", _CLEAN_CSL)
    with pytest.raises(ImportPipelineError, match="invalid --via"):
        import_file(repo, source, imported_by="ethan", via="not-a-real-via")


def test_import_file_accepts_via_without_search(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    source = _write(tmp_path, "e.json", _CLEAN_CSL)
    outcome = import_file(repo, source, imported_by="ethan", via="citation-searching")
    assert outcome.records_created == 2
    records = read_records(repo)
    assert all(r["strata"]["sources"][0]["via"] == "citation-searching" for r in records)


def test_import_file_rejects_unknown_search(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    source = _write(tmp_path, "e.json", _CLEAN_CSL)
    with pytest.raises(ImportPipelineError, match="unknown search"):
        import_file(repo, source, imported_by="ethan", search_id="S-99-nope")


def test_import_file_rejects_unknown_actor(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    search_id = _with_search(repo)
    source = _write(tmp_path, "e.json", _CLEAN_CSL)
    with pytest.raises(ImportPipelineError, match="not a configured actor"):
        import_file(repo, source, imported_by="nobody", search_id=search_id)


def test_import_file_explicit_format_overrides_detection(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    search_id = _with_search(repo)
    # A .txt file that would otherwise fail to sniff, forced to parse as RIS.
    source = _write(tmp_path, "e.txt", _RIS_TEXT)
    outcome = import_file(repo, source, imported_by="ethan", search_id=search_id, fmt="ris")
    assert outcome.format == "ris"


def test_import_file_normalises_doi_on_storage(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    search_id = _with_search(repo)
    content = '[{"title": "T", "DOI": "https://doi.org/10.1000/Upper."}]'
    import_file(repo, _write(tmp_path, "e.json", content), imported_by="ethan", search_id=search_id)
    records = read_records(repo)
    assert records[0]["DOI"] == "10.1000/upper"
