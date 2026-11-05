"""`strata host` commands (openspec:cli#hosted-instance-commands)."""

# ruff: noqa: E501

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from strata import gitio
from strata.cli.main import app
from strata.hosted import accounts
from strata.hosted import members as members_mod
from strata.hosted.instance import Instance
from tests.integration._hosted import push_to_bare, seed_review

runner = CliRunner()
ENV = {
    "STRATA_ADMIN_PASSWORD": "an administrator password",
    "STRATA_PASSWORD": "a reviewer password",
}


def host(
    data: Path, *args: str, code: int = 0, input: str | None = None, json_output: bool = False
) -> str:
    prefix = ["--json"] if json_output else []
    result = runner.invoke(app, [*prefix, "host", *args, "--data", str(data)], env=ENV, input=input)
    assert result.exit_code == code, result.output
    return result.output


def _instance(tmp_path: Path) -> tuple[Path, Path]:
    data = tmp_path / "data"
    host(data, "init", "--public-url", "https://strata.example.test", "--admin", "root")
    bare = push_to_bare(seed_review(tmp_path), tmp_path / "remote.git")
    return data, bare


def test_init_creates_instance_state_and_the_first_administrator(tmp_path: Path) -> None:
    data = tmp_path / "data"
    host(data, "init", "--public-url", "https://strata.example.test", "--admin", "root")
    instance = Instance(data)
    assert instance.is_initialised() and (data / "projects").is_dir()
    user = accounts.get_user(instance.store, "root")
    assert user is not None and user.is_admin and user.has_password
    assert instance.settings.public_url == "https://strata.example.test"
    assert "already initialised" in host(data, "init")
    invited = json.loads(
        host(tmp_path / "other", "init", "--admin", "boss", "--invite", json_output=True)
    )
    assert "/invite/" in invited["invitation"]


def test_a_project_is_added_by_cloning_or_initialising_and_listed(tmp_path: Path) -> None:
    data, bare = _instance(tmp_path)
    assert "cloned from" in host(data, "project", "add", "spacing", "--remote", str(bare))
    host(
        data,
        "project",
        "add",
        "fresh",
        "--title",
        "A new review",
        "--actor",
        "zoe",
        "--actor-name",
        "Zoe",
    )
    listed = json.loads(host(data, "project", "list", json_output=True))
    assert [(p["id"], p["title"], p["remote"]) for p in listed] == [
        ("fresh", "A new review", None),
        ("spacing", "Spacing review", str(bare)),
    ]
    assert (data / "projects" / "spacing" / "strata.toml").is_file()
    host(data, "project", "add", "spacing", "--remote", str(bare), code=2)
    host(data, "project", "add", "bad", code=2)  # no remote and no first actor
    out = host(
        data, "project", "add", "leaky", "--remote", "https://u:secret@example.org/r.git", code=2
    )
    assert "token" in out
    assert "no remote" in host(data, "project", "list")


def test_adding_a_member_writes_instance_state_only(tmp_path: Path) -> None:
    data, bare = _instance(tmp_path)
    host(data, "project", "add", "spacing", "--remote", str(bare))
    host(data, "user", "add", "sam.okonkwo", "--name", "Sam Okonkwo")
    project = data / "projects" / "spacing"
    before = gitio.current_commit(project)
    host(data, "member", "add", "spacing", "sam.okonkwo", "--actor", "sam", "--role", "screener")
    assert gitio.current_commit(project) == before and not gitio.is_dirty(project)
    membership = members_mod.membership(Instance(data), "spacing", "sam.okonkwo")
    assert membership is not None and (membership.actor, membership.role) == ("sam", "screener")
    assert host(data, "member", "list", "spacing").split() == ["sam.okonkwo", "sam", "screener"]


def test_an_unknown_actor_is_a_usage_error_naming_the_handle(tmp_path: Path) -> None:
    data, bare = _instance(tmp_path)
    host(data, "project", "add", "spacing", "--remote", str(bare))
    host(data, "user", "add", "sam.okonkwo")
    out = host(
        data,
        "member",
        "add",
        "spacing",
        "sam.okonkwo",
        "--actor",
        "samuel",
        "--role",
        "screener",
        code=2,
    )
    assert "samuel" in out and "strata.toml" in out
    assert host(
        data, "member", "add", "spacing", "sam.okonkwo", "--actor", "sam", "--role", "boss", code=2
    )


def test_users_are_added_invited_disabled_and_listed(tmp_path: Path) -> None:
    data, _bare = _instance(tmp_path)
    invited = json.loads(host(data, "user", "add", "priya", "--invite", json_output=True))
    assert invited["invitation"].startswith("https://strata.example.test/invite/")
    host(data, "user", "add", "sam")
    instance = Instance(data)
    assert (
        accounts.sign_in(instance.store, "sam", ENV["STRATA_PASSWORD"], client="t").username
        == "sam"
    )
    host(data, "user", "disable", "sam")
    rows = json.loads(host(data, "user", "list", json_output=True))
    assert {r["username"]: r["disabled"] for r in rows} == {
        "priya": False,
        "root": False,
        "sam": True,
    }
    assert "password" not in json.dumps([r for r in rows if r["username"] == "sam"]).replace(
        '"password": true', ""
    )
    host(data, "user", "enable", "sam")
    host(data, "user", "disable", "nobody", code=2)
    log = json.loads(host(data, "signins", json_output=True))
    assert log[0]["username"] == "sam" and log[0]["outcome"] == "success"


def test_tokens_and_secrets_are_shown_once_or_never(tmp_path: Path) -> None:
    data, _bare = _instance(tmp_path)
    host(data, "user", "add", "sam")
    token = json.loads(host(data, "token", "add", "sam", json_output=True))["token"]
    assert accounts.user_for_api_token(Instance(data).store, token) == "sam"
    assert "revoked 1" in host(data, "token", "revoke", "sam")
    host(data, "secret", "set", "spacing-token", input="ghp_value-from-stdin\n")
    listed = host(data, "secret", "list", "spacing-token", "absent")
    assert listed.split() == ["spacing-token", "stored", "absent", "missing"]
    assert Instance(data).secrets.get("spacing-token") == "ghp_value-from-stdin"
    host(data, "secret", "delete", "spacing-token")
    host(data, "secret", "delete", "spacing-token", code=2)


def test_running_needs_an_initialised_instance_and_an_https_url(tmp_path: Path) -> None:
    out = host(tmp_path / "empty", code=2)
    assert "strata host init" in out
    data = tmp_path / "data"
    host(data, "init", "--admin", "root")
    assert "public URL" in host(data, code=2)
    result = runner.invoke(
        app, ["host", "--data", str(data), "--public-url", "http://example.org"], env=ENV
    )
    assert result.exit_code == 2 and "https://" in result.output


def test_a_relative_data_directory_works(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _data, bare = _instance(tmp_path)
    monkeypatch.chdir(tmp_path)
    host(Path("rel"), "init", "--admin", "root")
    host(Path("rel"), "project", "add", "spacing", "--remote", str(bare))
    assert (tmp_path / "rel" / "projects" / "spacing" / "strata.toml").is_file()


def test_an_empty_remote_is_explained_and_leaves_nothing_behind(tmp_path: Path) -> None:
    data, _bare = _instance(tmp_path)
    empty = tmp_path / "empty.git"
    gitio.run(["init", "--bare", str(empty)], cwd=tmp_path)
    out = host(data, "project", "add", "spacing", "--remote", str(empty), code=2)
    assert "holds no strata review" in out
    assert not (data / "projects" / "spacing").exists()
