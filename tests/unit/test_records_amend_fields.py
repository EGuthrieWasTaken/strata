"""Batch field amendment from an external source (`strata.core.records.amend_fields`).

A reference manager pull corrects records with structured values (an author list, a date), not the
text a person types into `strata fix`. Each change is still an ordinary `record-amend` event, and a
change to a record's identity still keeps the record's id and makes the new identity an alias.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from strata.core import aliases as aliases_mod
from strata.core.events import iter_event_files, read_events
from strata.core.fieldedit import FixFieldError
from strata.core.ids import canonical_key, record_id
from strata.core.records import (
    FieldChange,
    RecordNotFoundError,
    amend_fields,
    read_records,
    write_records,
)
from strata.core.repo import Repo

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


def _record(title: str, **fields: object) -> dict:
    record: dict = {"type": "article-journal", "title": title, **fields}
    key, _ = canonical_key(record)
    record["id"] = record_id(key)
    record["strata"] = {
        "canonical_key": key,
        "canonical": True,
        "sources": [{"import": "imp_" + "0" * 26}],
    }
    return record


def _amend_events(repo: Repo) -> list[dict]:
    return [
        e for path in iter_event_files(repo.root) for e in read_events(path)
        if e["ev"] == "record-amend"
    ]  # fmt: skip


def test_a_changed_value_is_written_and_recorded_as_a_record_amend_event(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    original = _record("Spacing effect", DOI="10.1000/abc")
    write_records(repo, [original])

    result = amend_fields(
        repo,
        [FieldChange(original["id"], "title", "The spacing effect")],
        actor="ethan",
        source="zotero",
    )

    assert [a.changed for a in result] == [True]
    assert read_records(repo)[0]["title"] == "The spacing effect"
    (event,) = _amend_events(repo)
    assert event["actor"] == "ethan"
    assert event["body"] == {
        "record": original["id"],
        "field": "title",
        "old": "Spacing effect",
        "new": "The spacing effect",
        "source": "zotero",
    }


def test_structured_values_are_stored_as_given(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    original = _record("Spacing effect", DOI="10.1000/abc")
    write_records(repo, [original])
    authors = [{"family": "Cepeda", "given": "Nicholas"}]
    issued = {"date-parts": [[2008, 11]]}

    amend_fields(
        repo,
        [
            FieldChange(original["id"], "author", authors),
            FieldChange(original["id"], "issued", issued),
        ],
        actor="ethan",
        source="zotero",
    )

    stored = read_records(repo)[0]
    assert stored["author"] == authors
    assert stored["issued"] == issued
    assert len(_amend_events(repo)) == 2


def test_a_value_the_record_already_has_writes_nothing(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    original = _record("Spacing effect", DOI="10.1000/abc")
    write_records(repo, [original])
    before = (repo.root / "records" / "records.ndjson").read_bytes()

    result = amend_fields(
        repo,
        [FieldChange(original["id"], "title", "Spacing effect")],
        actor="ethan",
        source="zotero",
    )

    assert [a.changed for a in result] == [False]
    assert (repo.root / "records" / "records.ndjson").read_bytes() == before
    assert _amend_events(repo) == []


def test_a_correction_to_a_title_only_identity_keeps_the_id_and_aliases_the_new_one(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    original = _record("Spacing effect", issued={"date-parts": [[2008]]})
    write_records(repo, [original])
    assert original["strata"]["canonical_key"].startswith("sig:")

    (amendment,) = amend_fields(
        repo,
        [FieldChange(original["id"], "title", "The spacing effect")],
        actor="ethan",
        source="zotero",
    )

    assert read_records(repo)[0]["id"] == original["id"]
    assert amendment.alias is not None
    assert aliases_mod.resolve(repo, amendment.alias) == original["id"]


def test_one_write_serves_many_changes_to_many_records(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    first = _record("First", DOI="10.1000/a")
    second = _record("Second", DOI="10.1000/b")
    write_records(repo, [first, second])

    amend_fields(
        repo,
        [FieldChange(first["id"], "page", "1-9"), FieldChange(second["id"], "volume", "12")],
        actor="ethan",
        source="zotero",
    )

    by_id = {r["id"]: r for r in read_records(repo)}
    assert by_id[first["id"]]["page"] == "1-9"
    assert by_id[second["id"]]["volume"] == "12"
    assert [e["seq"] for e in _amend_events(repo)] == [1, 2]


def test_an_unknown_record_is_refused_before_anything_is_written(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    original = _record("Spacing effect", DOI="10.1000/abc")
    write_records(repo, [original])

    with pytest.raises(RecordNotFoundError):
        amend_fields(
            repo,
            [
                FieldChange(original["id"], "page", "1-9"),
                FieldChange("rec_0000000000000000", "page", "2"),
            ],
            actor="ethan",
            source="zotero",
        )

    assert "page" not in read_records(repo)[0]
    assert _amend_events(repo) == []


def test_a_field_that_is_not_bibliographic_is_refused(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    original = _record("Spacing effect", DOI="10.1000/abc")
    write_records(repo, [original])

    with pytest.raises(FixFieldError):
        amend_fields(
            repo, [FieldChange(original["id"], "strata", {})], actor="ethan", source="zotero"
        )
