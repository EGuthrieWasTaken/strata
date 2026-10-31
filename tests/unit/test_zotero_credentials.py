"""Where a Zotero Web API key lives.

openspec:zotero-integration#api-keys-are-never-stored-in-the-repository
"""

from __future__ import annotations

from pathlib import Path

import pytest

from strata.integrations.zotero import credentials
from strata.integrations.zotero.credentials import (
    ENV_VAR,
    KeyringStore,
    resolve_key,
    save_key,
)
from tests.unit._zotero import MemoryKeystore


def test_the_keychain_is_preferred_to_the_environment() -> None:
    store = MemoryKeystore(available_=True, secret="from-keychain")

    resolved = resolve_key(store, {ENV_VAR: "from-env"})

    assert resolved is not None
    assert (resolved.key, resolved.source, resolved.persisted) == (
        "from-keychain",
        "keychain",
        True,
    )
    assert resolved.notice is None


def test_with_no_keychain_the_key_is_read_from_the_environment_and_a_notice_says_it_is_not_kept(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    store = MemoryKeystore(available_=False)

    resolved = resolve_key(store, {ENV_VAR: "from-env"})

    assert resolved is not None
    assert (resolved.key, resolved.source, resolved.persisted) == ("from-env", "environment", False)
    assert resolved.notice is not None
    assert "not being stored" in resolved.notice and ENV_VAR in resolved.notice
    assert store.writes == []
    assert list(tmp_path.iterdir()) == []  # nothing written to disk


def test_a_keychain_with_no_key_falls_back_to_the_environment_without_the_notice() -> None:
    resolved = resolve_key(MemoryKeystore(available_=True), {ENV_VAR: " from-env "})

    assert resolved is not None
    assert resolved.key == "from-env"  # surrounding space is not part of a key
    assert resolved.notice is None  # there is a keychain; the person simply has not used it


def test_no_key_anywhere_is_none() -> None:
    assert resolve_key(MemoryKeystore(available_=True), {}) is None
    assert resolve_key(MemoryKeystore(available_=False), {ENV_VAR: "  "}) is None


def test_saving_needs_a_keychain() -> None:
    kept = MemoryKeystore(available_=True)
    assert save_key(kept, "  secret  ") is True
    assert kept.secret == "secret"

    lost = MemoryKeystore(available_=False)
    assert save_key(lost, "secret") is False
    assert lost.writes == []


def test_the_real_keyring_store_reports_unavailable_on_a_machine_with_no_keychain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import keyring
    from keyring.backends import fail

    monkeypatch.setattr(keyring, "get_keyring", lambda: fail.Keyring())

    store = KeyringStore()

    assert store.available() is False
    assert store.get() is None


def test_the_real_keyring_store_round_trips_through_a_working_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import keyring
    from keyring.backend import KeyringBackend

    class Memory(KeyringBackend):
        priority = 1  # type: ignore[assignment]

        def __init__(self) -> None:
            self.saved: dict[tuple[str, str], str] = {}

        def get_password(self, service: str, username: str) -> str | None:
            return self.saved.get((service, username))

        def set_password(self, service: str, username: str, password: str) -> None:
            self.saved[(service, username)] = password

        def delete_password(self, service: str, username: str) -> None:
            self.saved.pop((service, username), None)

    backend = Memory()
    monkeypatch.setattr(keyring, "get_keyring", lambda: backend)
    monkeypatch.setattr(keyring, "get_password", backend.get_password)
    monkeypatch.setattr(keyring, "set_password", backend.set_password)

    store = KeyringStore()
    assert store.available() is True
    store.set("secret")

    assert store.get() == "secret"
    assert backend.saved == {(credentials.SERVICE, credentials.ACCOUNT): "secret"}
