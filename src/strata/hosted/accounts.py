"""Accounts, sign-in and sessions: openspec:hosted-deployment#per-user-authentication and the
sign-in half of openspec:hosted-deployment#hosted-security-baseline.

- **Local accounts** are the default, so an instance needs no identity provider. Passwords are
  hashed with Argon2id (`argon2-cffi`'s defaults: 64 MiB, 3 passes, 4 lanes) and never stored or
  logged in the clear. An administrator creates an account with a password or with an
  invitation, a one-time link the person opens to choose their own password (or to link a
  sign-in provider, `strata.hosted.oidc`).
- **Sign-in is rate limited**: after `MAX_FAILURES_PER_ACCOUNT` failed attempts for one account
  (or `MAX_FAILURES_PER_CLIENT` from one client) within `FAILURE_WINDOW`, further attempts are
  refused, without even checking the password, until `LOCKOUT` has passed since the last failure.
  Every attempt, refused or not, is written to the sign-in log in instance state.
- **Sessions** are random 256-bit tokens; the instance keeps only their SHA-256, so a copy of the
  database cannot be replayed as a cookie. A session ends when it has been idle too long, when it
  reaches its absolute lifetime, when its owner signs out, or when the account is disabled.
  Each session has its own CSRF token, separate from the cookie.
- **API tokens** let an MCP client authenticate as a user
  (openspec:hosted-deployment#remote-mcp-access); stored hashed like sessions.

Disabled accounts cannot sign in and lose their sessions and tokens at once.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import sqlite3
import time
from dataclasses import dataclass

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from strata.hosted.secrets import random_token
from strata.hosted.store import Store

USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
MIN_PASSWORD_LENGTH = 12

MAX_FAILURES_PER_ACCOUNT = 5
MAX_FAILURES_PER_CLIENT = 20
FAILURE_WINDOW = 15 * 60.0
LOCKOUT = 15 * 60.0
INVITATION_LIFETIME = 7 * 24 * 3600.0

_HASHER = PasswordHasher()  # Argon2id
#: Verified against when the account does not exist, so a missing account takes as long to
#: refuse as a wrong password and the timing does not say which accounts exist.
_DUMMY_HASH = _HASHER.hash("strata-dummy-password-for-timing")


class AccountError(ValueError):
    pass


class SignInRefused(Exception):
    """A sign-in that did not succeed. `reason` is `invalid` or `locked`; the message is what the
    person is told, the same for a wrong password and an unknown account."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        message = (
            "too many failed sign-ins; wait a few minutes and try again"
            if reason == "locked"
            else "the user name or password is not right"
        )
        super().__init__(message)


@dataclass(frozen=True)
class User:
    username: str
    display_name: str
    email: str | None
    is_admin: bool
    disabled: bool
    has_password: bool


@dataclass(frozen=True)
class Session:
    username: str
    csrf: str
    created: float
    expires: float


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def hash_password(password: str) -> str:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise AccountError(f"a password must be at least {MIN_PASSWORD_LENGTH} characters")
    return _HASHER.hash(password)


def _user(row: sqlite3.Row) -> User:
    return User(
        username=row["username"],
        display_name=row["display_name"],
        email=row["email"],
        is_admin=bool(row["is_admin"]),
        disabled=bool(row["disabled"]),
        has_password=row["password_hash"] is not None,
    )


# --------------------------------------------------------------------------------- accounts


def add_user(
    store: Store,
    username: str,
    *,
    display_name: str | None = None,
    email: str | None = None,
    password: str | None = None,
    admin: bool = False,
    now: float | None = None,
) -> User:
    if not USERNAME_RE.match(username):
        raise AccountError(f"invalid user name {username!r} (must match {USERNAME_RE.pattern})")
    if get_user(store, username) is not None:
        raise AccountError(f"there is already an account called {username!r}")
    hashed = hash_password(password) if password is not None else None
    store.execute(
        "INSERT INTO users (username, display_name, email, password_hash, is_admin, created) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            username,
            display_name or username,
            email,
            hashed,
            int(admin),
            now if now is not None else time.time(),
        ),
    )
    user = get_user(store, username)
    assert user is not None
    return user


def get_user(store: Store, username: str) -> User | None:
    row = store.one("SELECT * FROM users WHERE username = ?", (username,))
    return _user(row) if row is not None else None


def list_users(store: Store) -> list[User]:
    return [_user(row) for row in store.all("SELECT * FROM users ORDER BY username")]


def set_password(store: Store, username: str, password: str) -> None:
    hashed = hash_password(password)
    if not store.execute(
        "UPDATE users SET password_hash = ? WHERE username = ?", (hashed, username)
    ):
        raise AccountError(f"there is no account called {username!r}")


def disable_user(store: Store, username: str) -> None:
    """Disable an account: it can no longer sign in, and its sessions and tokens end now."""
    with store.connect() as db:
        if not db.execute("UPDATE users SET disabled = 1 WHERE username = ?", (username,)).rowcount:
            raise AccountError(f"there is no account called {username!r}")
        db.execute("DELETE FROM sessions WHERE username = ?", (username,))
        db.execute("DELETE FROM api_tokens WHERE username = ?", (username,))


def enable_user(store: Store, username: str) -> None:
    if not store.execute("UPDATE users SET disabled = 0 WHERE username = ?", (username,)):
        raise AccountError(f"there is no account called {username!r}")


# ------------------------------------------------------------------------------ invitations


def create_invitation(
    store: Store, username: str, *, now: float | None = None, lifetime: float = INVITATION_LIFETIME
) -> str:
    """A one-time token that lets `username` set a password or link a sign-in provider."""
    if get_user(store, username) is None:
        raise AccountError(f"there is no account called {username!r}")
    token = random_token()
    current = now if now is not None else time.time()
    store.execute(
        "INSERT INTO invitations (token_hash, username, expires) VALUES (?, ?, ?)",
        (_digest(token), username, current + lifetime),
    )
    return token


def invitation_user(store: Store, token: str, *, now: float | None = None) -> str | None:
    """Whose invitation `token` is, if it is still unused and unexpired."""
    row = store.one(
        "SELECT username, expires, used FROM invitations WHERE token_hash = ?", (_digest(token),)
    )
    current = now if now is not None else time.time()
    if row is None or row["used"] or row["expires"] < current:
        return None
    user = get_user(store, row["username"])
    if user is None or user.disabled:
        return None
    return str(row["username"])


def use_invitation(store: Store, token: str, *, now: float | None = None) -> str:
    username = invitation_user(store, token, now=now)
    if username is None:
        raise AccountError("this invitation has expired or has already been used")
    store.execute("UPDATE invitations SET used = 1 WHERE token_hash = ?", (_digest(token),))
    return username


def accept_invitation(store: Store, token: str, password: str, *, now: float | None = None) -> str:
    """Set the invited person's password; returns their user name."""
    hash_password(password)  # refuse a short password before using up the invitation
    username = use_invitation(store, token, now=now)
    set_password(store, username, password)
    return username


# ---------------------------------------------------------------------------------- sign-in


def log_signin(
    store: Store, *, username: str, client: str, method: str, outcome: str, now: float
) -> None:
    store.execute(
        "INSERT INTO signins (ts, username, client, method, outcome) VALUES (?, ?, ?, ?, ?)",
        (now, username, client, method, outcome),
    )


def _locked(store: Store, column: str, value: str, limit: int, now: float) -> bool:
    last_success = store.one(
        f"SELECT MAX(ts) AS ts FROM signins WHERE {column} = ? AND outcome = 'success'",  # noqa: S608
        (value,),
    )
    since = max(now - FAILURE_WINDOW, (last_success["ts"] if last_success else None) or 0.0)
    row = store.one(
        f"SELECT COUNT(*) AS n, MAX(ts) AS last FROM signins "  # noqa: S608
        f"WHERE {column} = ? AND outcome IN ('failure', 'locked') AND ts > ?",
        (value, since),
    )
    if row is None or row["n"] < limit:
        return False
    return bool(now - row["last"] < LOCKOUT)


def is_locked_out(store: Store, *, username: str, client: str, now: float | None = None) -> bool:
    current = now if now is not None else time.time()
    return _locked(store, "username", username, MAX_FAILURES_PER_ACCOUNT, current) or _locked(
        store, "client", client, MAX_FAILURES_PER_CLIENT, current
    )


def sign_in(
    store: Store, username: str, password: str, *, client: str, now: float | None = None
) -> User:
    """Check a user name and password; the account, or `SignInRefused`. Always logged."""
    current = now if now is not None else time.time()
    name = username.strip().lower()
    if is_locked_out(store, username=name, client=client, now=current):
        log_signin(store, username=name, client=client, method="password", outcome="locked",
                   now=current)  # fmt: skip
        raise SignInRefused("locked")
    row = store.one("SELECT * FROM users WHERE username = ?", (name,))
    stored = row["password_hash"] if row is not None else None
    ok = False
    try:
        ok = _HASHER.verify(stored or _DUMMY_HASH, password) and stored is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        ok = False
    if not ok or row is None or row["disabled"]:
        log_signin(store, username=name, client=client, method="password", outcome="failure",
                   now=current)  # fmt: skip
        raise SignInRefused("invalid")
    if stored is not None and _HASHER.check_needs_rehash(stored):
        store.execute(
            "UPDATE users SET password_hash = ? WHERE username = ?", (_HASHER.hash(password), name)
        )
    log_signin(store, username=name, client=client, method="password", outcome="success",
               now=current)  # fmt: skip
    return _user(row)


def signin_log(store: Store, *, limit: int = 100) -> list[dict[str, object]]:
    rows = store.all("SELECT * FROM signins ORDER BY id DESC LIMIT ?", (limit,))
    return [dict(row) for row in rows]


# --------------------------------------------------------------------------------- sessions


def create_session(
    store: Store,
    username: str,
    *,
    hours: float,
    now: float | None = None,
) -> tuple[str, Session]:
    """A new session for `username`: the cookie value (returned once, never stored) and the
    session."""
    current = now if now is not None else time.time()
    token = random_token()
    session = Session(
        username=username, csrf=random_token(), created=current, expires=current + hours * 3600
    )
    store.execute(
        "INSERT INTO sessions (token_hash, username, csrf, created, last_seen, expires) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (_digest(token), username, session.csrf, current, current, session.expires),
    )
    return token, session


def session_for(
    store: Store, token: str | None, *, idle_minutes: float, now: float | None = None
) -> Session | None:
    """The live session `token` names, refreshing its last use; `None` if it has ended."""
    if not token:
        return None
    current = now if now is not None else time.time()
    digest = _digest(token)
    with store.connect() as db:
        row = db.execute(
            "SELECT s.*, u.disabled FROM sessions s JOIN users u ON u.username = s.username "
            "WHERE s.token_hash = ?",
            (digest,),
        ).fetchone()
        if row is None:
            return None
        if (
            row["disabled"]
            or row["expires"] <= current
            or (current - row["last_seen"] > idle_minutes * 60)
        ):
            db.execute("DELETE FROM sessions WHERE token_hash = ?", (digest,))
            return None
        db.execute("UPDATE sessions SET last_seen = ? WHERE token_hash = ?", (current, digest))
        return Session(
            username=row["username"], csrf=row["csrf"], created=row["created"],
            expires=row["expires"],
        )  # fmt: skip


def end_session(store: Store, token: str | None) -> None:
    if token:
        store.execute("DELETE FROM sessions WHERE token_hash = ?", (_digest(token),))


def csrf_matches(session: Session, submitted: str | None) -> bool:
    return submitted is not None and hmac.compare_digest(session.csrf, submitted)


# ------------------------------------------------------------------------------- API tokens


def create_api_token(store: Store, username: str, *, label: str, now: float | None = None) -> str:
    user = get_user(store, username)
    if user is None:
        raise AccountError(f"there is no account called {username!r}")
    if user.disabled:
        raise AccountError(f"the account {username!r} is disabled")
    token = "strata_" + random_token()
    store.execute(
        "INSERT INTO api_tokens (token_hash, username, label, created) VALUES (?, ?, ?, ?)",
        (_digest(token), username, label, now if now is not None else time.time()),
    )
    return token


def user_for_api_token(store: Store, token: str | None, *, now: float | None = None) -> str | None:
    if not token:
        return None
    digest = _digest(token)
    row = store.one(
        "SELECT t.username, u.disabled FROM api_tokens t JOIN users u ON u.username = t.username "
        "WHERE t.token_hash = ?",
        (digest,),
    )
    if row is None or row["disabled"]:
        return None
    store.execute(
        "UPDATE api_tokens SET last_used = ? WHERE token_hash = ?",
        (now if now is not None else time.time(), digest),
    )
    return str(row["username"])


def revoke_api_tokens(store: Store, username: str, *, label: str | None = None) -> int:
    if label is None:
        return store.execute("DELETE FROM api_tokens WHERE username = ?", (username,))
    return store.execute(
        "DELETE FROM api_tokens WHERE username = ? AND label = ?", (username, label)
    )
