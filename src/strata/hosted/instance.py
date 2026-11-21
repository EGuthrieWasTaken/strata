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
    hooks/                    the git hooks every project runs (see below)
```

**Hooks.** A review repository carries its git hooks in `.strata/hooks/`, and a local clone runs
them from there. On an instance that would let anyone who can push to a project's remote make the
server run any program they liked at its next commit. So the instance points every project's
`core.hooksPath` at its own copy of the standard hooks, written from `strata.core.hooks`, and never
runs a hook from a repository's files.

A project is either cloned from its remote or initialised fresh. Its remote URL is kept in
instance state, never with a credential in it: a URL carrying a password or token is refused,
and the credential is named instead (`strata.hosted.secrets`).
"""

from __future__ import annotations

import contextlib
import logging
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
from strata.core.hooks import HOOK_SCRIPTS
from strata.core.init import init_repository
from strata.core.repo import Repo, RepoNotFoundError, open_repo
from strata.hosted import hostkeys
from strata.hosted.errors import InstanceError as InstanceError  # re-exported
from strata.hosted.secrets import SecretStore, git_credential_env
from strata.hosted.store import Store

_LOG = logging.getLogger("strata.hosted")

PROJECT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
DEFAULT_DATA_DIR = Path("/data")
DATA_ENV = "STRATA_DATA"

DEFAULT_SYNC_INTERVAL = 30.0
DEFAULT_SESSION_IDLE_MINUTES = 120
DEFAULT_SESSION_HOURS = 12


#: How many links a refusal names before it counts the rest.
_LINKS_NAMED = 5


def _unavailable_message(project_id: str, links: list[str]) -> str:
    """Why a project is not served, in plain words: which project, which link, why that matters,
    and how to remove it and push (openspec:hosted-deployment#hosted-security-baseline)."""
    shown = links[:_LINKS_NAMED]
    more = len(links) - len(shown)
    named = ", ".join(shown) + (f" and {more} more" if more else "")
    one = len(links) == 1
    removals = "; ".join(f"git -C projects/{project_id} rm {link}" for link in shown)
    return (
        f"The project {project_id!r} is unavailable: its working copy contains "
        f"{'a symbolic link' if one else f'{len(links)} symbolic links'} ({named}), and an "
        "instance never serves a project that has one, because the screens could follow the link "
        "to files outside the project, such as the instance's own state or another project. "
        "Other projects on this instance are not affected. To fix it, remove "
        f"{'the link' if one else 'the links'} from the project's working copy and push the "
        f"removal: in the instance's data directory run `{removals}` (`rm` instead of `git rm` "
        "if git does not track it), commit, and `git push` from there. The project returns when "
        "its page is next opened."
    )


def _say_tokens_were_expired(count: int) -> None:
    """Tell the operator, in the log, that bringing the instance's state up to date ended the API
    tokens made before they named a project and expired, and what to do about it. Said once: the
    upgrade finds them only the first time it runs
    (openspec:hosted-deployment#api-tokens-name-one-project-and-expire)."""
    if count:
        _LOG.warning(
            "Upgrading the instance's state expired %d %s made before tokens named a project and "
            "expired, so that none of them reads every project its owner is in. Whoever holds one "
            "is told it expired: make a replacement with `strata host token add USER --project "
            "PROJECT` (`strata host audit` lists whose).",
            count,
            "API token" if count == 1 else "API tokens",
        )


class ProjectUnavailable(InstanceError):
    """A project the instance will not serve, and why; the message is safe to show a member."""

    def __init__(self, project_id: str, links: list[str]) -> None:
        self.project_id = project_id
        self.links = links
        super().__init__(_unavailable_message(project_id, links))


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
    #: The SSH host key(s) the remote is pinned to, as `known_hosts` lines; `None` is trust on
    #: first use (`strata.hosted.hostkeys`).
    host_key: str | None = None


@dataclass(frozen=True)
class HostKeyReport:
    """Which SSH host key(s) a project's remote is trusted with, and how that came about."""

    host: str
    pinned: bool
    keys: list[hostkeys.HostKey]


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


#: Set in every project's git configuration (`Instance.secure_project`).
SECURE_GIT_CONFIG = {"core.symlinks": "false"}


def _symlinks_in(root: Path) -> list[Path]:
    """Every symbolic link in a working tree outside `.git`, sorted."""
    found: list[Path] = []
    for directory, dirnames, filenames in os.walk(root):
        if ".git" in dirnames:
            dirnames.remove(".git")
        for name in [*dirnames, *filenames]:
            path = Path(directory) / name
            if path.is_symlink():
                found.append(path)
    return sorted(found)


def check_remote_url(url: str) -> str:
    """A remote URL fit to store: no password or token embedded in it."""
    text = url.strip()
    if not text:
        raise InstanceError("the remote URL is empty")
    parts = urlsplit(text)
    if (parts.scheme in ("http", "https") and parts.username) or parts.password:
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
        # Absolute, because git runs in other directories (a clone runs in `projects/`).
        self.data_dir = data_dir.absolute()
        self.projects_dir = self.data_dir / "projects"
        self.state_dir = self.data_dir / "instance"
        self.tmp_dir = self.state_dir / "tmp"
        self.hooks_dir = self.state_dir / "hooks"
        self.settings_path = self.state_dir / "instance.toml"
        self.store = Store(self.state_dir / "instance.db")
        self.secrets = SecretStore(self.store, self.state_dir / "instance.key", environ=environ)
        self._settings: Settings | None = None
        self._unavailable: dict[str, ProjectUnavailable] = {}

    # -- set-up ----------------------------------------------------------------------------

    def is_initialised(self) -> bool:
        return self.store.exists()

    def require_initialised(self) -> None:
        if not self.is_initialised():
            raise InstanceError(
                f"{self.data_dir} holds no strata instance; run `strata host init --data "
                f"{self.data_dir}` first"
            )
        if self.store.needs_upgrade():
            # State made by an earlier version: bring it up to date, keeping what it holds.
            _say_tokens_were_expired(self.store.upgrade())

    def initialise(self, *, public_url: str | None = None) -> None:
        """Create the instance's state (idempotent: an existing instance keeps what it has)."""
        for directory in (self.projects_dir, self.state_dir):
            directory.mkdir(parents=True, exist_ok=True)
        self.state_dir.chmod(0o700)
        _say_tokens_were_expired(self.store.create())
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

    def secure_project(self, project_id: str) -> None:
        """Make a project's git run the instance's own hooks, never the repository's, and check
        out no symbolic links; refuse (`ProjectUnavailable`) a project that already has one.

        A symbolic link committed to a project's remote would otherwise be checked out as one, and
        the screens that read and write a review's files would follow it out of the project: to
        the instance's own state, its key, its hooks or another project. With `core.symlinks`
        off, git writes such a link as a small file holding the link's text.

        The hardening is applied first and the refusal comes after, so even a project that is
        refused never runs a hook from its repository.
        """
        root = self.project_dir(project_id)
        for key, value in SECURE_GIT_CONFIG.items():
            if gitio.get_config(root, key) != value:
                gitio.set_config(root, key, value)
        self.hooks_dir.mkdir(parents=True, exist_ok=True)
        for name, script in HOOK_SCRIPTS.items():
            path = self.hooks_dir / name
            if not path.exists() or path.read_text(encoding="utf-8") != script:
                path.write_text(script, encoding="utf-8")
            path.chmod(0o755)
        if gitio.get_config(root, "core.hooksPath") != str(self.hooks_dir):
            gitio.set_config(root, "core.hooksPath", str(self.hooks_dir))
        links = self.symlinks_in(project_id)
        if links:
            raise ProjectUnavailable(project_id, links)

    def symlinks_in(self, project_id: str) -> list[str]:
        """The symbolic links in a project's working tree, relative to it; changes nothing."""
        root = self.project_dir(project_id)
        return [str(link.relative_to(root)) for link in _symlinks_in(root)]

    def check_project(self, project_id: str) -> ProjectUnavailable | None:
        """Secure a project and remember whether the instance will serve it: why not, or `None`."""
        try:
            self.secure_project(project_id)
        except ProjectUnavailable as refusal:
            self._unavailable[project_id] = refusal
            return refusal
        self._unavailable.pop(project_id, None)
        return None

    def unavailable(self, project_id: str) -> ProjectUnavailable | None:
        """Why a project is not served, or `None` if it is. A project refused earlier is looked at
        again each time, so removing its link brings it back without a restart; one that was fine
        costs nothing here."""
        if project_id not in self._unavailable:
            return None
        return self.check_project(project_id)

    def unavailable_projects(self) -> list[ProjectUnavailable]:
        return [
            refusal
            for project in self.list_projects()
            if (refusal := self.unavailable(project.id)) is not None
        ]

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
                host_key=project.host_key,
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
        host_keys: list[str] | None = None,
        now: float | None = None,
    ) -> Project:
        """Add a project: clone `remote`, or initialise a new review when there is none.

        `host_keys` pins the remote's SSH host key (`known_hosts` lines) instead of trusting
        whatever the host shows at the first clone (`strata.hosted.hostkeys`)."""
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
        pinned = (
            "\n".join(k.line for k in hostkeys.parse_host_keys(host_keys, remote=stored_remote))
            if host_keys
            else None
        )
        pending = Project(
            id=project_id,
            title=title or project_id,
            remote=stored_remote,
            credential_kind=credential_kind,
            credential_secret=credential_secret,
            credential_username=credential_username,
            created=now if now is not None else time.time(),
            host_key=pinned,
        )
        try:
            if stored_remote is not None:
                with self.git_env(pending):
                    # No symbolic links, from the first checkout on (see `secure_project`).
                    gitio.clone(stored_remote, dest, config=SECURE_GIT_CONFIG)
                try:
                    repo = open_repo(dest)
                except RepoNotFoundError:
                    raise InstanceError(
                        f"{stored_remote} holds no strata review (there is no strata.toml on its "
                        "default branch); push the review to it first, or leave out --remote to "
                        "start a new one"
                    ) from None
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
            self.secure_project(project_id)
        except gitio.GitError as exc:
            _remove_tree(dest)
            if hostkeys.is_verification_failure(exc.stderr):
                raise InstanceError(self.host_key_refusal(pending, during="clone")) from None
            raise InstanceError(f"could not clone {stored_remote}: {exc.stderr.strip()}") from None
        except Exception:
            _remove_tree(dest)
            raise
        project = Project(**{**pending.__dict__, "title": resolved_title or project_id})
        self.store.execute(
            "INSERT INTO projects (id, title, remote, credential_kind, credential_secret, "
            "credential_username, created, host_key) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                project.id,
                project.title,
                project.remote,
                project.credential_kind,
                project.credential_secret,
                project.credential_username,
                project.created,
                project.host_key,
            ),
        )
        return project

    # -- SSH host keys ---------------------------------------------------------------------

    def host_key_report(self, project_id: str) -> HostKeyReport | None:
        """The SSH host key(s) a project's remote is trusted with: the pinned ones, or the ones
        trust on first use accepted. `None` where the instance chose no key (an https remote, or
        ssh with no deploy key and no pin, which uses the machine's own known_hosts)."""
        project = self.get_project(project_id)
        target = hostkeys.ssh_host_of(project.remote) if project and project.remote else None
        if project is None or target is None:
            return None
        host, port = target
        name = hostkeys.known_hosts_host(host, port)
        if project.host_key:
            return HostKeyReport(name, True, hostkeys.parse_stored(project.host_key))
        if project.credential_kind == "ssh-key":
            accepted = hostkeys.accepted_keys(self.state_dir / "known_hosts", host, port)
            return HostKeyReport(name, False, accepted)
        return None

    def set_host_keys(self, project_id: str, host_keys: list[str] | None) -> list[hostkeys.HostKey]:
        """Pin an existing project's remote to `host_keys` (`known_hosts` lines), or with `None`
        go back to trust on first use. The keys pinned."""
        project = self.get_project(project_id)
        if project is None:
            known = ", ".join(p.id for p in self.list_projects()) or "none yet"
            raise InstanceError(
                f"there is no project called {project_id!r}; this instance has: {known}"
            )
        keys = hostkeys.parse_host_keys(host_keys, remote=project.remote) if host_keys else []
        self.store.execute(
            "UPDATE projects SET host_key = ? WHERE id = ?",
            ("\n".join(k.line for k in keys) or None, project_id),
        )
        return keys

    def host_key_refusal(self, project: Project, *, during: str) -> str:
        """The plain-words message for ssh having refused `project`'s git host because of its key
        (`during` is `clone` or `sync`)."""
        report_keys: list[hostkeys.HostKey] = []
        target = hostkeys.ssh_host_of(project.remote) if project.remote else None
        if target is not None and project.host_key is None and project.credential_kind == "ssh-key":
            report_keys = hostkeys.accepted_keys(self.state_dir / "known_hosts", *target)
        pinned = hostkeys.parse_stored(project.host_key) if project.host_key else []
        return hostkeys.verification_failure_message(
            project.id, project.remote or "", pinned=pinned, accepted=report_keys, during=during
        )


def _project(row: Any) -> Project:
    return Project(
        id=row["id"],
        title=row["title"],
        remote=row["remote"],
        credential_kind=row["credential_kind"],
        credential_secret=row["credential_secret"],
        credential_username=row["credential_username"],
        created=row["created"],
        host_key=row["host_key"],
    )


def _remove_tree(path: Path) -> None:
    import shutil

    if path.exists():
        shutil.rmtree(path, ignore_errors=True)
