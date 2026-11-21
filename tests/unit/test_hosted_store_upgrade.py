"""An instance created by an earlier version keeps working after an upgrade
(openspec:hosted-deployment#projects-and-instance-state): new columns and tables arrive, and what
was already there, API tokens included, keeps its meaning."""

from __future__ import annotations

from pathlib import Path

from strata.hosted import accounts
from strata.hosted.store import SCHEMA_VERSION, Store


def _old_instance(path: Path) -> Store:
    """A database as the first release of the hosted mode left it: no audit log, and API tokens
    and projects without the newer columns."""
    store = Store(path)
    store.create()
    with store.connect() as db:
        db.execute("DROP TABLE audit")
        db.execute("ALTER TABLE api_tokens DROP COLUMN project")
        db.execute("ALTER TABLE api_tokens DROP COLUMN expires")
        db.execute("ALTER TABLE projects DROP COLUMN host_key")
        db.execute("UPDATE meta SET value = '1' WHERE key = 'schema_version'")
    return store


def _columns(store: Store, table: str) -> set[str]:
    return {row["name"] for row in store.all(f"PRAGMA table_info({table})")}


def test_an_older_database_is_brought_up_to_this_schema(tmp_path: Path) -> None:
    store = _old_instance(tmp_path / "instance.db")
    assert "project" not in _columns(store, "api_tokens")

    store.upgrade()

    assert {"project", "expires"} <= _columns(store, "api_tokens")
    assert "host_key" in _columns(store, "projects")
    assert _columns(store, "audit")
    version = store.one("SELECT value FROM meta WHERE key = 'schema_version'")
    assert version is not None and version["value"] == str(SCHEMA_VERSION)


def test_upgrading_twice_changes_nothing_the_second_time(tmp_path: Path) -> None:
    store = _old_instance(tmp_path / "instance.db")
    store.upgrade()
    store.upgrade()
    assert {"project", "expires"} <= _columns(store, "api_tokens")


def test_a_token_made_before_the_upgrade_keeps_working_until_it_is_revoked(
    tmp_path: Path,
) -> None:
    store = _old_instance(tmp_path / "instance.db")
    accounts.add_user(store, "sam", password="a long enough password")
    # What the first release stored: a hash, the user, a label, a creation time.
    token = "strata_an-old-token"
    store.execute(
        "INSERT INTO api_tokens (token_hash, username, label, created) VALUES (?, ?, 'mcp', 0)",
        (accounts._digest(token), "sam"),
    )

    store.upgrade()

    found = accounts.api_token(store, token, now=10.0**10)  # far in the future
    assert isinstance(found, accounts.ApiToken)
    assert found.username == "sam" and found.project is None and found.expires is None
    assert accounts.revoke_api_tokens(store, "sam", by="admin") == 1
    assert accounts.api_token(store, token, now=10.0**10) is None
