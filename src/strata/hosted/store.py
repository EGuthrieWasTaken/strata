"""The instance-state database: openspec:hosted-deployment#projects-and-instance-state.

One SQLite file, `<data>/instance/instance.db`, holds what the instance knows about its users and
projects. It lives outside every review repository by construction: the projects are siblings
under `<data>/projects/`, and nothing here ever writes into one.

SQLite rather than files because several requests (and the background sync) read and write it at
once, and a sign-in, a membership change or a sync result must be all-or-nothing. Each call opens
its own connection, so the store is safe to share between threads.
"""

from __future__ import annotations

import contextlib
import sqlite3
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from strata.hosted import audit

#: 2 added the audit log, API tokens that name a project and expire, and a project's pinned SSH
#: host key. `Store.upgrade` brings an older database up to date.
SCHEMA_VERSION = 2

#: Who the audit log names for what an upgrade does by itself.
UPGRADE_ACTOR = "instance upgrade"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS users (
    username TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    email TEXT,
    password_hash TEXT,
    is_admin INTEGER NOT NULL DEFAULT 0,
    disabled INTEGER NOT NULL DEFAULT 0,
    created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS identities (
    provider TEXT NOT NULL,
    subject TEXT NOT NULL,
    username TEXT NOT NULL REFERENCES users(username),
    PRIMARY KEY (provider, subject)
);
CREATE TABLE IF NOT EXISTS invitations (
    token_hash TEXT PRIMARY KEY,
    username TEXT NOT NULL REFERENCES users(username),
    expires REAL NOT NULL,
    used INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    remote TEXT,
    credential_kind TEXT,
    credential_secret TEXT,
    credential_username TEXT,
    created REAL NOT NULL,
    host_key TEXT
);
CREATE TABLE IF NOT EXISTS memberships (
    project TEXT NOT NULL REFERENCES projects(id),
    username TEXT NOT NULL REFERENCES users(username),
    actor TEXT NOT NULL,
    role TEXT NOT NULL,
    PRIMARY KEY (project, username),
    UNIQUE (project, actor)
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    username TEXT NOT NULL REFERENCES users(username),
    csrf TEXT NOT NULL,
    created REAL NOT NULL,
    last_seen REAL NOT NULL,
    expires REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS api_tokens (
    token_hash TEXT PRIMARY KEY,
    username TEXT NOT NULL REFERENCES users(username),
    label TEXT NOT NULL,
    created REAL NOT NULL,
    last_used REAL,
    project TEXT,
    expires REAL
);
CREATE TABLE IF NOT EXISTS signins (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    username TEXT NOT NULL,
    client TEXT NOT NULL,
    method TEXT NOT NULL,
    outcome TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS signins_by_user ON signins (username, ts);
CREATE INDEX IF NOT EXISTS signins_by_client ON signins (client, ts);
CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    performed_by TEXT NOT NULL,
    action TEXT NOT NULL,
    project TEXT,
    subject TEXT,
    detail TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS oidc_flows (
    state TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    nonce TEXT NOT NULL,
    verifier TEXT NOT NULL,
    invitation TEXT,
    created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS secrets (
    name TEXT PRIMARY KEY,
    ciphertext BLOB NOT NULL
);
CREATE TABLE IF NOT EXISTS sync_status (
    project TEXT PRIMARY KEY REFERENCES projects(id),
    last_fetch REAL,
    last_success REAL,
    last_push REAL,
    last_error TEXT,
    failures INTEGER NOT NULL DEFAULT 0,
    next_retry REAL,
    push_pending INTEGER NOT NULL DEFAULT 0,
    pending_actor TEXT,
    conflicts TEXT
);
CREATE TABLE IF NOT EXISTS screening_batches (
    project TEXT NOT NULL,
    actor TEXT NOT NULL,
    pending INTEGER NOT NULL,
    first REAL NOT NULL,
    last REAL NOT NULL,
    PRIMARY KEY (project, actor)
);
"""

#: Columns added after the first release: (table, column, type). A database made before has the
#: tables without them; `Store.upgrade` adds them, leaving every existing row as it was, except
#: that a token with no project and no expiry (one made before tokens named a project and expired)
#: is given an expiry of the moment of the upgrade, so it stops working.
_ADDED_COLUMNS = (
    ("api_tokens", "project", "TEXT"),
    ("api_tokens", "expires", "REAL"),
    ("projects", "host_key", "TEXT"),
)


def _expire_tokens_from_before(connection: sqlite3.Connection, now: float) -> int:
    """End every API token in `api_tokens` at `now`, in the caller's transaction, and say so in the
    audit log, one entry per token (who it was made for and its label, never the token). Called
    only when the table has just gained its `expires` column, so each row is one made before tokens
    named a project and expired."""
    rows = connection.execute("SELECT username, label FROM api_tokens ORDER BY created").fetchall()
    connection.execute("UPDATE api_tokens SET expires = ?", (now,))
    for username, label in rows:
        audit.record(
            connection, by=UPGRADE_ACTOR, action=audit.TOKEN_EXPIRE, subject=username, now=now,
            detail=(
                f"token {label!r} made before tokens named a project and expired, expired by the "
                "upgrade so that it no longer reads every project its owner is in"
            ),
        )  # fmt: skip
    return len(rows)


class Store:
    """The instance-state database at `path`."""

    def __init__(self, path: Path) -> None:
        self.path = path

    @contextlib.contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        """A connection inside one transaction: committed when the block ends, rolled back if it
        raises."""
        connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
            except BaseException:
                connection.execute("ROLLBACK")
                raise
            connection.execute("COMMIT")
        finally:
            connection.close()

    def create(self) -> int:
        """Create the database (or bring an existing one up to this schema). How many API tokens
        the upgrade expired, as `upgrade` says."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        new = not self.path.exists()
        expired = self._apply_schema(journal_mode="WAL")
        if new:
            self.path.chmod(0o600)
        return expired

    def needs_upgrade(self) -> bool:
        """Whether the database was made by an earlier version of this schema."""
        row = self.one("SELECT value FROM meta WHERE key = 'schema_version'")
        return row is None or int(row["value"]) < SCHEMA_VERSION

    def upgrade(self, *, now: float | None = None) -> int:
        """Bring an existing database up to this schema, keeping what it holds. Safe to run again,
        and safe to run in two processes at once.

        An API token made before tokens named a project and expired would, kept as it was, read
        every project its owner is in and never stop. The upgrade gives each an expiry of `now`
        instead (they stay in the database, so they can still be revoked, and a holder is told the
        token expired) and writes an audit entry for each. How many it expired; only the first run
        of an upgrade finds any."""
        if not self.exists():
            raise FileNotFoundError(self.path)
        return self._apply_schema(now=now)

    def _apply_schema(self, *, journal_mode: str | None = None, now: float | None = None) -> int:
        expired = 0
        connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        try:
            if journal_mode is not None:
                connection.execute(f"PRAGMA journal_mode = {journal_mode}")
            # New tables arrive with `CREATE TABLE IF NOT EXISTS`; columns added to tables that
            # exist need `ALTER TABLE`, checked and made in one transaction so that two processes
            # upgrading at once cannot both add the same column.
            connection.executescript(_SCHEMA)
            connection.execute("BEGIN IMMEDIATE")
            try:
                for table, column, kind in _ADDED_COLUMNS:
                    present = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
                    if column not in present:
                        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {kind}")
                        if (table, column) == ("api_tokens", "expires"):
                            # Every token there is now was made before they expired.
                            expired = _expire_tokens_from_before(
                                connection, now if now is not None else time.time()
                            )
                connection.execute(
                    "INSERT OR IGNORE INTO meta (key, value) VALUES ('schema_version', ?)",
                    (str(SCHEMA_VERSION),),
                )
                connection.execute(
                    "UPDATE meta SET value = ? WHERE key = 'schema_version' "
                    "AND CAST(value AS INTEGER) < ?",
                    (str(SCHEMA_VERSION), SCHEMA_VERSION),
                )
            except BaseException:
                connection.execute("ROLLBACK")
                raise
            connection.execute("COMMIT")
        finally:
            connection.close()
        return expired

    def exists(self) -> bool:
        return self.path.is_file()

    def one(self, sql: str, params: tuple[Any, ...] = ()) -> sqlite3.Row | None:
        with self.connect() as db:
            row: sqlite3.Row | None = db.execute(sql, params).fetchone()
            return row

    def all(self, sql: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        with self.connect() as db:
            return list(db.execute(sql, params).fetchall())

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> int:
        """Run one statement; the number of rows it changed."""
        with self.connect() as db:
            return db.execute(sql, params).rowcount
