from pathlib import Path

from strata import gitio
from strata.core.init import init_repository


def test_init_repository_adds_remote_when_given(tmp_path: Path) -> None:
    root = tmp_path / "review"
    init_repository(
        root,
        title="T",
        actor_handle="ethan",
        actor_name="Ethan",
        remote="https://example.invalid/review.git",
    )
    assert gitio.get_config(root, "remote.origin.url") == "https://example.invalid/review.git"


def test_a_new_review_ignores_its_scratch_files(tmp_path: Path) -> None:
    root = tmp_path / "review"
    init_repository(root, title="Scratch", actor_handle="ethan", actor_name="Ethan")
    (root / ".strata" / "tmp" / "uploads").mkdir(parents=True)
    (root / ".strata" / "tmp" / "uploads" / "export.ris").write_text("x", encoding="utf-8")
    (root / ".strata" / "lock").write_text("123\n", encoding="utf-8")

    assert not gitio.is_dirty(root)
