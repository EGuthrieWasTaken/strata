"""An instance created by an earlier version keeps working after an upgrade
(openspec:hosted-deployment#projects-and-instance-state): new columns and tables arrive and what was
already there is kept. The exception is the API tokens from before, which named no project and
never expired: the upgrade expires them, so that a token that leaked long ago stops reading every
project its owner is in (openspec:hosted-deployment#api-tokens-name-one-project-and-expire)."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from strata.hosted import accounts, audit
from strata.hosted.instance import Instance
from strata.hosted.store import SCHEMA_VERSION, Store

NOW = 1_800_000_000.0
YEAR = 365 * 24 * 3600.0
PASSWORD = "a long enough password"


def _downgrade(store: Store) -> Store:
    """Leave `store` as the first release of the hosted mode left it: no audit log, and API tokens
    and projects without the newer columns."""
    with store.connect() as db:
        db.execute("DROP TABLE audit")
        db.execute("ALTER TABLE api_tokens DROP COLUMN project")
        db.execute("ALTER TABLE api_tokens DROP COLUMN expires")
        db.execute("ALTER TABLE projects DROP COLUMN host_key")
        db.execute("UPDATE meta SET value = '1' WHERE key = 'schema_version'")
    return store


def _old_instance(path: Path) -> Store:
    store = Store(path)
    store.create()
    return _downgrade(store)


def _old_token(store: Store, token: str, *, username: str = "sam", label: str = "mcp") -> str:
    """What the first release stored for a token: a hash, the user, a label, a creation time."""
    store.execute(
        "INSERT INTO api_tokens (token_hash, username, label, created) VALUES (?, ?, ?, 0)",
        (accounts._digest(token), username, label),
    )
    return token


def _store_with_an_old_token(tmp_path: Path) -> tuple[Store, str]:
    store = _old_instance(tmp_path / "instance.db")
    accounts.add_user(store, "sam", password=PASSWORD)
    return store, _old_token(store, "strata_an-old-token")


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


# ------------------------------------------------------------ tokens made before the upgrade


def test_a_token_made_before_the_upgrade_is_expired_by_it_and_says_when(tmp_path: Path) -> None:
    store, token = _store_with_an_old_token(tmp_path)

    expired = store.upgrade(now=NOW)

    assert expired == 1
    with pytest.raises(accounts.TokenExpired) as refused:
        accounts.api_token(store, token, now=NOW + 10 * YEAR)
    assert refused.value.expires == NOW  # the day of the upgrade, which is what the holder is told


def test_an_expired_old_token_is_kept_so_that_it_can_still_be_revoked(tmp_path: Path) -> None:
    store, token = _store_with_an_old_token(tmp_path)
    store.upgrade(now=NOW)

    assert accounts.revoke_api_tokens(store, "sam", by="admin", now=NOW + 1) == 1

    assert accounts.api_token(store, token, now=NOW + 2) is None  # now simply unknown


def test_the_upgrade_records_each_token_it_expired_without_the_token(tmp_path: Path) -> None:
    store, token = _store_with_an_old_token(tmp_path)
    _old_token(store, "strata_another-old-token", username="sam", label="laptop")

    store.upgrade(now=NOW)

    entries = audit.entries(store)
    assert sorted(str(e["detail"]).split("'")[1] for e in entries) == ["laptop", "mcp"]
    for entry in entries:
        assert (entry["action"], entry["by"], entry["subject"], entry["ts"]) == (
            audit.TOKEN_EXPIRE, "instance upgrade", "sam", NOW,
        )  # fmt: skip
        assert "before tokens named a project" in str(entry["detail"])
        assert token not in str(entry["detail"])
        assert accounts._digest(token) not in str(entry["detail"])


def test_upgrading_again_expires_nothing_more_and_leaves_newer_tokens_alone(
    tmp_path: Path,
) -> None:
    store, _old = _store_with_an_old_token(tmp_path)
    store.upgrade(now=NOW)
    fresh = accounts.create_api_token(
        store, "sam", label="new", project="spacing", by="admin", now=NOW + 5
    )

    assert store.upgrade(now=NOW + 10) == 0

    assert [e["action"] for e in audit.entries(store)].count(audit.TOKEN_EXPIRE) == 1
    assert accounts.api_token(store, fresh, now=NOW + 20) is not None


def test_an_upgrade_with_no_old_tokens_expires_none_and_writes_nothing(tmp_path: Path) -> None:
    store = _old_instance(tmp_path / "instance.db")
    assert store.upgrade(now=NOW) == 0
    assert audit.entries(store) == []


def test_starting_the_instance_expires_old_tokens_and_the_log_says_how_many(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    instance = Instance(tmp_path / "data", environ={})
    instance.initialise()
    _downgrade(instance.store)
    accounts.add_user(instance.store, "sam", password=PASSWORD)
    _old_token(instance.store, "strata_one", label="mcp")
    _old_token(instance.store, "strata_two", label="laptop")

    with caplog.at_level(logging.WARNING, logger="strata.hosted"):
        instance.require_initialised()

    said = [r.getMessage() for r in caplog.records if r.name == "strata.hosted"]
    assert len(said) == 1
    assert "2 API tokens" in said[0] and "expired" in said[0]
    assert "strata host token add" in said[0] and "strata host audit" in said[0]
    caplog.clear()
    instance.require_initialised()  # nothing left to upgrade, so nothing more is said
    assert not caplog.records


def test_the_log_says_one_token_in_the_singular(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    instance = Instance(tmp_path / "data", environ={})
    instance.initialise()
    _downgrade(instance.store)
    accounts.add_user(instance.store, "sam", password=PASSWORD)
    _old_token(instance.store, "strata_one")

    with caplog.at_level(logging.WARNING, logger="strata.hosted"):
        instance.require_initialised()

    assert "1 API token " in caplog.text and "1 API tokens" not in caplog.text


# ------------------------------------------------- a row that slipped through is refused too


@pytest.mark.parametrize(
    ("project", "expires"),
    [(None, None), ("spacing", None), (None, NOW + 1000.0)],
    ids=["no project and no expiry", "no expiry", "no project"],
)
def test_a_token_row_without_a_project_or_an_expiry_is_refused_as_expired(
    tmp_path: Path, project: str | None, expires: float | None
) -> None:
    """The upgrade expires old tokens, but the check does not rely on it: a row that names no
    project or never expires is refused rather than believed to read everything."""
    store = Store(tmp_path / "instance.db")
    store.create()
    accounts.add_user(store, "sam", password=PASSWORD)
    store.execute(
        "INSERT INTO api_tokens (token_hash, username, label, created, project, expires) "
        "VALUES (?, 'sam', 'mcp', 0, ?, ?)",
        (accounts._digest("strata_odd"), project, expires),
    )

    with pytest.raises(accounts.TokenExpired) as refused:
        accounts.api_token(store, "strata_odd", now=NOW)

    assert refused.value.expires <= NOW
