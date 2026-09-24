"""Unit tests for strata.core.records."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from strata.core.records import get_record, index_by_id, read_records, records_path, write_records
from strata.core.repo import Repo
from strata.core.validate import SchemaValidationError

_MANIFEST = """\
schema_version = 1
created_with = "strata/0.1.0"

[project]
id = "prj_x"
title = "T"
slug = "t"
created = "2026-01-01"

[[actors]]
handle = "ethan"
name = "Ethan"
role = "lead"
"""


def _repo(tmp_path: Path) -> Repo:
    (tmp_path / "strata.toml").write_text(_MANIFEST, encoding="utf-8")
    return Repo(root=tmp_path, config=tomllib.loads(_MANIFEST))


def _record(record_id: str, title: str = "T") -> dict:
    return {
        "id": record_id,
        "type": "article-journal",
        "title": title,
        "strata": {
            "canonical_key": f"sig:{title.lower()}",
            "canonical": True,
            "sources": [{"import": "imp_01arz3ndektsv4rrffq69g5fav"}],
        },
    }


def test_read_records_missing_file_returns_empty(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    assert read_records(repo) == []


def test_write_then_read_round_trips(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    records = [_record("rec_0000000000000002"), _record("rec_0000000000000001")]
    write_records(repo, records)
    reloaded = read_records(repo)
    assert [r["id"] for r in reloaded] == ["rec_0000000000000001", "rec_0000000000000002"]


def test_write_records_sorts_on_disk_byte_wise(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    write_records(repo, [_record("rec_zzzzzzzzzzzzzzzz"), _record("rec_0000000000000001")])
    text = records_path(repo).read_text(encoding="utf-8")
    lines = [line for line in text.split("\n") if line]
    assert lines[0].startswith('{"author"') is False  # sanity: not asserting field order here
    assert '"id":"rec_0000000000000001"' in lines[0]
    assert '"id":"rec_zzzzzzzzzzzzzzzz"' in lines[1]


def test_write_records_rejects_invalid_record(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    invalid = _record("rec_0000000000000001")
    del invalid["title"]
    with pytest.raises(SchemaValidationError):
        write_records(repo, [invalid])


def test_index_by_id(tmp_path: Path) -> None:
    records = [_record("rec_0000000000000001"), _record("rec_0000000000000002")]
    index = index_by_id(records)
    assert set(index) == {"rec_0000000000000001", "rec_0000000000000002"}
    assert index["rec_0000000000000001"]["id"] == "rec_0000000000000001"


def test_get_record_found_and_missing(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    write_records(repo, [_record("rec_0000000000000001")])
    assert get_record(repo, "rec_0000000000000001") is not None
    assert get_record(repo, "rec_nonexistent0000") is None


def test_read_records_skips_blank_lines(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    write_records(repo, [_record("rec_0000000000000001")])
    path = records_path(repo)
    path.write_text(path.read_text(encoding="utf-8") + "\n\n", encoding="utf-8")
    assert len(read_records(repo)) == 1
