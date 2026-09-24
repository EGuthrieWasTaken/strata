from pathlib import Path

from strata.core.init import init_repository
from strata.core.repo import open_repo
from strata.core.status import _count_ndjson_lines, _read_criteria_version, compute_status


def _init(tmp_path: Path) -> Path:
    root = tmp_path / "review"
    init_repository(root, title="T", actor_handle="ethan", actor_name="Ethan")
    return root


def test_count_ndjson_lines_missing_file_returns_zero(tmp_path: Path) -> None:
    assert _count_ndjson_lines(tmp_path / "does-not-exist.ndjson") == 0


def test_read_criteria_version_missing_file_returns_zero(tmp_path: Path) -> None:
    repo = open_repo(_init(tmp_path))
    repo.path("protocol", "criteria.yaml").unlink()
    assert _read_criteria_version(repo) == 0


def test_read_criteria_version_empty_file_returns_zero(tmp_path: Path) -> None:
    repo = open_repo(_init(tmp_path))
    repo.path("protocol", "criteria.yaml").write_text("", encoding="utf-8")
    assert _read_criteria_version(repo) == 0


def test_compute_status_on_freshly_initialised_repo(tmp_path: Path) -> None:
    repo = open_repo(_init(tmp_path))
    status = compute_status(repo)
    assert status.title == "T"
    assert status.actor_count == 1
    assert status.record_count == 0
    assert status.criteria_version == 0
    assert status.is_clean is True
