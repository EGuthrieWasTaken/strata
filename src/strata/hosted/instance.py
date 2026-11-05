"""The hosted instance's data directory, settings and projects.

Implements openspec:hosted-deployment#projects-and-instance-state and
openspec:hosted-deployment#git-is-always-the-backend. The layout under the data directory (`/data`
in the container) is:

```
<data>/
  projects/<project-id>/      one ordinary review repository (a git working copy) per project
  instance/
    instance.toml             the operator's settings (public URL, committer identity, sync, OIDC)
    instance.db               accounts, memberships, sessions, sign-in log, sync status, secrets
    instance.key              the key stored secrets are encrypted with (unless supplied)
    tmp/                      short-lived files git needs (a deploy key for one command)
```

A project is either cloned from its remote or initialised fresh. Its remote URL is kept in
instance state, never with a credential in it: a URL carrying a password or token is refused,
and the credential is named instead (`strata.hosted.secrets`).
"""

from __future__ import annotations

import contextlib
import os
import re
import time
import tomllib
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import tomlkit

from strata import gitio
from strata.core import doctor as doctor_mod
from strata.core.init import init_repository
from strata.core.repo import Repo, open_repo
from strata.hosted.secrets import SecretStore, git_credential_env
from strata.hosted.store import Store

PROJECT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
DEFAULT_DATA_DIR = Path("/data")
DATA_ENV = "STRATA_DATA"

DEFAULT_SYNC_INTERVAL = 30.0
DEFAULT_SESSION_IDLE_MINUTES = 120
DEFAULT_SESSION_HOURS = 12


class InstanceError(ValueError):
    """Something about the instance or a project is not as the command needs it."""


@dataclass(frozen=True)
class OidcProvider:
    """One configured sign-in provider (`[[oidc]]` in `instance.toml`)."""

    id: str
    label: str
    kind: str  # "oidc" (discovery from `issuer`) or "github"
    client_id: str
    client_secret: str  # the *name* of the secret holding the client secret
    issuer: str | None = None
    scopes: str = "openid email profile"


@dataclass(frozen=True)
class Settings:
    """`instance.toml`, with defaults for what it leaves out."""

    public_url: str | None = None
    committer_name: str = "strata instance"
    committer_email: str = "strata@instance.invalid"
    sync_interval: float = DEFAULT_SYNC_INTERVAL
    session_idle_minutes: int = DEFAULT_SESSION_IDLE_MINUTES
    session_hours: int = DEFAULT_SESSION_HOURS
    max_upload_mb: int = 50
    oidc: tuple[OidcProvider, ...] = field(default_factory=tuple)

    @property
    def committer(self) -> tuple[str, str]:
        return self.committer_name, self.committer_email


@dataclass(frozen=True)
class Project:
    id: str
    title: str
    remote: str | None
    credential_kind: str | None
    credential_secret: str | None
    credential_username: str | None
    created: float


def _settings_from(doc: dict[str, Any]) -> Settings:
    committer = doc.get("committer", {})
    sync = doc.get("sync", {})
    sessions = doc.get("sessions", {})
    providers = []
    for entry in doc.get("oidc", []):
        try:
            providers.append(
                OidcProvider(
                    id=str(entry["id"]),
                    label=str(entry.get("label") or entry["id"]),
                    kind=str(entry.get("kind", "oidc")),
                    client_id=str(entry["client_id"]),
                    client_secret=str(entry["client_secret"]),
                    issuer=str(entry["issuer"]) if entry.get("issuer") else None,
                    scopes=str(entry.get("scopes", "openid email profile")),
                )
            )
        except KeyError as missing:
            raise InstanceError(f"an [[oidc]] provider in instance.toml has no {missing}") from None
    return Settings(
        public_url=doc.get("public_url"),
        committer_name=str(committer.get("name", Settings.committer_name)),
        committer_email=str(committer.get("email", Settings.committer_email)),
        sync_interval=float(sync.get("interval_seconds", DEFAULT_SYNC_INTERVAL)),
        session_idle_minutes=int(sessions.get("idle_minutes", DEFAULT_SESSION_IDLE_MINUTES)),
        session_hours=int(sessions.get("hours", DEFAULT_SESSION_HOURS)),
        max_upload_mb=int(doc.get("max_upload_mb", 50)),
        oidc=tuple(providers),
    )


def default_data_dir() -> Path:
    configured = os.environ.get(DATA_ENV)
    return Path(configured) if configured else DEFAULT_DATA_DIR


def check_remote_url(url: str) -> str:
    """A remote URL fit to store: no password or token embedded in it."""
    text = url.strip()
    if not text:
        raise InstanceError("the remote URL is empty")
    parts = urlsplit(text)
    if parts.scheme in ("http", "https") and (parts.password or parts.username):
        raise InstanceError(
            "the remote URL has a user name or token in it, which would be stored in plain text; "
            "give the URL without it and name the credential with --credential"
        )
    if text.startswith("-"):
        raise InstanceError(f"{url!r} is not a remote URL")
    return text


class Instance:
    """One hosted instance, rooted at its data directory."""

    def __init__(self, data_dir: Path, *, environ: dict[str, str] | None = None) -> None:
        self.data_dir = data_dir
        self.projects_dir = data_dir / "projects"
        self.state_dir = data_dir / "instance"
        self.tmp_dir = self.state_dir / "tmp"
        self.settings_path = self.state_dir / "instance.toml"
        self.store = Store(self.state_dir / "instance.db")
        self.secrets = SecretStore(self.store, self.state_dir / "instance.key", environ=environ)
        self._settings: Settings | None = None

    # -- set-up ----------------------------------------------------------------------------

    def is_initialised(self) -> bool:
        return self.store.exists()

    def require_initialised(self) -> None:
        if not self.is_initialised():
            raise InstanceError(
                f"{self.data_dir} holds no strata instance; run `strata host init --data "
                f"{self.data_dir}` first"
            )

    def initialise(self, *, public_url: str | None = None) -> None:
        """Create the instance's state (idempotent: an existing instance keeps what it has)."""
        for directory in (self.projects_dir, self.state_dir):
            directory.mkdir(parents=True, exist_ok=True)
        self.state_dir.chmod(0o700)
        self.store.create()
        self.secrets.ensure_key()
        if not self.settings_path.exists():
            doc = tomlkit.document()
            doc.add(tomlkit.comment("Settings for this strata instance (strata host)."))
            if public_url:
                doc.add("public_url", public_url)
            committer = tomlkit.table()
            committer.add("name", Settings.committer_name)
            committer.add("email", Settings.committer_email)
            doc.add("committer", committer)
            sync = tomlkit.table()
            sync.add("interval_seconds", int(DEFAULT_SYNC_INTERVAL))
            doc.add("sync", sync)
            self.settings_path.write_text(tomlkit.dumps(doc), encoding="utf-8")

    @property
    def settings(self) -> Settings:
        if self._settings is None:
            doc: dict[str, Any] = {}
            if self.settings_path.exists():
                try:
                    doc = tomllib.loads(self.settings_path.read_text(encoding="utf-8"))
                except tomllib.TOMLDecodeError as exc:
                    raise InstanceError(f"{self.settings_path} is not valid TOML: {exc}") from None
            self._settings = _settings_from(doc)
        return self._settings

    # -- projects --------------------------------------------------------------------------

    def project_dir(self, project_id: str) -> Path:
        if not PROJECT_ID_RE.match(project_id):
            raise InstanceError(
                f"invalid project id {project_id!r} (must match {PROJECT_ID_RE.pattern})"
            )
        return self.projects_dir / project_id

    def get_project(self, project_id: str) -> Project | None:
        row = self.store.one("SELECT * FROM projects WHERE id = ?", (project_id,))
        return _project(row) if row is not None else None

    def list_projects(self) -> list[Project]:
        return [_project(row) for row in self.store.all("SELECT * FROM projects ORDER BY id")]

    def open_project(self, project_id: str) -> Repo:
        return open_repo(self.project_dir(project_id))

    @contextlib.contextmanager
    def git_env(self, project: Project) -> Iterator[None]:
        """Run the git commands inside this block with `project`'s remote credential."""
        with (
            git_credential_env(
                self.secrets,
                kind=project.credential_kind,
                secret=project.credential_secret,
                username=project.credential_username,
                tmp_dir=self.tmp_dir,
            ) as env,
            gitio.environment(env),
        ):
            yield

    def add_project(
        self,
        project_id: str,
        *,
        remote: str | None = None,
        credential_kind: str | None = None,
        credential_secret: str | None = None,
        credential_username: str | None = None,
        title: str | None = None,
        actor_handle: str | None = None,
        actor_name: str | None = None,
        actor_email: str | None = None,
        now: float | None = None,
    ) -> Project:
        """Add a project: clone `remote`, or initialise a new review when there is none."""
        self.require_initialised()
        dest = self.project_dir(project_id)
        if self.get_project(project_id) is not None or dest.exists():
            raise InstanceError(f"there is already a project called {project_id!r}")
        if (credential_kind is None) != (credential_secret is None):
            raise InstanceError("a credential needs both its kind and the name of its secret")
        if credential_kind not in (None, "ssh-key", "token"):
            raise InstanceError(
                f"unknown credential kind {credential_kind!r}; use ssh-key or token"
            )
        if credential_kind is not None and remote is None:
            raise InstanceError("a credential is only used with a remote")
        stored_remote = check_remote_url(remote) if remote is not None else None
        pending = Project(
            id=project_id,
            title=title or project_id,
            remote=stored_remote,
            credential_kind=credential_kind,
            credential_secret=credential_secret,
            credential_username=credential_username,
            created=now if now is not None else time.time(),
        )
        try:
            if stored_remote is not None:
                with self.git_env(pending):
                    gitio.clone(stored_remote, dest)
                repo = open_repo(dest)
                # The merge drivers and hooks a clone does not carry (`strata doctor --fix`).
                doctor_mod.run_doctor(repo, fix=True)
                resolved_title = title or str(repo.config.get("project", {}).get("title") or "")
            else:
                if not (actor_handle and actor_name):
                    raise InstanceError(
                        "a new project needs its first actor: give --actor and --actor-name (or "
                        "--remote to clone an existing review)"
                    )
                init_repository(
                    dest,
                    title=title or project_id,
                    actor_handle=actor_handle,
                    actor_name=actor_name,
                    actor_email=actor_email,
                )
                resolved_title = title or project_id
        except gitio.GitError as exc:
            _remove_tree(dest)
            raise InstanceError(f"could not clone {stored_remote}: {exc.stderr.strip()}") from None
        except Exception:
            _remove_tree(dest)
            raise
        project = Project(**{**pending.__dict__, "title": resolved_title or project_id})
        self.store.execute(
            "INSERT INTO projects (id, title, remote, credential_kind, credential_secret, "
            "credential_username, created) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                project.id,
                project.title,
                project.remote,
                project.credential_kind,
                project.credential_secret,
                project.credential_username,
                project.created,
            ),
        )
        return project


def _project(row: Any) -> Project:
    return Project(
        id=row["id"],
        title=row["title"],
        remote=row["remote"],
        credential_kind=row["credential_kind"],
        credential_secret=row["credential_secret"],
        credential_username=row["credential_username"],
        created=row["created"],
    )


def _remove_tree(path: Path) -> None:
    import shutil

    if path.exists():
        shutil.rmtree(path, ignore_errors=True)
