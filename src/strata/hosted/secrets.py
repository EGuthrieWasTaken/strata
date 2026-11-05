"""Instance secrets: openspec:hosted-deployment#instance-secrets-never-reach-a-repository.

A secret is looked up by name, first among what the operator supplied and then among what the
instance stores itself:

1. an environment variable `STRATA_SECRET_<NAME>` (the name upper-cased, `-` and `.` as `_`);
2. a file `<secrets dir>/<name>`, where the secrets directory is `STRATA_SECRETS_DIR` or
   `/run/secrets` (where Docker and Compose mount container secrets);
3. a value an administrator stored with `strata host secret set`, kept in instance state encrypted
   with the instance key (Fernet: AES-128-CBC with an HMAC-SHA256 tag).

The instance key is `STRATA_INSTANCE_KEY` (or the file `STRATA_INSTANCE_KEY_FILE` names, such as a
container secret) when the operator supplies one, else `<data>/instance/instance.key`, created
with mode 0600 by `strata host init`. Keeping the key in
the operator's secret store rather than on the data volume means a copy of the volume alone does
not reveal the stored secrets.

Secrets are only ever handed to git through its environment (`strata.gitio.environment`): a
deploy key is written to a 0600 file under the instance's own temporary directory for the length
of one command, and a token is answered to git through `GIT_ASKPASS`. Nothing here writes inside a
project, and no secret is ever returned to a page: the interface shows only secret *names*.
"""

from __future__ import annotations

import contextlib
import os
import re
import secrets as secrets_lib
import tempfile
from collections.abc import Iterator, Mapping
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from strata.hosted.store import Store

SECRET_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
DEFAULT_SECRETS_DIR = Path("/run/secrets")
KEY_ENV = "STRATA_INSTANCE_KEY"
KEY_FILE_ENV = "STRATA_INSTANCE_KEY_FILE"

_ASKPASS = """#!/bin/sh
# Written by strata host: answers git's credential prompts from the environment of the one git
# command that needs them. It holds no secret itself.
case "$1" in
  Username*) printf '%s\\n' "$STRATA_GIT_USERNAME" ;;
  *) printf '%s\\n' "$STRATA_GIT_PASSWORD" ;;
esac
"""

#: What every git command the instance runs gets, credential or not: never wait for a person to
#: type a password at a terminal nobody is watching.
NO_PROMPT_ENV = {"GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never"}


class SecretError(ValueError):
    pass


def env_name(name: str) -> str:
    return "STRATA_SECRET_" + re.sub(r"[^A-Za-z0-9]", "_", name).upper()


def generate_key() -> bytes:
    return Fernet.generate_key()


class SecretStore:
    """Secrets for one instance."""

    def __init__(
        self,
        store: Store,
        key_path: Path,
        *,
        environ: Mapping[str, str] | None = None,
        secrets_dir: Path | None = None,
    ) -> None:
        self._store = store
        self._key_path = key_path
        self._environ = os.environ if environ is None else environ
        configured = self._environ.get("STRATA_SECRETS_DIR")
        self._secrets_dir = secrets_dir or (Path(configured) if configured else DEFAULT_SECRETS_DIR)

    # -- the key ---------------------------------------------------------------------------

    def _supplied_key(self) -> str | None:
        if self._environ.get(KEY_ENV):
            return self._environ[KEY_ENV]
        key_file = self._environ.get(KEY_FILE_ENV)
        if key_file:
            try:
                return Path(key_file).read_text(encoding="ascii").strip()
            except OSError as exc:
                raise SecretError(f"cannot read the instance key from {key_file}: {exc}") from None
        return None

    def ensure_key(self) -> None:
        """Create the instance key file unless the operator supplies the key."""
        if self._supplied_key() or self._key_path.exists():
            return
        self._key_path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self._key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(generate_key())

    def _fernet(self) -> Fernet:
        supplied = self._supplied_key()
        if supplied:
            key = supplied.strip().encode("ascii")
        elif self._key_path.exists():
            key = self._key_path.read_bytes().strip()
        else:
            raise SecretError(
                f"there is no instance key: set {KEY_ENV} or {KEY_FILE_ENV}, or run "
                "`strata host init` to create one"
            )
        try:
            return Fernet(key)
        except ValueError as exc:
            raise SecretError(f"the instance key is not a valid key: {exc}") from None

    # -- secrets ---------------------------------------------------------------------------

    def get(self, name: str) -> str | None:
        """The secret called `name`, or `None` if nobody supplied or stored one."""
        supplied = self._environ.get(env_name(name))
        if supplied:
            return supplied
        if SECRET_NAME_RE.match(name):
            path = self._secrets_dir / name
            with contextlib.suppress(OSError):
                if path.is_file():
                    return path.read_text(encoding="utf-8").strip("\n")
        row = self._store.one("SELECT ciphertext FROM secrets WHERE name = ?", (name,))
        if row is None:
            return None
        try:
            return self._fernet().decrypt(bytes(row["ciphertext"])).decode("utf-8")
        except InvalidToken:
            raise SecretError(
                f"the stored secret {name!r} cannot be decrypted with this instance key"
            ) from None

    def source(self, name: str) -> str | None:
        """Where `name` comes from (`environment`, `file`, `stored`), never its value."""
        if self._environ.get(env_name(name)):
            return "environment"
        if SECRET_NAME_RE.match(name) and (self._secrets_dir / name).is_file():
            return "file"
        if self._store.one("SELECT 1 FROM secrets WHERE name = ?", (name,)) is not None:
            return "stored"
        return None

    def put(self, name: str, value: str) -> None:
        """Store `value` under `name`, encrypted with the instance key."""
        if not SECRET_NAME_RE.match(name):
            raise SecretError(f"invalid secret name {name!r} (must match {SECRET_NAME_RE.pattern})")
        if not value:
            raise SecretError("a secret cannot be empty")
        ciphertext = self._fernet().encrypt(value.encode("utf-8"))
        self._store.execute(
            "INSERT INTO secrets (name, ciphertext) VALUES (?, ?) "
            "ON CONFLICT (name) DO UPDATE SET ciphertext = excluded.ciphertext",
            (name, ciphertext),
        )

    def delete(self, name: str) -> bool:
        return self._store.execute("DELETE FROM secrets WHERE name = ?", (name,)) > 0

    def stored_names(self) -> list[str]:
        return [row["name"] for row in self._store.all("SELECT name FROM secrets ORDER BY name")]


@contextlib.contextmanager
def git_credential_env(
    secrets: SecretStore,
    *,
    kind: str | None,
    secret: str | None,
    username: str | None,
    tmp_dir: Path,
) -> Iterator[dict[str, str]]:
    """The environment git needs to reach a project's remote with its credential.

    `kind` is `ssh-key` (a deploy key: the secret is the private key) or `token` (HTTPS: the secret
    is the password or token, `username` the name to send with it, `x-access-token` if none). With
    no credential, git uses whatever the container offers (an SSH agent, a credential helper) but
    is still told never to prompt.
    """
    env = dict(NO_PROMPT_ENV)
    if kind is None or secret is None:
        yield env
        return
    value = secrets.get(secret)
    if value is None:
        raise SecretError(
            f"the remote credential {secret!r} is not available: supply {env_name(secret)}, a "
            f"file named {secret!r} in the secrets directory, or `strata host secret set {secret}`"
        )
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir.chmod(0o700)
    if kind == "ssh-key":
        fd, key_file = tempfile.mkstemp(prefix="deploy-key-", dir=tmp_dir)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(value if value.endswith("\n") else value + "\n")
            known_hosts = tmp_dir.parent / "known_hosts"
            env["GIT_SSH_COMMAND"] = (
                f"ssh -i '{key_file}' -o IdentitiesOnly=yes -o BatchMode=yes "
                f"-o StrictHostKeyChecking=accept-new -o UserKnownHostsFile='{known_hosts}'"
            )
            yield env
        finally:
            with contextlib.suppress(OSError):
                os.unlink(key_file)
    elif kind == "token":
        askpass = tmp_dir.parent / "git-askpass.sh"
        if not askpass.exists() or askpass.read_text(encoding="utf-8") != _ASKPASS:
            askpass.write_text(_ASKPASS, encoding="utf-8")
        askpass.chmod(0o700)
        env.update(
            {
                "GIT_ASKPASS": str(askpass),
                "STRATA_GIT_USERNAME": username or "x-access-token",
                "STRATA_GIT_PASSWORD": value,
            }
        )
        yield env
    else:
        raise SecretError(f"unknown credential kind {kind!r}; use ssh-key or token")


def random_token() -> str:
    """A fresh 256-bit URL-safe token (sessions, invitations, API tokens)."""
    return secrets_lib.token_urlsafe(32)
