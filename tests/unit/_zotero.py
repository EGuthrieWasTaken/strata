"""Helpers shared by the Zotero tests."""

from __future__ import annotations

from dataclasses import dataclass, field

from strata.integrations.zotero.api import LOCAL_BASE_URL, WEB_BASE_URL, ZoteroApi
from strata.integrations.zotero.manager import ZoteroManager
from tests.zotero_fake import API_KEY, FakeZotero


@dataclass
class MemoryKeystore:
    """A keychain that lives in memory, or a machine with none (`available=False`)."""

    available_: bool = True
    secret: str | None = None
    writes: list[str] = field(default_factory=list)

    def available(self) -> bool:
        return self.available_

    def get(self) -> str | None:
        return self.secret if self.available_ else None

    def set(self, secret: str) -> None:
        self.writes.append(secret)
        self.secret = secret


class Sleeper:
    """Records the waits a client was told to make, and makes none."""

    def __init__(self) -> None:
        self.waits: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.waits.append(seconds)


def local_api(fake: FakeZotero, sleeper: Sleeper | None = None) -> ZoteroApi:
    return ZoteroApi(LOCAL_BASE_URL, fake, sleep=sleeper or Sleeper())


def web_api(fake: FakeZotero, sleeper: Sleeper | None = None, key: str = API_KEY) -> ZoteroApi:
    return ZoteroApi(WEB_BASE_URL, fake, api_key=key, sleep=sleeper or Sleeper())


def web_manager(
    fake: FakeZotero, library: str = "users/12345", *, writable: bool = True
) -> ZoteroManager:
    return ZoteroManager(web_api(fake), library, local=False, writable=writable)


def local_manager(fake: FakeZotero, library: str = "users/12345") -> ZoteroManager:
    return ZoteroManager(local_api(fake), library, local=True)
