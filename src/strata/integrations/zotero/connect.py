"""Choosing how to reach Zotero, and the link a review has to it.

Implements openspec:zotero-integration#transport-selection and
openspec:zotero-integration#api-keys-are-never-stored-in-the-repository. The local API is tried
first, with no key; the Web API is used when the local one is absent, switched off, shaped
differently from what `strata` reads, or the operation writes (the local API is read-only). A key is
asked for only when the Web API is the one being used.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Literal

from strata.core.repo import Repo
from strata.integrations.zotero import credentials
from strata.integrations.zotero.api import (
    LOCAL_BASE_URL,
    WEB_BASE_URL,
    ZoteroApi,
    ZoteroUnavailableError,
)
from strata.integrations.zotero.credentials import Keystore, ResolvedKey
from strata.integrations.zotero.http import HttpTransport, UrllibTransport
from strata.integrations.zotero.manager import KeyInfo, ZoteroManager, key_info
from strata.integrations.zotero.probe import probe_local

TransportName = Literal["local", "web"]
PREFERENCES = ("auto", "local", "web")


def make_http_transport() -> HttpTransport:
    """The transport used for every request; the one seam tests replace."""
    return UrllibTransport()


@dataclass(frozen=True)
class ZoteroLink:
    """The `[zotero]` table of `strata.toml`: which library the review is linked to."""

    library: str
    transport: str = "auto"
    write: bool = False


def read_link(repo: Repo) -> ZoteroLink | None:
    """The review's Zotero link, or `None` if it has none."""
    table = repo.config.get("zotero")
    if not table or "library" not in table:
        return None
    return ZoteroLink(
        library=str(table["library"]),
        transport=str(table.get("transport", "auto")),
        write=bool(table.get("write", False)),
    )


@dataclass(frozen=True)
class Connection:
    """A way of reaching Zotero that has been checked to work."""

    api: ZoteroApi
    transport: TransportName
    #: The personal library as `users/<id>`.
    personal_library: str
    #: Set for the Web API: what the key may do.
    key_info: KeyInfo | None
    #: Things the person should be told, in the order they arose.
    notices: tuple[str, ...]

    def manager(self, library: str, *, writable: bool = False) -> ZoteroManager:
        return ZoteroManager(self.api, library, local=self.transport == "local", writable=writable)


def connect(
    preference: str = "auto",
    *,
    need_write: bool = False,
    store: Keystore | None = None,
    environ: Mapping[str, str] | None = None,
    prompt_key: Callable[[], str | None] | None = None,
    http: HttpTransport | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> Connection:
    """Reach Zotero by the best way available, or raise `ZoteroUnavailableError` saying why not.

    `prompt_key`, if given, is asked for a key only when the Web API is needed, none is stored or
    in the environment, and this machine has a keychain to keep it in: a key is never typed in
    just to be thrown away.
    """
    if preference not in PREFERENCES:
        raise ValueError(f"transport must be one of {PREFERENCES}, got {preference!r}")
    transport = http or make_http_transport()
    keystore = store or credentials.KeyringStore()
    notices: list[str] = []

    if need_write and preference == "local":
        raise ZoteroUnavailableError(
            "writing to Zotero needs the Web API: the local API is read-only"
        )
    if not need_write and preference in ("auto", "local"):
        local, reason = probe_local(transport)
        if local is not None:
            return Connection(
                ZoteroApi(LOCAL_BASE_URL, transport, sleep=sleep), "local", local.library, None, ()
            )
        if preference == "local":
            raise ZoteroUnavailableError(f"the local API cannot be used: {reason}")
        notices.append(f"Zotero's local API is not available ({reason}); using the Web API")

    key = credentials.resolve_key(keystore, environ)
    if key is None and prompt_key is not None and keystore.available():
        entered = (prompt_key() or "").strip()
        if entered:
            credentials.save_key(keystore, entered)
            key = ResolvedKey(entered, "keychain", persisted=True)
    if key is None:
        raise ZoteroUnavailableError(
            "no Zotero API key: create one at https://www.zotero.org/settings/keys and either "
            f"run `strata zotero link --web` to keep it in your keychain or set "
            f"${credentials.ENV_VAR}"
        )
    if key.notice:
        notices.append(key.notice)
    api = ZoteroApi(WEB_BASE_URL, transport, api_key=key.key, sleep=sleep)
    info = key_info(api)
    return Connection(api, "web", f"users/{info.user_id}", info, tuple(notices))
