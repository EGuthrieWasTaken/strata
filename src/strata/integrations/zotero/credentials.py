"""Where a Zotero Web API key lives: the operating system's keychain, and nowhere else.

Implements openspec:zotero-integration#api-keys-are-never-stored-in-the-repository. A key committed
to a shared review repository is an irreversible leak, so it is never written to `strata.toml`, to
a file in the repository, or to a file anywhere else: it goes to the OS keychain through `keyring`,
or it is read from an environment variable and `strata` says that it is not being kept.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, Protocol

SERVICE = "strata-zotero"
ACCOUNT = "api-key"
ENV_VAR = "STRATA_ZOTERO_API_KEY"

KeySource = Literal["keychain", "environment"]


class Keystore(Protocol):
    """A place secrets are kept for the current user."""

    def available(self) -> bool:
        """Whether this machine has a working keychain."""
        ...

    def get(self) -> str | None: ...

    def set(self, secret: str) -> None: ...


class KeyringStore:
    """The OS keychain, through the optional `keyring` package.

    Unavailable (never an error) when `keyring` is not installed or finds no working backend, as on
    a server with no desktop session; the caller then falls back to the environment variable.
    """

    def available(self) -> bool:
        try:
            import keyring
            from keyring.backends import fail, null
        except ImportError:
            return False
        return not isinstance(keyring.get_keyring(), fail.Keyring | null.Keyring)

    def get(self) -> str | None:
        if not self.available():
            return None
        import keyring
        from keyring.errors import KeyringError

        try:
            return keyring.get_password(SERVICE, ACCOUNT)
        except KeyringError:
            return None

    def set(self, secret: str) -> None:
        import keyring

        keyring.set_password(SERVICE, ACCOUNT, secret)


@dataclass(frozen=True)
class ResolvedKey:
    """A key found, and where it came from.

    `persisted` is false when the key came from the environment on a machine with no keychain: it
    exists only for this run, and the person is told so.
    """

    key: str
    source: KeySource
    persisted: bool

    @property
    def notice(self) -> str | None:
        if self.persisted:
            return None
        return (
            f"Zotero API key read from ${ENV_VAR}; this machine has no keychain, so it is not "
            "being stored anywhere (nothing is written to disk)"
        )


def resolve_key(store: Keystore, environ: Mapping[str, str] | None = None) -> ResolvedKey | None:
    """The key to use now: the keychain's, else the environment's; `None` if there is neither."""
    env = os.environ if environ is None else environ
    keychain = store.get() if store.available() else None
    if keychain:
        return ResolvedKey(keychain, "keychain", persisted=True)
    from_env = (env.get(ENV_VAR) or "").strip()
    if from_env:
        return ResolvedKey(from_env, "environment", persisted=store.available())
    return None


def save_key(store: Keystore, secret: str) -> bool:
    """Keep a key in the keychain; whether it was kept (it is not when there is no keychain)."""
    if not store.available():
        return False
    store.set(secret.strip())
    return True
