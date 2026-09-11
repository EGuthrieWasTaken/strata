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
