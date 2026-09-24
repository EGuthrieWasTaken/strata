"""Unit tests for strata.core.aliases."""

from __future__ import annotations

import tomllib
from pathlib import Path

from strata.core.aliases import append_alias, read_aliases, remove_alias, resolve
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


def test_read_aliases_missing_file_returns_empty(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    assert read_aliases(repo) == []


def test_append_and_read_alias(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    append_alias(repo, alias="rec_a", canonical="rec_b", reason="dedup", event="ev_x")
    entries = read_aliases(repo)
    assert entries == [{"alias": "rec_a", "canonical": "rec_b", "reason": "dedup", "event": "ev_x"}]


def test_append_multiple_aliases(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    append_alias(repo, alias="rec_a", canonical="rec_c", reason="dedup", event="ev_1")
    append_alias(repo, alias="rec_b", canonical="rec_c", reason="dedup", event="ev_2")
    assert len(read_aliases(repo)) == 2


def test_resolve_non_alias_returns_itself(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    assert resolve(repo, "rec_unknown") == "rec_unknown"


def test_resolve_direct_alias(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    append_alias(repo, alias="rec_a", canonical="rec_b", reason="dedup", event="ev_1")
    assert resolve(repo, "rec_a") == "rec_b"


def test_resolve_transitive_chain(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    append_alias(repo, alias="rec_a", canonical="rec_b", reason="dedup", event="ev_1")
    append_alias(repo, alias="rec_b", canonical="rec_c", reason="dedup", event="ev_2")
    assert resolve(repo, "rec_a") == "rec_c"


def test_resolve_stops_on_cycle_rather_than_looping_forever(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    append_alias(repo, alias="rec_a", canonical="rec_b", reason="dedup", event="ev_1")
    append_alias(repo, alias="rec_b", canonical="rec_a", reason="dedup", event="ev_2")
    # A cycle is an E_ALIAS_CYCLE per `strata verify`; `resolve` just must not hang.
    result = resolve(repo, "rec_a")
    assert result in {"rec_a", "rec_b"}


def test_remove_alias_returns_removed_entry(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    append_alias(repo, alias="rec_a", canonical="rec_b", reason="dedup", event="ev_1")
    removed = remove_alias(repo, "rec_a")
    assert removed == {"alias": "rec_a", "canonical": "rec_b", "reason": "dedup", "event": "ev_1"}
    assert read_aliases(repo) == []


def test_remove_alias_missing_returns_none(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    assert remove_alias(repo, "rec_nonexistent") is None


def test_remove_alias_only_removes_first_match(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    append_alias(repo, alias="rec_a", canonical="rec_b", reason="dedup", event="ev_1")
    append_alias(repo, alias="rec_c", canonical="rec_b", reason="dedup", event="ev_2")
    remove_alias(repo, "rec_a")
    remaining = read_aliases(repo)
    assert len(remaining) == 1
    assert remaining[0]["alias"] == "rec_c"
