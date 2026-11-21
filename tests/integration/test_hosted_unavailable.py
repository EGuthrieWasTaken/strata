"""A project with a symbolic link in its working copy is refused on its own: the instance and its
other projects start (openspec:hosted-deployment#isolation-between-projects and
#hosted-security-baseline; tasks 4.13 and 4.14)."""

# ruff: noqa: E501

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import pytest

from strata import gitio
from strata.hosted import accounts
from strata.hosted.instance import ProjectUnavailable
from strata.web.hosted import HostedServer
from strata.web.security import parse_public_url
from tests.integration._hosted import PUBLIC_URL, Hosted
from tests.integration.test_cli_host import ENV, _instance, host, runner
from tests.integration.test_hosted_isolation import _mcp, _two_projects

LINK = "protocol/leak.md"


def _link_into(h: Hosted, project: str = "spacing", where: str = LINK) -> Path:
    path = h.instance.project_dir(project) / where
    path.unlink(missing_ok=True)
    os.symlink("/etc/hostname", path)
    return path


def _restart(h: Hosted) -> None:
    """A new process over the same data directory."""
    h.server = HostedServer(
        h.instance, public_url=parse_public_url(PUBLIC_URL), background=False, clock=h.clock
    )
    h.clients.clear()


def _world(tmp_path: Path, caplog: pytest.LogCaptureFixture | None = None) -> Hosted:
    """`spacing` (sam, olive, ethan) with a link in it, and `secret-trial` (zoe), restarted."""
    if caplog is not None:
        caplog.set_level(logging.INFO, logger="strata.hosted")
    h, _ids = _two_projects(tmp_path)
    _link_into(h)
    _restart(h)
    return h


def test_the_instance_starts_and_names_the_project_it_refused_in_the_log(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="strata.hosted")
    h, _ids = _two_projects(tmp_path)
    _link_into(h)

    _restart(h)  # does not raise

    refusal = h.instance.unavailable("spacing")
    assert isinstance(refusal, ProjectUnavailable)
    assert h.instance.unavailable("secret-trial") is None
    for text in (str(refusal), caplog.text):
        assert "spacing" in text and LINK in text  # which project, which link
        assert "symbolic link" in text and "outside the project" in text  # why
        assert f"git -C projects/spacing rm {LINK}" in text and "push" in text  # the fix
        assert "other projects" in text.lower() and "not affected" in text


def test_a_member_is_told_the_project_is_unavailable_and_how_to_fix_it(tmp_path: Path) -> None:
    h = _world(tmp_path)
    sam = h.signed_in("sam.okonkwo")

    for method, path in (
        ("get", "/p/spacing/"),
        ("get", "/p/spacing/records"),
        ("post", "/p/spacing/screen/title-abstract"),
    ):
        response = getattr(sam, method)(path)
        assert response.status_code == 503, path
        text = response.text
        assert "unavailable" in text and LINK in text and "symbolic link" in text
        assert f"git -C projects/spacing rm {LINK}" in text
        assert "Spacing review" not in text  # none of the review's own data
    assert "Spacing review" not in sam.get("/p/spacing/").text


def test_the_dashboard_shows_the_project_as_unavailable_and_names_the_link(tmp_path: Path) -> None:
    h = _world(tmp_path)
    page = h.signed_in("sam.okonkwo").get("/")
    assert page.status_code == 200
    assert "unavailable" in page.text and LINK in page.text


def test_the_instances_other_projects_carry_on(tmp_path: Path) -> None:
    h = _world(tmp_path)
    zoe = h.signed_in("zoe")
    assert zoe.get("/p/secret-trial/").status_code == 200
    assert "unavailable" not in zoe.get("/").text


def test_a_non_member_learns_nothing_about_the_project_or_its_link(tmp_path: Path) -> None:
    h = _world(tmp_path)
    zoe = h.signed_in("zoe")  # a member of secret-trial, not of spacing
    for path in ("/p/spacing/", "/p/spacing/records", "/p/spacing/-/members", "/p/spacing/-/sync"):
        asked = zoe.get(path)
        unknown = zoe.get(path.replace("spacing", "no-such-project"))
        assert asked.status_code == unknown.status_code == 404, path
        assert asked.text == unknown.text, path
        assert (
            LINK not in asked.text
            and "symbolic" not in asked.text
            and "unavailable" not in asked.text
        )
    assert "spacing" not in zoe.get("/").text and LINK not in zoe.get("/").text
    # Nor does the remote MCP endpoint, for a token holder who is not a member.
    token = accounts.create_api_token(
        h.instance.store, "zoe", label="mcp", project="secret-trial", by="test", now=h.clock()
    )
    asked = _mcp(h.client(), "spacing", token, "tools/list")
    unknown = _mcp(h.client(), "no-such-project", token, "tools/list")
    assert asked.status_code == unknown.status_code == 404 and asked.json() == unknown.json()


def test_remote_mcp_for_the_project_says_why_it_is_refused(tmp_path: Path) -> None:
    h = _world(tmp_path)
    token = accounts.create_api_token(
        h.instance.store, "sam.okonkwo", label="mcp", project="spacing", by="test", now=h.clock()
    )
    refused = _mcp(h.client(), "spacing", token, "tools/list")
    assert refused.status_code == 503
    description = refused.json()["error_description"]
    assert (
        LINK in description
        and "symbolic link" in description
        and "git -C projects/spacing rm" in description
    )
    assert token not in refused.text


def test_the_sync_loop_leaves_an_unavailable_project_alone(tmp_path: Path) -> None:
    h = _world(tmp_path)
    head = gitio.current_commit(h.instance.project_dir("spacing"))
    h.server.sync.note_commit("spacing", "ethan")  # something waiting to be pushed
    h.server.sync.note_screening("spacing", "sam", decisions=300)  # and a screening batch due

    assert h.server.sync.run_due() == []
    status = h.server.sync.sync_now("spacing", "ethan")
    h.server.sync.pull_before_read("spacing", "ethan")

    assert status.last_fetch is None and status.last_success is None
    assert gitio.current_commit(h.instance.project_dir("spacing")) == head
    # The other project is still synced (its remote here is a working copy, so a push is refused,
    # but a fetch was tried).
    assert h.server.sync.sync_now("secret-trial", "ethan").last_fetch is not None


def test_a_project_that_still_has_its_link_never_runs_the_repositorys_hooks(tmp_path: Path) -> None:
    h = _world(tmp_path)
    root = h.instance.project_dir("spacing")
    assert gitio.get_config(root, "core.hooksPath") == str(h.instance.hooks_dir)
    assert gitio.get_config(root, "core.symlinks") == "false"


def test_the_project_comes_back_when_the_link_is_gone(tmp_path: Path) -> None:
    h = _world(tmp_path)
    sam = h.signed_in("sam.okonkwo")
    assert sam.get("/p/spacing/").status_code == 503

    (h.instance.project_dir("spacing") / LINK).unlink()

    assert sam.get("/p/spacing/").status_code == 200  # no restart needed
    assert h.instance.unavailable("spacing") is None


def test_every_link_is_named_up_to_a_few_and_the_rest_counted(tmp_path: Path) -> None:
    h, _ids = _two_projects(tmp_path)
    names = [f"protocol/link-{n}.md" for n in range(8)]
    for name in names:
        _link_into(h, where=name)
    refusal = h.instance.check_project("spacing")
    assert refusal is not None and refusal.links == sorted(names)
    text = str(refusal)
    assert all(name in text for name in names[:5]) and "3 more" in text


# ------------------------------------------------------------------- the command line


def test_the_command_starts_the_instance_and_warns_about_the_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import strata.web.hosted as hosted_mod
    from strata.cli.main import app

    data, bare = _instance(tmp_path)
    host(data, "project", "add", "spacing", "--remote", str(bare))
    host(data, "project", "add", "other", "--actor", "ethan", "--actor-name", "Ethan")
    os.symlink("/etc/hostname", data / "projects" / "spacing" / LINK)
    started: list[object] = []
    monkeypatch.setattr(hosted_mod, "run_hosted", lambda server, **kw: started.append(server))

    result = runner.invoke(
        app,
        [
            "host",
            "--data",
            str(data),
            "--public-url",
            "http://localhost:8123",
            "--insecure-local-testing",
        ],
        env=ENV,
    )

    assert result.exit_code == 0 and len(started) == 1
    assert "serving 2 project(s)" in result.output
    assert "spacing" in result.output and LINK in result.output and "unavailable" in result.output
    assert "git -C projects/spacing rm" in result.output


def test_the_project_list_shows_which_project_is_unavailable(tmp_path: Path) -> None:
    data, bare = _instance(tmp_path)
    host(data, "project", "add", "spacing", "--remote", str(bare))
    os.symlink("/etc/hostname", data / "projects" / "spacing" / LINK)

    rows = json.loads(host(data, "project", "list", json_output=True))

    assert rows[0]["id"] == "spacing" and LINK in rows[0]["unavailable"]
    assert "unavailable" in host(data, "project", "list") and LINK in host(data, "project", "list")
