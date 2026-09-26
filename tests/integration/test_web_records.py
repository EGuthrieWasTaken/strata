"""Integration tests for the read-only `/records`, `/records/<id>`
screens: openspec:web-ui#screens, reusing exactly the CLI's own data
paths (`core.filters`, `core.provenance.build_provenance`)."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from strata.core.init import init_repository
from strata.core.repo import open_repo
from strata.ingest.pipeline import import_file
from strata.web.app import create_app

_TOKEN = "test-session-token-0123456789"

_CSL_RECORDS = """\
[
  {
    "id": "1",
    "type": "article-journal",
    "title": "A study of spaced retrieval practice",
    "author": [{"family": "Cepeda", "given": "Nicholas"}],
    "issued": {"date-parts": [[2019]]},
    "container-title": "Psychological Science",
    "DOI": "10.1111/webrecords.one",
    "abstract": "An abstract about retrieval practice."
  },
  {
    "id": "2",
    "type": "article-journal",
    "title": "A survey of testing effects",
    "author": [{"family": "Roediger", "given": "Henry"}],
    "issued": {"date-parts": [[2009]]},
    "container-title": "Annual Review of Psychology",
    "DOI": "10.1111/webrecords.two"
  }
]
"""


def _repo_with_records(tmp_path: Path):  # type: ignore[no-untyped-def]
    root = tmp_path / "review"
    init_repository(root, title="Records Test", actor_handle="ethan", actor_name="Ethan")
    repo = open_repo(root)
    export = tmp_path / "export.json"
    export.write_text(_CSL_RECORDS, encoding="utf-8")
    import_file(repo, export, imported_by="ethan", via="registry")
    return open_repo(root)


def _client(repo) -> TestClient:  # type: ignore[no-untyped-def]
    app = create_app(repo_root=repo.root, actor="ethan", session_token=_TOKEN)
    client = TestClient(app, base_url="http://127.0.0.1:8000")
    r = client.get(f"/?token={_TOKEN}")
    assert r.status_code == 200
    return client


def _first_record_id(repo) -> str:  # type: ignore[no-untyped-def]
    from strata.core.records import read_records

    (record,) = [r for r in read_records(repo) if r.get("DOI") == "10.1111/webrecords.one"]
    return str(record["id"])


def test_records_list_shows_every_canonical_record(tmp_path: Path) -> None:
    repo = _repo_with_records(tmp_path)
    client = _client(repo)
    r = client.get("/records")
    assert r.status_code == 200
    assert "A study of spaced retrieval practice" in r.text
    assert "A survey of testing effects" in r.text
    assert "2 records" in r.text


def test_records_list_filter_narrows_results(tmp_path: Path) -> None:
    repo = _repo_with_records(tmp_path)
    client = _client(repo)
    r = client.get("/records?filter=year>2015")
    assert r.status_code == 200
    assert "A study of spaced retrieval practice" in r.text
    assert "A survey of testing effects" not in r.text
    assert "1 record" in r.text


def test_records_list_filter_with_no_matches(tmp_path: Path) -> None:
    repo = _repo_with_records(tmp_path)
    client = _client(repo)
    r = client.get("/records?filter=year>2050")
    assert r.status_code == 200
    assert "0 records" in r.text


def test_records_list_invalid_filter_syntax_shows_an_error(tmp_path: Path) -> None:
    repo = _repo_with_records(tmp_path)
    client = _client(repo)
    r = client.get("/records?filter=" + "and and and")
    assert r.status_code == 200
    assert "invalid filter" in r.text


def test_records_list_filter_evaluation_error_shows_an_error(tmp_path: Path) -> None:
    """Syntactically valid but referring to a field that can't be resolved
    (openspec:filter-language's fields not implemented in M2, e.g. `tiab`/
    `stale`/`rob_overall`) -- a distinct failure mode from a parse error,
    both surfaced the same way."""
    repo = _repo_with_records(tmp_path)
    client = _client(repo)
    r = client.get("/records", params={"filter": "not_a_real_field == 1"})
    assert r.status_code == 200
    assert "filter failed" in r.text


def test_records_list_links_to_detail_pages(tmp_path: Path) -> None:
    repo = _repo_with_records(tmp_path)
    record_id = _first_record_id(repo)
    client = _client(repo)
    r = client.get("/records")
    assert f"/records/{record_id}" in r.text


def test_record_detail_shows_metadata_and_provenance(tmp_path: Path) -> None:
    repo = _repo_with_records(tmp_path)
    record_id = _first_record_id(repo)
    client = _client(repo)
    r = client.get(f"/records/{record_id}")
    assert r.status_code == 200
    assert "A study of spaced retrieval practice" in r.text
    assert "Cepeda" in r.text
    assert "10.1111/webrecords.one" in r.text
    assert "Provenance" in r.text
    assert "IMPORT" in r.text.upper()


def test_record_detail_unknown_id_is_404(tmp_path: Path) -> None:
    repo = _repo_with_records(tmp_path)
    client = _client(repo)
    r = client.get("/records/rec_nonexistent0000")
    assert r.status_code == 404
