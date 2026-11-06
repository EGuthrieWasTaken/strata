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


def test_a_person_cannot_be_mapped_to_an_ai_agents_handle(tmp_path: Path) -> None:
    import tomlkit

    from strata.core.manifest import load_manifest_doc, write_manifest

    data, bare = _instance(tmp_path)
    host(data, "project", "add", "spacing", "--remote", str(bare))
    project = data / "projects" / "spacing"
    doc = load_manifest_doc(project)
    agent = tomlkit.table()
    for key, value in (
        ("handle", "claude"),
        ("name", "Claude"),
        ("role", "screener"),
        ("kind", "agent"),
        ("model", "claude-opus"),
    ):
        agent.add(key, value)
    doc["actors"].append(agent)
    write_manifest(project, doc)
    host(data, "user", "add", "sam")
    out = host(
        data, "member", "add", "spacing", "sam", "--actor", "claude", "--role", "screener", code=2
    )
    assert "AI agent" in out


def _bare_host(
    data: Path, *args: str, code: int = 0, input: str | None = None, json_output: bool = False
) -> str:
    """`host` with no passwords in the environment, for the prompts and pipes."""
    prefix = ["--json"] if json_output else []
    result = runner.invoke(
        app,
        [*prefix, "host", *args, "--data", str(data)],
        env={"STRATA_PASSWORD": "", "STRATA_ADMIN_PASSWORD": ""},
        input=input,
    )
    assert result.exit_code == code, result.output
    return result.output


def test_a_password_can_be_piped_in_but_not_left_out(tmp_path: Path) -> None:
    data, _bare = _instance(tmp_path)
    _bare_host(data, "user", "add", "sam", input="a piped-in password\n")
    assert (
        accounts.sign_in(Instance(data).store, "sam", "a piped-in password", client="t").username
        == "sam"
    )
    out = _bare_host(data, "user", "add", "priya", input="\n", code=2)
    assert "no password" in out and "--invite" in out
    assert accounts.get_user(Instance(data).store, "priya") is None


def test_running_starts_the_server_with_what_was_asked(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import strata.web.hosted as hosted_mod

    data = tmp_path / "data"
    host(data, "init", "--admin", "root")
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        hosted_mod, "run_hosted", lambda server, **kw: calls.append({"server": server, **kw})
    )
    out = runner.invoke(
        app,
        [
            "host",
            "--data",
            str(data),
            "--public-url",
            "http://localhost:8123",
            "--insecure-local-testing",
            "--bind",
            "0.0.0.0",
            "--port",
            "8123",
            "--trusted-proxy",
            "10.0.0.2",
        ],
        env=ENV,
    ).output
    assert (
        "sessions are issued over plain HTTP" in out
        and "serving 0 project(s) at http://localhost:8123" in out
    )
    assert len(calls) == 1 and calls[0]["bind"] == "0.0.0.0" and calls[0]["port"] == 8123
    assert calls[0]["trusted_proxies"] == "10.0.0.2"
    assert calls[0]["server"].allow_plain_http  # type: ignore[attr-defined]


def test_init_refuses_a_bad_public_url_or_administrator_and_prints_an_invitation(
    tmp_path: Path,
) -> None:
    assert "needs a scheme" in host(
        tmp_path / "a", "init", "--public-url", "strata.example.org", code=2
    )
    assert "invalid user name" in host(tmp_path / "b", "init", "--admin", "Not Valid", code=2)
    assert "invitation (valid for 7 days): https://<public-url>/invite/" in host(
        tmp_path / "c", "init", "--invite"
    )


def test_project_commands_report_in_both_forms(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    data, bare = _instance(tmp_path)
    assert "no projects yet" in host(data, "project", "list")
    assert "KIND:SECRET" in host(
        data, "project", "add", "spacing", "--remote", str(bare), "--credential", "ssh-key", code=2
    )
    assert "not available" in host(
        data,
        "project",
        "add",
        "spacing",
        "--remote",
        str(bare),
        "--credential",
        "token:absent",
        code=2,
    )
    added = json.loads(
        host(data, "project", "add", "spacing", "--remote", str(bare), json_output=True)
    )
    assert added == {"id": "spacing", "title": "Spacing review", "remote": str(bare)}

    def broken(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("the clone has an unreadable strata.toml")

    monkeypatch.setattr(Instance, "add_project", broken)
    out = host(data, "project", "add", "other", "--remote", str(bare), code=1)
    assert "could not add other: the clone has an unreadable strata.toml" in out


def test_user_commands_report_in_both_forms_and_refuse_unknowns(tmp_path: Path) -> None:
    data, _bare = _instance(tmp_path)
    assert "invitation (valid for 7 days): https://strata.example.test/invite/" in host(
        data, "user", "add", "priya", "--invite"
    )
    assert "already an account" in host(data, "user", "add", "priya", code=2)
    assert "invitation for priya" in host(data, "user", "invite", "priya")
    assert (
        json.loads(host(data, "user", "invite", "priya", json_output=True))["username"] == "priya"
    )
    assert "no account called 'ghost'" in host(data, "user", "invite", "ghost", code=2)
    assert "no account called 'ghost'" in host(data, "user", "enable", "ghost", code=2)
    host(data, "user", "add", "boss", "--admin")
    host(data, "user", "disable", "priya")
    listed = host(data, "user", "list").splitlines()
    assert [line.split()[0] for line in listed] == ["boss", "priya", "root"]
    assert "admin" in listed[0] and "disabled" in listed[1]
    accounts.sign_in(Instance(data).store, "boss", ENV["STRATA_PASSWORD"], client="10.1.2.3")
    assert "boss" in host(data, "signins") and "10.1.2.3" in host(data, "signins")


def test_member_token_and_secret_commands_report_in_both_forms(tmp_path: Path) -> None:
    from strata.core.actor import add_actor, deactivate_actor
    from strata.core.repo import open_repo

    data, bare = _instance(tmp_path)
    host(data, "project", "add", "spacing", "--remote", str(bare))
    host(data, "user", "add", "sam")
    added = json.loads(
        host(
            data,
            "member",
            "add",
            "spacing",
            "sam",
            "--actor",
            "sam",
            "--role",
            "screener",
            json_output=True,
        )
    )
    assert added == {"project": "spacing", "username": "sam", "actor": "sam", "role": "screener"}
    assert json.loads(host(data, "member", "list", "spacing", json_output=True)) == [added]
    assert "removed sam from spacing" in host(data, "member", "remove", "spacing", "sam")
    assert "not a member" in host(data, "member", "remove", "spacing", "sam", code=2)
    assert "no project called 'nope'" in host(
        data, "member", "add", "nope", "sam", "--actor", "sam", "--role", "screener", code=2
    )
    assert "no account called 'ghost'" in host(
        data, "member", "add", "spacing", "ghost", "--actor", "sam", "--role", "screener", code=2
    )
    project = open_repo(data / "projects" / "spacing")
    add_actor(project, handle="gone", name="Gone", role="screener")
    deactivate_actor(open_repo(project.root), "gone")
    assert "deactivated" in host(
        data, "member", "add", "spacing", "sam", "--actor", "gone", "--role", "screener", code=2
    )

    printed = host(data, "token", "add", "sam", "--label", "laptop").splitlines()
    assert "it is not shown again" in printed[0] and printed[1].startswith("strata_")
    assert "no account called 'ghost'" in host(data, "token", "add", "ghost", code=2)

    import os

    os.environ["SPACING_TOKEN_FOR_TEST"] = "ghp_from_the_environment"
    try:
        host(data, "secret", "set", "spacing-token", "--from-env", "SPACING_TOKEN_FOR_TEST")
    finally:
        del os.environ["SPACING_TOKEN_FOR_TEST"]
    assert Instance(data).secrets.get("spacing-token") == "ghp_from_the_environment"
    assert json.loads(host(data, "secret", "list", json_output=True)) == [
        {"name": "spacing-token", "source": "stored"}
    ]
    assert "invalid secret name" in host(
        data, "secret", "set", "../escape", input="value\n", code=2
    )
