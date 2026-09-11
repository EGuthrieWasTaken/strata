from pathlib import Path

import pytest

from strata.core.init import init_repository
from strata.core.manifest import get_value, load_manifest_doc, set_value, write_manifest


def _init(tmp_path: Path) -> Path:
    root = tmp_path / "review"
    init_repository(root, title="T", actor_handle="ethan", actor_name="Ethan")
    return root


def test_get_value_raises_key_error_for_unknown_dotted_key(tmp_path: Path) -> None:
    doc = load_manifest_doc(_init(tmp_path))
    with pytest.raises(KeyError):
        get_value(doc, "nonexistent.key")


def test_get_value_returns_nested_table_unwrapped(tmp_path: Path) -> None:
    doc = load_manifest_doc(_init(tmp_path))
    project = get_value(doc, "project")
    assert isinstance(project, dict)
    assert project["title"] == "T"


def test_set_value_creates_missing_intermediate_table(tmp_path: Path) -> None:
    root = _init(tmp_path)
    doc = load_manifest_doc(root)
    set_value(doc, "custom.newkey", "newvalue")
    write_manifest(root, doc)
    reread = load_manifest_doc(root)
    assert get_value(reread, "custom.newkey") == "newvalue"
