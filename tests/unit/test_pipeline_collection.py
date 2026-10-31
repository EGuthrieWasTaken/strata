"""An import made from a reference-manager collection records which collection it was
(`strata.ingest.pipeline.import_file(collection=...)`; openspec:zotero-integration#commands)."""

from __future__ import annotations

from pathlib import Path

import pytest

from strata.core.init import init_repository
from strata.core.repo import Repo, open_repo
from strata.core.validate import SchemaValidationError
from strata.ingest.pipeline import import_file, list_import_manifests

_CSL = '[{"title": "First paper", "DOI": "10.1000/aaa"}]'
_COLLECTION = {
    "manager": "zotero",
    "library": "users/12345",
    "key": "AB3D9XYZ",
    "name": "Hand-searched trials",
}


def _repo(tmp_path: Path) -> Repo:
    root = tmp_path / "review"
    init_repository(root, title="T", actor_handle="ethan", actor_name="Ethan")
    return open_repo(root)


def _export(tmp_path: Path) -> Path:
    path = tmp_path / "zotero-hand-searched-trials-2026-03-28.json"
    path.write_text(_CSL, encoding="utf-8")
    return path


def test_the_collection_is_recorded_in_the_import_manifest(tmp_path: Path) -> None:
    repo = _repo(tmp_path)

    import_file(repo, _export(tmp_path), imported_by="ethan", via="website", collection=_COLLECTION)

    (manifest,) = list_import_manifests(repo)
    assert manifest["collection"] == _COLLECTION
    assert manifest["via"] == "website"


def test_an_import_with_no_collection_has_no_collection_field(tmp_path: Path) -> None:
    repo = _repo(tmp_path)

    import_file(repo, _export(tmp_path), imported_by="ethan", via="website")

    (manifest,) = list_import_manifests(repo)
    assert "collection" not in manifest


def test_a_malformed_collection_is_refused_before_anything_is_written(tmp_path: Path) -> None:
    repo = _repo(tmp_path)

    with pytest.raises(SchemaValidationError):
        import_file(
            repo,
            _export(tmp_path),
            imported_by="ethan",
            via="website",
            collection={"manager": "zotero"},
        )

    assert list_import_manifests(repo) == []
