"""Local accounts, sign-in, sessions and API tokens (openspec:hosted-deployment#per-user-authentication,
#hosted-security-baseline)."""

# ruff: noqa: E501

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from strata.hosted import accounts
from strata.hosted.store import Store

PASSWORD = "a long enough password"


@pytest.fixture
def store(tmp_path: Path) -> Store:
    s = Store(tmp_path / "instance.db")
    s.create()
    return s


def test_passwords_are_argon2id_hashes_never_plaintext(store: Store, tmp_path: Path) -> None:
    accounts.add_user(store, "sam", password=PASSWORD, now=1.0)
    row = store.one("SELECT password_hash FROM users WHERE username = 'sam'")
    assert row is not None and row["password_hash"].startswith("$argon2id$v=19$m=65536")
    assert PASSWORD.encode() not in (tmp_path / "instance.db").read_bytes()
    if sys.platform != "win32":  # POSIX permissions; Windows has no such mode bits
        assert oct((tmp_path / "instance.db").stat().st_mode & 0o777) == "0o600"


def test_short_passwords_and_bad_user_names_are_refused(store: Store) -> None:
    with pytest.raises(accounts.AccountError, match="at least 12"):
        accounts.add_user(store, "sam", password="short")
    with pytest.raises(accounts.AccountError, match="invalid user name"):
        accounts.add_user(store, "Sam Smith", password=PASSWORD)
    accounts.add_user(store, "sam", password=PASSWORD)
    with pytest.raises(accounts.AccountError, match="already an account"):
        accounts.add_user(store, "sam", password=PASSWORD)


def test_sign_in_says_the_same_for_a_wrong_password_and_an_unknown_account(store: Store) -> None:
    accounts.add_user(store, "sam", password=PASSWORD)
    assert accounts.sign_in(store, "sam", PASSWORD, client="1.2.3.4", now=10.0).username == "sam"
    with pytest.raises(accounts.SignInRefused) as wrong:
        accounts.sign_in(store, "sam", "not the password", client="1.2.3.4", now=11.0)
    with pytest.raises(accounts.SignInRefused) as unknown:
        accounts.sign_in(store, "nobody", PASSWORD, client="1.2.3.4", now=12.0)
    assert str(wrong.value) == str(unknown.value)
    log = accounts.signin_log(store)
    assert [(r["username"], r["outcome"]) for r in log] == [
        ("nobody", "failure"),
        ("sam", "failure"),
        ("sam", "success"),
    ]


def test_an_account_with_no_password_cannot_sign_in_with_one(store: Store) -> None:
    accounts.add_user(store, "invited")
    with pytest.raises(accounts.SignInRefused):
        accounts.sign_in(store, "invited", "strata-dummy-password-for-timing", client="c", now=1.0)


def test_failed_sign_ins_lock_the_account_for_a_cooling_off_period(store: Store) -> None:
    accounts.add_user(store, "sam", password=PASSWORD)
    now = 1000.0
    for i in range(accounts.MAX_FAILURES_PER_ACCOUNT):
        with pytest.raises(accounts.SignInRefused):
            accounts.sign_in(store, "sam", "wrong password", client=f"client-{i}", now=now + i)
    with pytest.raises(accounts.SignInRefused) as locked:
        accounts.sign_in(store, "sam", PASSWORD, client="elsewhere", now=now + 10)
    assert locked.value.reason == "locked"
    later = now + 10 + accounts.LOCKOUT
    assert accounts.sign_in(store, "sam", PASSWORD, client="elsewhere", now=later).username == "sam"
    # A success clears the count.
    with pytest.raises(accounts.SignInRefused) as again:
        accounts.sign_in(store, "sam", "wrong password", client="x", now=later + 1)
    assert again.value.reason == "invalid"


def test_one_client_guessing_many_accounts_is_limited_too(store: Store) -> None:
    for i in range(accounts.MAX_FAILURES_PER_CLIENT):
        with pytest.raises(accounts.SignInRefused):
            accounts.sign_in(store, f"user{i}", "guess", client="10.0.0.9", now=100.0 + i)
    accounts.add_user(store, "sam", password=PASSWORD)
    with pytest.raises(accounts.SignInRefused) as locked:
        accounts.sign_in(store, "sam", PASSWORD, client="10.0.0.9", now=200.0)
    assert locked.value.reason == "locked"
    assert accounts.sign_in(store, "sam", PASSWORD, client="10.0.0.10", now=200.0).username == "sam"


def test_sessions_expire_when_idle_and_at_their_lifetime(store: Store) -> None:
    accounts.add_user(store, "sam", password=PASSWORD)
    token, session = accounts.create_session(store, "sam", hours=1, now=0.0)
    assert store.one("SELECT 1 FROM sessions WHERE token_hash = ?", (token,)) is None  # only a hash
    assert accounts.session_for(store, token, idle_minutes=10, now=300.0) == session
    assert accounts.session_for(store, token, idle_minutes=10, now=300.0 + 601) is None
    token, _ = accounts.create_session(store, "sam", hours=1, now=0.0)
    for minute in range(1, 60, 5):
        assert accounts.session_for(store, token, idle_minutes=10, now=minute * 60.0) is not None
    assert accounts.session_for(store, token, idle_minutes=10, now=3600.0) is None
    assert accounts.session_for(store, "made-up", idle_minutes=10, now=1.0) is None


def test_disabling_an_account_ends_its_sessions_and_tokens(store: Store) -> None:
    accounts.add_user(store, "sam", password=PASSWORD)
    token, _ = accounts.create_session(store, "sam", hours=1, now=0.0)
    api = accounts.create_api_token(store, "sam", label="mcp", now=0.0)
    accounts.disable_user(store, "sam")
    assert accounts.session_for(store, token, idle_minutes=10, now=1.0) is None
    assert accounts.user_for_api_token(store, api) is None
    with pytest.raises(accounts.SignInRefused):
        accounts.sign_in(store, "sam", PASSWORD, client="c", now=2.0)
    accounts.enable_user(store, "sam")
    assert accounts.sign_in(store, "sam", PASSWORD, client="c", now=3.0).username == "sam"


def test_invitations_are_single_use_and_expire(store: Store) -> None:
    accounts.add_user(store, "priya")
    token = accounts.create_invitation(store, "priya", now=0.0)
    assert accounts.invitation_user(store, token, now=1.0) == "priya"
    with pytest.raises(accounts.AccountError, match="at least"):
        accounts.accept_invitation(store, token, "short", now=1.0)
    assert accounts.invitation_user(store, token, now=1.0) == "priya"  # not used up by that
    assert accounts.accept_invitation(store, token, PASSWORD, now=2.0) == "priya"
    with pytest.raises(accounts.AccountError, match="expired or has already been used"):
        accounts.accept_invitation(store, token, PASSWORD, now=3.0)
    late = accounts.create_invitation(store, "priya", now=0.0)
    assert accounts.invitation_user(store, late, now=accounts.INVITATION_LIFETIME + 1) is None


def test_api_tokens_are_stored_hashed_and_revocable(store: Store, tmp_path: Path) -> None:
    accounts.add_user(store, "sam", password=PASSWORD)
    token = accounts.create_api_token(store, "sam", label="laptop", now=0.0)
    assert token.startswith("strata_")
    assert token.encode() not in (tmp_path / "instance.db").read_bytes()
    assert accounts.user_for_api_token(store, token) == "sam"
    assert accounts.user_for_api_token(store, None) is None
    assert accounts.revoke_api_tokens(store, "sam", label="laptop") == 1
    assert accounts.user_for_api_token(store, token) is None
