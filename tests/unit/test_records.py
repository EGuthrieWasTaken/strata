"""Unit tests for strata.core.records."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from strata.core.events import iter_event_files, read_events
from strata.core.filters import FilterEvaluationError
from strata.core.records import (
    AmbiguousRecordIdError,
    FixFieldError,
    RecordNotFoundError,
    amend_field,
    get_record,
    index_by_id,
    read_records,
    record_field_resolver,
    records_path,
    resolve_id_prefix,
    write_records,
)
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


# ---- resolve_id_prefix --------------------------------------------------------


def test_resolve_id_prefix_unambiguous(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    write_records(repo, [_record("rec_0000000000000001"), _record("rec_1111111111111111")])
    assert resolve_id_prefix(repo, "rec_000") == "rec_0000000000000001"


def test_resolve_id_prefix_full_id(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    write_records(repo, [_record("rec_0000000000000001")])
    assert resolve_id_prefix(repo, "rec_0000000000000001") == "rec_0000000000000001"


def test_resolve_id_prefix_no_match_raises(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    write_records(repo, [_record("rec_0000000000000001")])
    with pytest.raises(RecordNotFoundError):
        resolve_id_prefix(repo, "rec_zzz")


def test_resolve_id_prefix_ambiguous_raises(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    write_records(repo, [_record("rec_0000000000000001"), _record("rec_0000000000000002")])
    with pytest.raises(AmbiguousRecordIdError) as exc_info:
        resolve_id_prefix(repo, "rec_000")
    assert exc_info.value.matches == ["rec_0000000000000001", "rec_0000000000000002"]
    assert "rec_0000000000000001" in str(exc_info.value)


# ---- record_field_resolver -----------------------------------------------------


def _full_record() -> dict:
    return {
        "id": "rec_0000000000000001",
        "type": "article-journal",
        "title": "A Title",
        "abstract": "An abstract.",
        "DOI": "10.1000/x",
        "PMID": "12345",
        "container-title": "A Journal",
        "issued": {"date-parts": [[2020]]},
        "author": [{"family": "Smith"}, {"family": "Jones"}, "not-a-dict", {"given": "no-family"}],
        "strata": {
            "canonical_key": "sig:a-title",
            "canonical": True,
            "sources": [
                {"import": "imp_01arz3ndektsv4rrffq69g5fav", "via": "database", "search": "S-01"},
                {"import": "imp_01arz3ndektsv4rrffq69g5fav", "via": "citation-searching"},
            ],
        },
    }


@pytest.mark.parametrize(
    ("field", "expected"),
    [
        ("id", "rec_0000000000000001"),
        ("doi", "10.1000/x"),
        ("pmid", "12345"),
        ("title", "A Title"),
        ("abstract", "An abstract."),
        ("journal", "A Journal"),
        ("year", 2020),
        ("authors", ["Smith", "Jones"]),
        ("via", "database"),
        ("search", "S-01"),
    ],
)
def test_record_field_resolver_known_fields(field: str, expected: object) -> None:
    resolve = record_field_resolver(_full_record())
    assert resolve(field) == expected


def test_record_field_resolver_missing_optional_fields_are_falsy_defaults() -> None:
    resolve = record_field_resolver(
        {"id": "rec_0000000000000001", "type": "article-journal", "title": "T", "strata": {}}
    )
    assert resolve("doi") is None
    assert resolve("pmid") is None
    assert resolve("abstract") == ""
    assert resolve("journal") == ""
    assert resolve("year") is None
    assert resolve("authors") == []
    assert resolve("via") is None
    assert resolve("search") is None


@pytest.mark.parametrize(
    "field", ["tiab", "fulltext", "stale", "criteria", "rob_overall", "derived_from_pvalue"]
)
def test_record_field_resolver_not_yet_available_scalar_fields(field: str) -> None:
    resolve = record_field_resolver(_full_record())
    with pytest.raises(FilterEvaluationError, match="not available yet"):
        resolve(field)


@pytest.mark.parametrize("field", ["actor_decision.ethan", "rob.selection"])
def test_record_field_resolver_not_yet_available_prefixed_fields(field: str) -> None:
    resolve = record_field_resolver(_full_record())
    with pytest.raises(FilterEvaluationError, match="not available yet"):
        resolve(field)


def test_record_field_resolver_unknown_field_raises() -> None:
    resolve = record_field_resolver(_full_record())
    with pytest.raises(FilterEvaluationError, match="unknown filter field"):
        resolve("not_a_real_field")


# ---- amend_field ----------------------------------------------------------------


def test_amend_field_updates_value_and_returns_old_new(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    write_records(repo, [_record("rec_0000000000000001", title="Old Title")])
    old, new = amend_field(
        repo, record_id="rec_0000000000000001", field="title", value="New Title", actor="ethan"
    )
    assert old == "Old Title"
    assert new == "New Title"
    assert get_record(repo, "rec_0000000000000001")["title"] == "New Title"


def test_amend_field_appends_record_amend_event(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    write_records(repo, [_record("rec_0000000000000001", title="Old Title")])
    amend_field(
        repo, record_id="rec_0000000000000001", field="title", value="New Title", actor="ethan"
    )
    events = [e for path in iter_event_files(repo.root) for e in read_events(path)]
    amend_events = [e for e in events if e["ev"] == "record-amend"]
    assert len(amend_events) == 1
    assert amend_events[0]["body"] == {
        "record": "rec_0000000000000001",
        "field": "title",
        "old": "Old Title",
        "new": "New Title",
        "source": "manual",
    }


def test_amend_field_unknown_record_raises(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    write_records(repo, [_record("rec_0000000000000001")])
    with pytest.raises(RecordNotFoundError):
        amend_field(repo, record_id="rec_nonexistent0000", field="title", value="x", actor="ethan")


def test_amend_field_rejects_structured_field(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    write_records(repo, [_record("rec_0000000000000001")])
    with pytest.raises(FixFieldError, match="author"):
        amend_field(
            repo, record_id="rec_0000000000000001", field="author", value="x", actor="ethan"
        )


def test_amend_field_rejects_identity_field(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    write_records(repo, [_record("rec_0000000000000001")])
    with pytest.raises(FixFieldError):
        amend_field(repo, record_id="rec_0000000000000001", field="id", value="x", actor="ethan")
