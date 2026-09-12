import shutil
from pathlib import Path

import pytest

from strata.core.init import init_repository
from strata.core.repo import open_repo
from strata.core.validate import SchemaValidationError
from strata.protocol.searches import (
    PENDING_QUERY,
    SearchError,
    add_search,
    get_search,
    list_searches,
    next_search_id,
    pending_search_ids,
    searches_dir,
)


def _init(tmp_path: Path) -> Path:
    root = tmp_path / "review"
    init_repository(root, title="T", actor_handle="ethan", actor_name="Ethan")
    return root


def test_next_search_id_increments_per_database_slug(tmp_path: Path) -> None:
    repo = open_repo(_init(tmp_path))
    assert next_search_id(repo, "MEDLINE") == "S-01-medline"
    add_search(
        repo,
        database="MEDLINE",
        platform="Ovid",
        executed="2026-03-04",
        executed_by="ethan",
        query="1 exp Learning/",
    )
    assert next_search_id(repo, "MEDLINE") == "S-02-medline"
    # A different database starts its own numbering.
    assert next_search_id(repo, "Embase") == "S-01-embase"


def test_add_search_writes_valid_yaml_with_verbatim_query(tmp_path: Path) -> None:
    repo = open_repo(_init(tmp_path))
    query = "1  exp Learning/\n2  (spac* adj3 practice).ti,ab,kf.\n3  1 and 2\n"
    record = add_search(
        repo,
        database="MEDLINE",
        platform="Ovid",
        executed="2026-03-04",
        executed_by="ethan",
        query=query,
        hits=4182,
    )
    assert record["id"] == "S-01-medline"
    assert record["query"] == query.strip()

    path = repo.path("protocol", "searches", "S-01-medline.yaml")
    text = path.read_text(encoding="utf-8")
    assert "query: |" in text
    assert "1  exp Learning/" in text

    reloaded = get_search(repo, "S-01-medline")
    assert reloaded is not None
    assert reloaded["query"] == query.strip()
    assert reloaded["hits"] == 4182


def test_add_search_without_query_records_pending(tmp_path: Path) -> None:
    repo = open_repo(_init(tmp_path))
    record = add_search(
        repo,
        database="PsycINFO",
        platform="EBSCO",
        executed="2026-03-04",
        executed_by="ethan",
    )
    assert record["query"] == PENDING_QUERY
    assert pending_search_ids(repo) == [record["id"]]


def test_add_search_rejects_unknown_actor(tmp_path: Path) -> None:
    repo = open_repo(_init(tmp_path))
    with pytest.raises(SearchError, match="not a configured actor"):
        add_search(
            repo,
            database="MEDLINE",
            platform="Ovid",
            executed="2026-03-04",
            executed_by="nobody",
            query="q",
        )


def test_add_search_rejects_duplicate_id(tmp_path: Path) -> None:
    repo = open_repo(_init(tmp_path))
    add_search(
        repo,
        database="MEDLINE",
        platform="Ovid",
        executed="2026-03-04",
        executed_by="ethan",
        search_id="S-01-medline",
        query="q",
    )
    with pytest.raises(SearchError, match="already exists"):
        add_search(
            repo,
            database="MEDLINE",
            platform="Ovid",
            executed="2026-03-05",
            executed_by="ethan",
            search_id="S-01-medline",
            query="q2",
        )


def test_add_search_rejects_unknown_supersedes(tmp_path: Path) -> None:
    repo = open_repo(_init(tmp_path))
    with pytest.raises(SearchError, match="supersedes"):
        add_search(
            repo,
            database="MEDLINE",
            platform="Ovid",
            executed="2026-03-04",
            executed_by="ethan",
            query="q",
            supersedes="S-99-nope",
        )


def test_add_search_accepts_valid_supersedes_chain(tmp_path: Path) -> None:
    repo = open_repo(_init(tmp_path))
    first = add_search(
        repo,
        database="MEDLINE",
        platform="Ovid",
        executed="2026-03-04",
        executed_by="ethan",
        query="q1",
    )
    second = add_search(
        repo,
        database="MEDLINE",
        platform="Ovid",
        executed="2026-04-01",
        executed_by="ethan",
        query="q2",
        supersedes=first["id"],
    )
    assert second["supersedes"] == first["id"]


def test_add_search_rejects_malformed_executed_date(tmp_path: Path) -> None:
    repo = open_repo(_init(tmp_path))
    with pytest.raises(SchemaValidationError):
        add_search(
            repo,
            database="MEDLINE",
            platform="Ovid",
            executed="04 March 2026",
            executed_by="ethan",
            query="q",
        )


def test_list_searches_empty_before_any_recorded(tmp_path: Path) -> None:
    repo = open_repo(_init(tmp_path))
    assert list_searches(repo) == []


def test_list_searches_missing_directory_returns_empty(tmp_path: Path) -> None:
    repo = open_repo(_init(tmp_path))
    shutil.rmtree(searches_dir(repo))
    assert list_searches(repo) == []
    assert pending_search_ids(repo) == []


def test_list_searches_skips_blank_yaml_files(tmp_path: Path) -> None:
    repo = open_repo(_init(tmp_path))
    add_search(
        repo,
        database="MEDLINE",
        platform="Ovid",
        executed="2026-03-04",
        executed_by="ethan",
        query="q",
    )
    (searches_dir(repo) / "S-99-blank.yaml").write_text("", encoding="utf-8")
    ids = [s["id"] for s in list_searches(repo)]
    assert ids == ["S-01-medline"]


def test_add_search_records_notes_as_folded_scalar(tmp_path: Path) -> None:
    repo = open_repo(_init(tmp_path))
    record = add_search(
        repo,
        database="MEDLINE",
        platform="Ovid",
        executed="2026-03-04",
        executed_by="ethan",
        query="q",
        notes="Search strategy adapted from the protocol.",
    )
    assert record["notes"] == "Search strategy adapted from the protocol."
    reloaded = get_search(repo, record["id"])
    assert reloaded is not None
    assert "adapted from the protocol" in reloaded["notes"]


def test_list_searches_sorted_by_id(tmp_path: Path) -> None:
    repo = open_repo(_init(tmp_path))
    add_search(
        repo,
        database="Embase",
        platform="Ovid",
        executed="2026-03-04",
        executed_by="ethan",
        query="q",
    )
    add_search(
        repo,
        database="MEDLINE",
        platform="Ovid",
        executed="2026-03-04",
        executed_by="ethan",
        query="q",
    )
    ids = [s["id"] for s in list_searches(repo)]
    assert ids == sorted(ids)
    assert len(ids) == 2
