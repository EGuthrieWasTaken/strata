from pathlib import Path

import pytest

from strata.core.actor import ActorError, add_actor, deactivate_actor, list_actors
from strata.core.init import init_repository
from strata.core.repo import open_repo


def _init(tmp_path: Path) -> Path:
    root = tmp_path / "review"
    init_repository(root, title="T", actor_handle="ethan", actor_name="Ethan")
    return root


def test_add_actor_rejects_invalid_handle(tmp_path: Path) -> None:
    repo = open_repo(_init(tmp_path))
    with pytest.raises(ActorError, match="invalid actor handle"):
        add_actor(repo, handle="Not Valid!", name="X")


def test_add_actor_rejects_invalid_role(tmp_path: Path) -> None:
    repo = open_repo(_init(tmp_path))
    with pytest.raises(ActorError, match="invalid role"):
        add_actor(repo, handle="sam", name="Sam", role="wizard")


def test_add_actor_with_email_is_persisted(tmp_path: Path) -> None:
    repo = open_repo(_init(tmp_path))
    add_actor(repo, handle="sam", name="Sam", email="sam@example.edu", role="screener")
    actors = list_actors(open_repo(repo.root))
    sam = next(a for a in actors if a["handle"] == "sam")
    assert sam["email"] == "sam@example.edu"


def test_deactivate_unknown_actor_raises(tmp_path: Path) -> None:
    repo = open_repo(_init(tmp_path))
    with pytest.raises(ActorError, match="not found"):
        deactivate_actor(repo, "nobody")
