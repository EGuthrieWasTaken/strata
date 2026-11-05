"""Fixtures for the hosted-instance tests (openspec:hosted-deployment): an instance, a review
pushed to a bare remote and added to it as a project, accounts mapped to the review's actors, and
browser-like clients signed in as them."""

# ruff: noqa: E501

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from typer.testing import CliRunner

from strata import gitio
from strata.cli.main import app as cli_app
from strata.core.actor import add_actor
from strata.core.init import init_repository
from strata.core.repo import Repo, open_repo
from strata.hosted import accounts
from strata.hosted import members as members_mod
from strata.hosted.instance import Instance
from strata.protocol import criteria as criteria_mod
from strata.web.hosted import HostedServer, create_hosted_app
from strata.web.security import parse_public_url
from tests.unit._m5 import import_into, search

PUBLIC_URL = "https://strata.example.test"
PASSWORD = "correct horse battery staple"

#: user name -> (actor, role)
USERS = {
    "ethan.g": ("ethan", "lead"),
    "sam.okonkwo": ("sam", "screener"),
    "olive": ("olive", "observer"),
}

_CSRF = re.compile(r'name="csrf_token" value="([^"]+)"')
runner = CliRunner()


class FakeClock:
    def __init__(self, start: float = 1_800_000_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def seed_review(tmp_path: Path, name: str = "seed", *, title: str = "Spacing review", records: int = 6) -> Repo:
    """A review with a lead, two screeners and an observer, criteria and imported records."""
    root = tmp_path / name
    init_repository(root, title=title, actor_handle="ethan", actor_name="Ethan Guthrie",
                    actor_email="ethan@example.org")  # fmt: skip
    repo = open_repo(root)
    add_actor(repo, handle="sam", name="Sam Okonkwo", email="sam@example.org", role="screener")
    add_actor(open_repo(root), handle="priya", name="Priya Raman", email="priya@example.org", role="screener")
    add_actor(open_repo(root), handle="olive", name="Olive Observer", role="observer")
    repo = open_repo(root)
    for kind, label in (("inclusion", "Human participants"), ("exclusion", "Wrong population")):
        criteria_mod.add_criterion(
            repo, kind=kind, label=label, definition=label + ".",  # type: ignore[arg-type]
            applies_at=["title-abstract", "full-text"], actor="ethan", rationale="Protocol.",
        )  # fmt: skip
    import_into(repo, tmp_path, f"{name}-export.json", list(range(1, records + 1)), search_id=search(repo, "MEDLINE"))
    gitio.add_all(repo.root)
    gitio.commit(repo.root, "seed: the shared review\n\nStrata-Op: test\nStrata-Actor: ethan\n")
    return open_repo(root)


def push_to_bare(repo: Repo, bare: Path) -> Path:
    gitio.run(["init", "--bare", "--initial-branch=main", str(bare)], cwd=bare.parent)
    gitio.run(["remote", "add", "origin", str(bare)], cwd=repo.root)
    gitio.run(["push", "-u", "origin", "HEAD:main"], cwd=repo.root)
    return bare


def local_clone(bare: Path, dest: Path) -> Repo:
    """A collaborator's own clone, set up as `strata doctor --fix` leaves one."""
    gitio.clone(str(bare), dest)
    gitio.run(["checkout", "-B", "main", "origin/main"], cwd=dest)
    result = runner.invoke(cli_app, ["-C", str(dest), "doctor", "--fix"])
    assert result.exit_code == 0, result.output
    return open_repo(dest)


@dataclass
class Hosted:
    instance: Instance
    server: HostedServer
    clock: FakeClock
    bare: Path
    project: str = "spacing"
    clients: dict[str, TestClient] = field(default_factory=dict)

    @property
    def repo(self) -> Repo:
        return self.instance.open_project(self.project)

    def client(self, base_url: str = PUBLIC_URL) -> TestClient:
        return TestClient(create_hosted_app(self.server), base_url=base_url, follow_redirects=False)

    def signed_in(self, username: str) -> TestClient:
        if username not in self.clients:
            self.clients[username] = sign_in(self.client(), username)
        return self.clients[username]


def make_instance(tmp_path: Path, *, clock: FakeClock | None = None, environ: dict[str, str] | None = None) -> Instance:
    instance = Instance(tmp_path / "data", environ=environ if environ is not None else {})
    instance.initialise(public_url=PUBLIC_URL)
    return instance


def hosted(tmp_path: Path, *, records: int = 6, users: dict[str, tuple[str, str]] | None = None) -> Hosted:
    """An instance serving one project, `spacing`, cloned from a bare remote, with accounts for
    `USERS` (and any others given)."""
    clock = FakeClock()
    seed = seed_review(tmp_path, records=records)
    bare = push_to_bare(seed, tmp_path / "remote.git")
    instance = make_instance(tmp_path)
    instance.add_project("spacing", remote=str(bare))
    for username, (actor, role) in (users or USERS).items():
        accounts.add_user(instance.store, username, display_name=username.title(), password=PASSWORD)
        members_mod.add_member(instance, "spacing", username, actor=actor, role=role)
    server = HostedServer(instance, public_url=parse_public_url(PUBLIC_URL), background=False, clock=clock)
    return Hosted(instance=instance, server=server, clock=clock, bare=bare)


def csrf_from(html: str) -> str:
    match = _CSRF.search(html)
    assert match, "no CSRF field on the page"
    return match.group(1)


def sign_in(client: TestClient, username: str, password: str = PASSWORD) -> TestClient:
    page = client.get("/signin")
    assert page.status_code == 200, page.text
    response = client.post(
        "/signin",
        data={"csrf_token": csrf_from(page.text), "username": username, "password": password, "next": "/"},
    )
    assert response.status_code == 303, response.text
    return client


def session_csrf(client: TestClient, project: str = "spacing") -> str:
    page = client.get(f"/p/{project}/")
    assert page.status_code == 200, page.text
    return csrf_from(page.text)


def post(client: TestClient, path: str, data: dict[str, Any], *, project: str = "spacing") -> Any:
    return client.post(f"/p/{project}{path}", data={"csrf_token": session_csrf(client, project), **data})


def event_lines(repo: Repo) -> dict[str, list[str]]:
    """Every event file's lines, by path: what must be identical everywhere after a sync."""
    found = {}
    for path in sorted(repo.path("events").rglob("*.ndjson")):
        found[path.relative_to(repo.root).as_posix()] = sorted(path.read_text(encoding="utf-8").splitlines())
    return found
