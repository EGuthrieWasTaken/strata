"""`integrations/zotero.ndjson` (openspec:zotero-integration#identity-mapping)."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from strata.core.repo import Repo
from strata.core.validate import SchemaValidationError
from strata.integrations.zotero.mapping import (
    CREATED,
    MappingRow,
    absorbed_into,
    append_rows,
    canonical_record_id,
    current_rows,
    mapping_path,
    read_mapping,
    row_for_record,
)

_REC = "rec_3kq8v1r0zx2m4a7b"
_OTHER = "rec_0000000000000001"
_LIB = "users/12345"

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
    return Repo(root=tmp_path, config=tomllib.loads(_MANIFEST))


def _row(
    record: str = _REC,
    key: str = "AB3D9XYZ",
    version: int = 8842,
    linked: str = "2026-03-28",
    via: str = "doi",
    library: str = _LIB,
) -> MappingRow:
    return MappingRow(record, library, key, version, linked, via)


def test_a_row_is_written_as_one_canonical_line_of_the_documented_shape(tmp_path: Path) -> None:
    repo = _repo(tmp_path)

    assert append_rows(repo, [_row()]) == 1

    assert mapping_path(repo).read_text(encoding="utf-8") == (
        '{"item_key":"AB3D9XYZ","item_version":8842,"library":"users/12345","linked":"2026-03-28",'
        '"record":"rec_3kq8v1r0zx2m4a7b","via":"doi"}\n'
    )
    assert read_mapping(repo) == [_row()]


def test_rows_are_appended_never_rewritten(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    append_rows(repo, [_row()])
    first = mapping_path(repo).read_bytes()

    append_rows(repo, [_row(version=9000)])

    assert mapping_path(repo).read_bytes().startswith(first)
    assert len(read_mapping(repo)) == 2


def test_a_missing_file_is_an_empty_mapping(tmp_path: Path) -> None:
    assert read_mapping(_repo(tmp_path)) == []


@pytest.mark.parametrize(
    "bad",
    [
        _row(key="lower123"),
        _row(library="library/1"),
        _row(via="guessed"),
        _row(record="rec_short"),
        _row(linked="March"),
    ],
)
def test_an_invalid_row_is_refused_and_nothing_is_written(tmp_path: Path, bad: MappingRow) -> None:
    repo = _repo(tmp_path)

    with pytest.raises(SchemaValidationError):
        append_rows(repo, [_row(key="CD4E5FGH"), bad])

    assert not mapping_path(repo).exists()  # not even the valid row before it


def test_an_item_strata_created_is_marked_as_such() -> None:
    assert _row(via=CREATED).created_by_strata is True
    assert _row(via="doi").created_by_strata is False


def test_the_highest_version_of_a_link_is_the_one_that_counts() -> None:
    rows = [_row(version=8842), _row(version=9001), _row(version=8900)]

    assert [r.item_version for r in current_rows(rows, _LIB)] == [9001]


def test_a_later_row_wins_a_tie_and_other_libraries_are_ignored() -> None:
    rows = [
        _row(version=5, via="doi"),
        _row(version=5, via="pmid"),
        _row(version=5, library="groups/777"),
    ]

    (kept,) = current_rows(rows, _LIB)

    assert kept.via == "pmid"


def test_different_items_for_one_record_are_each_kept() -> None:
    rows = [_row(key="AB3D9XYZ"), _row(key="CD4E5FGH")]

    assert {r.item_key for r in current_rows(rows, _LIB)} == {"AB3D9XYZ", "CD4E5FGH"}


def test_the_item_for_a_record_is_the_most_recently_linked() -> None:
    rows = [
        _row(key="AB3D9XYZ", linked="2026-01-01"),
        _row(key="CD4E5FGH", linked="2026-03-01"),
    ]

    chosen = row_for_record(rows, _LIB, _REC)

    assert chosen is not None and chosen.item_key == "CD4E5FGH"
    assert row_for_record(rows, _LIB, _OTHER) is None
    assert row_for_record(rows, "groups/777", _REC) is None


def test_a_row_for_a_record_merged_away_serves_the_record_that_took_it_in() -> None:
    rows = [_row(record=_OTHER)]

    assert row_for_record(rows, _LIB, _REC) is None
    chosen = row_for_record(rows, _LIB, _REC, follow={_OTHER: _REC})
    assert chosen is not None and chosen.record == _OTHER


def test_absorbed_records_resolve_to_the_canonical_one_and_vanished_ones_to_none() -> None:
    records = [
        {"id": _REC, "strata": {"canonical": True, "absorbed": [_OTHER]}},
        {"id": _OTHER, "strata": {"canonical": False}},
    ]
    absorbed = absorbed_into(records)
    known = {r["id"]: r for r in records}

    assert absorbed == {_OTHER: _REC}
    assert canonical_record_id(_OTHER, known, absorbed) == _REC
    assert canonical_record_id(_REC, known, absorbed) == _REC
    assert canonical_record_id("rec_ffffffffffffffff", known, absorbed) is None
