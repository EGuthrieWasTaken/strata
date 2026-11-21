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
  (openspec:hosted-deployment#remote-mcp-access); stored hashed like sessions. A token names one
  project and expires (90 days unless asked otherwise, 365 at most), so a leaked one reads one
  review for a while rather than every review its owner is in, for ever. Tokens made before that,
  which name no project and never expire, are expired by the upgrade that adds the columns
  (`Store.upgrade`), and are refused as expired here wherever one is found.

Disabled accounts cannot sign in and lose their sessions and tokens at once.
"""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import re
import sqlite3
import time
from dataclasses import dataclass

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from strata.hosted import audit
from strata.hosted.secrets import random_token
from strata.hosted.store import Store

USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
MIN_PASSWORD_LENGTH = 12

MAX_FAILURES_PER_ACCOUNT = 5
MAX_FAILURES_PER_CLIENT = 20
FAILURE_WINDOW = 15 * 60.0
LOCKOUT = 15 * 60.0
INVITATION_LIFETIME = 7 * 24 * 3600.0
DEFAULT_TOKEN_DAYS = 90
#: The longest an API token may last, however long the operator asks for. A token that leaks stops
#: working within a year at most, and a client's owner asks for a new one.
MAX_TOKEN_DAYS = 365

_HASHER = PasswordHasher()  # Argon2id
#: Verified against when the account does not exist, so a missing account takes as long to
#: refuse as a wrong password and the timing does not say which accounts exist.
_DUMMY_HASH = _HASHER.hash("strata-dummy-password-for-timing")


class AccountError(ValueError):
    pass


class IdentityAlreadyLinked(AccountError):
    """A provider identity that is linked to another account was offered with an invitation, so
    the invitation was left unused."""

    def __init__(self, provider: str, subject: str) -> None:
        self.provider = provider
        self.subject = subject
        super().__init__("that sign-in is already linked to another account")


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


class PasswordChangeRefused(Exception):
    """A change of password that was not made. `reason` is `locked`, `no-password`,
    `wrong-current` or `too-short`; the message says, in plain words, what was refused, why and
    what to do, and is what the person is shown and what the log records."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        messages = {
            "locked": (
                "Too many wrong passwords were tried for this account, so your password was not "
                "changed. Wait a few minutes and try again."
            ),
            "no-password": (
                "This account has no password here (it signs in through another provider), so "
                "there is no password to change. If you want one as well, ask an administrator "
                "of this instance for an invitation link."
            ),
            "wrong-current": (
                "The current password you gave is not right, so your password was not changed "
                "and your other sessions are still signed in. Try again, or if you have "
                "forgotten it, ask an administrator of this instance for a new invitation link."
            ),
            "too-short": (
                f"The new password must be at least {MIN_PASSWORD_LENGTH} characters, so your "
                "password was not changed. Choose a longer one."
            ),
        }
        super().__init__(messages[reason])


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
    """Set an account's password and end its sessions: whoever was signed in with the old one is
    signed out."""
    hashed = hash_password(password)
    with store.connect() as db:
        if not db.execute(
            "UPDATE users SET password_hash = ? WHERE username = ?", (hashed, username)
        ).rowcount:
            raise AccountError(f"there is no account called {username!r}")
        db.execute("DELETE FROM sessions WHERE username = ?", (username,))


def change_password(
    store: Store,
    username: str,
    current: str,
    new: str,
    *,
    keep_session: str | None,
    client: str,
    now: float | None = None,
) -> int:
    """Change `username`'s own password: it needs the current one, and ends every session of theirs
    except `keep_session` (the cookie value of the one they are using); how many it ended.

    Guessing the current password from a stolen session is what the check is for, so each wrong
    attempt is logged and counts against the same limits as a wrong password at sign-in
    (`is_locked_out`): after too many, the change is refused without looking at the password.
    """
    current_time = now if now is not None else time.time()

    def log(outcome: str) -> None:
        log_signin(
            store, username=username, client=client, method="password-change", outcome=outcome,
            now=current_time,
        )  # fmt: skip

    if is_locked_out(store, username=username, client=client, now=current_time):
        log("locked")
        raise PasswordChangeRefused("locked")
    row = store.one("SELECT password_hash FROM users WHERE username = ?", (username,))
    stored = row["password_hash"] if row is not None else None
    if stored is None:
        raise PasswordChangeRefused("no-password")
    right: bool = False
    with contextlib.suppress(VerifyMismatchError, VerificationError, InvalidHashError):
        right = _HASHER.verify(stored, current)
    if not right:
        log("failure")
        raise PasswordChangeRefused("wrong-current")
    if len(new) < MIN_PASSWORD_LENGTH:
        raise PasswordChangeRefused("too-short")
    hashed = hash_password(new)
    with store.connect() as db:
        db.execute("UPDATE users SET password_hash = ? WHERE username = ?", (hashed, username))
        ended = db.execute(
            "DELETE FROM sessions WHERE username = ? AND token_hash != ?",
            (username, _digest(keep_session) if keep_session else ""),
        ).rowcount
    log("success")
    return ended


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


def use_invitation(
    store: Store,
    token: str,
    *,
    now: float | None = None,
    identity: tuple[str, str] | None = None,
) -> str:
    """Use an invitation up; its user name. Two requests with the same token cannot both use it:
    the update that marks it used is also the check that it was not.

    `identity` is a sign-in provider's `(provider, subject)` the person is accepting the invitation
    with. It is linked to the invited account in the same transaction as the invitation is used,
    and only if no *other* account has it already: when one does, `IdentityAlreadyLinked` is
    raised and the invitation is left unused, so the person can try again with another identity
    rather than needing a new invitation.
    """
    current = now if now is not None else time.time()
    digest = _digest(token)
    expired = AccountError("this invitation has expired or has already been used")
    with store.connect() as db:
        row = db.execute(
            "SELECT i.username, i.expires, i.used, u.disabled FROM invitations i "
            "LEFT JOIN users u ON u.username = i.username WHERE i.token_hash = ?",
            (digest,),
        ).fetchone()
        if row is None or row["used"] or row["expires"] < current or row["disabled"] != 0:
            raise expired
        username = str(row["username"])
        if identity is not None:
            linked = db.execute(
                "SELECT username FROM identities WHERE provider = ? AND subject = ?", identity
            ).fetchone()
            if linked is not None and linked["username"] != username:
                raise IdentityAlreadyLinked(*identity)
        if not db.execute(
            "UPDATE invitations SET used = 1 WHERE token_hash = ? AND used = 0 AND expires >= ?",
            (digest, current),
        ).rowcount:
            raise expired
        if identity is not None:
            db.execute(
                "INSERT OR REPLACE INTO identities (provider, subject, username) VALUES (?, ?, ?)",
                (*identity, username),
            )
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


@dataclass(frozen=True)
class ApiToken:
    """What the instance knows about a token it was shown that still works: whose it is, the one
    project it reads, and when it stops. A token made before tokens named a project and expired has
    neither, and is refused (`api_token`) rather than described."""

    username: str
    label: str
    project: str
    created: float
    expires: float


class TokenExpired(Exception):
    """The token was made by this instance but has passed its expiry."""

    def __init__(self, expires: float) -> None:
        self.expires = expires
        super().__init__("this API token has expired")


def _plural(count: float, noun: str) -> str:
    return f"{count:g} {noun}" + ("" if count == 1 else "s")


def create_api_token(
    store: Store,
    username: str,
    *,
    label: str,
    project: str,
    by: str,
    days: float = DEFAULT_TOKEN_DAYS,
    now: float | None = None,
) -> str:
    """A token for `username` that reads `project` and expires after `days` (from one to
    `MAX_TOKEN_DAYS`); returned once and stored only as a hash. The creation is written to the audit
    log, as `by`."""
    if not days >= 1:  # also a length that is not a number
        raise AccountError(
            f"a token must last at least one day, not {days:g}: ask for a longer one "
            "(for example --days 1, or leave --days out for "
            f"{_plural(DEFAULT_TOKEN_DAYS, 'day')})"
        )
    if days > MAX_TOKEN_DAYS:
        raise AccountError(
            f"a token can last at most {_plural(MAX_TOKEN_DAYS, 'day')}, not "
            f"{_plural(days, 'day')}: ask for a shorter one (for example --days {MAX_TOKEN_DAYS}, "
            f"or leave --days out for {_plural(DEFAULT_TOKEN_DAYS, 'day')}) and make a new one "
            "when it expires"
        )
    user = get_user(store, username)
    if user is None:
        raise AccountError(f"there is no account called {username!r}")
    if user.disabled:
        raise AccountError(f"the account {username!r} is disabled")
    token = "strata_" + random_token()
    current = now if now is not None else time.time()
    expires = current + days * 24 * 3600
    until = time.strftime("%Y-%m-%d", time.gmtime(expires))
    with store.connect() as db:
        db.execute(
            "INSERT INTO api_tokens (token_hash, username, label, created, project, expires) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (_digest(token), username, label, current, project, expires),
        )
        audit.record(
            db, by=by, action=audit.TOKEN_CREATE, project=project, subject=username, now=current,
            detail=f"token {label!r} for {project}, valid {_plural(days, 'day')} (until {until})",
        )  # fmt: skip
    return token


def api_token(store: Store, token: str | None, *, now: float | None = None) -> ApiToken | None:
    """The token `token` is, if it is one this instance made and its account is enabled; `None`
    if not. An expired one raises `TokenExpired`, so a client can be told why it was refused."""
    if not token:
        return None
    digest = _digest(token)
    current = now if now is not None else time.time()
    row = store.one(
        "SELECT t.username, t.label, t.project, t.created, t.expires, u.disabled "
        "FROM api_tokens t JOIN users u ON u.username = t.username WHERE t.token_hash = ?",
        (digest,),
    )
    if row is None or row["disabled"]:
        return None
    project, expires = row["project"], row["expires"]
    if project is None or expires is None:
        # Made before tokens named a project and expired. The upgrade ends these, so one found
        # here slipped past it (or was written by hand): refuse it rather than believe it reads
        # every project its owner is in and never stops.
        raise TokenExpired(current if expires is None else min(expires, current))
    if expires <= current:
        raise TokenExpired(expires)
    store.execute("UPDATE api_tokens SET last_used = ? WHERE token_hash = ?", (current, digest))
    return ApiToken(
        username=row["username"],
        label=row["label"],
        project=project,
        created=row["created"],
        expires=expires,
    )


def revoke_api_tokens(
    store: Store,
    username: str,
    *,
    by: str,
    label: str | None = None,
    now: float | None = None,
) -> int:
    """Revoke `username`'s tokens (those with `label`, or all); how many. Written to the audit
    log, as `by`, when there were any."""
    with store.connect() as db:
        if label is None:
            count = db.execute("DELETE FROM api_tokens WHERE username = ?", (username,)).rowcount
        else:
            count = db.execute(
                "DELETE FROM api_tokens WHERE username = ? AND label = ?", (username, label)
            ).rowcount
        if count:
            which = f" labelled {label!r}" if label is not None else ""
            audit.record(
                db, by=by, action=audit.TOKEN_REVOKE, subject=username, now=now,
                detail=f"revoked {_plural(count, 'token')}{which}",
            )  # fmt: skip
    return count
