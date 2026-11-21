"""A signed-in person changes their own password, with the current one, and their other sessions
end (openspec:hosted-deployment#per-user-authentication; tasks 4.9 and 4.14)."""

# ruff: noqa: E501

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from strata.hosted import accounts
from tests.integration._hosted import PASSWORD, csrf_from, hosted, sign_in

NEW = "a much better password"


def _change(
    client: TestClient,
    current: str,
    new: str,
    *,
    confirm: str | None = None,
    csrf: str | None = None,
):  # type: ignore[no-untyped-def]
    page = client.get("/account/password")
    assert page.status_code == 200, page.text
    return client.post(
        "/account/password",
        data={
            "csrf_token": csrf or csrf_from(page.text),
            "current_password": current,
            "new_password": new,
            "confirm_password": new if confirm is None else confirm,
        },
    )


def _can_sign_in(h, password: str, username: str = "sam.okonkwo") -> bool:  # type: ignore[no-untyped-def]
    client = h.client()
    page = client.get("/signin")
    response = client.post(
        "/signin",
        data={"csrf_token": csrf_from(page.text), "username": username, "password": password},
    )
    return bool(response.status_code == 303)


def test_the_form_needs_a_session_and_is_linked_from_every_page(tmp_path: Path) -> None:
    h = hosted(tmp_path)
    assert h.client().get("/account/password").status_code == 303
    assert h.client().post("/account/password", data={}).status_code in (401, 403, 303)
    sam = sign_in(h.client(), "sam.okonkwo")
    assert 'href="/account/password"' in sam.get("/").text


def test_a_person_changes_their_password_with_the_current_one_and_other_sessions_end(
    tmp_path: Path,
) -> None:
    h = hosted(tmp_path)
    here = sign_in(h.client(), "sam.okonkwo")
    elsewhere = sign_in(h.client(), "sam.okonkwo")
    also_elsewhere = sign_in(h.client(), "sam.okonkwo")
    someone_else = sign_in(h.client(), "olive")
    assert elsewhere.get("/").status_code == 200

    changed = _change(here, PASSWORD, NEW)

    assert changed.status_code == 303
    assert here.get("/").status_code == 200  # the person who changed it stays signed in
    assert elsewhere.get("/").status_code == 303  # every other session of theirs is over
    assert also_elsewhere.get("/p/spacing/").status_code == 303
    assert someone_else.get("/").status_code == 200  # nobody else's is touched
    assert not _can_sign_in(h, PASSWORD) and _can_sign_in(h, NEW)
    log = accounts.signin_log(h.instance.store)
    assert any(
        r["method"] == "password-change"
        and r["outcome"] == "success"
        and r["username"] == "sam.okonkwo"
        for r in log
    )
    assert "was changed" in here.get("/account/password?changed=1").text


def test_the_new_password_is_stored_as_argon2id_and_never_in_the_clear(tmp_path: Path) -> None:
    h = hosted(tmp_path)
    _change(sign_in(h.client(), "sam.okonkwo"), PASSWORD, NEW)
    row = h.instance.store.one("SELECT password_hash FROM users WHERE username = 'sam.okonkwo'")
    assert row is not None and row["password_hash"].startswith("$argon2id$")
    assert NEW.encode() not in (h.instance.state_dir / "instance.db").read_bytes()


def test_a_wrong_current_password_changes_nothing_and_says_what_to_do(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING, logger="strata.hosted")
    h = hosted(tmp_path)
    here = sign_in(h.client(), "sam.okonkwo")
    elsewhere = sign_in(h.client(), "sam.okonkwo")

    refused = _change(here, "not my password", NEW)

    assert refused.status_code == 401
    text = refused.text
    assert "current password" in text and "not right" in text  # what was refused, and why
    assert "not changed" in text  # what happened
    assert "administrator" in text and "invitation" in text  # what fixes a forgotten one
    assert _can_sign_in(h, PASSWORD) and not _can_sign_in(h, NEW)
    assert elsewhere.get("/").status_code == 200
    assert any(
        r["method"] == "password-change" and r["outcome"] == "failure"
        for r in accounts.signin_log(h.instance.store)
    )
    assert "current password" in caplog.text and "sam.okonkwo" in caplog.text  # in the log too
    assert "not my password" not in caplog.text and NEW not in caplog.text


def test_guessing_the_current_password_from_a_stolen_session_is_cooled_off(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING, logger="strata.hosted")
    h = hosted(tmp_path)
    thief = sign_in(h.client(), "sam.okonkwo")
    h.clock.advance(1)  # the guesses come after the sign-in, as they would in real time
    for _ in range(accounts.MAX_FAILURES_PER_ACCOUNT):
        assert _change(thief, "a guess at it", NEW).status_code == 401

    refused = _change(thief, PASSWORD, NEW)  # even the right one is not tried now

    assert refused.status_code == 429
    assert "Too many" in refused.text and "wait" in refused.text.lower()
    assert "Too many" in caplog.text
    # The guesses count against the account's sign-in limit, so the account is cooled off as a whole;
    # another person's account is not.
    assert not _can_sign_in(h, PASSWORD)
    assert _can_sign_in(h, PASSWORD, "olive")
    h.clock.advance(accounts.LOCKOUT + 1)
    assert _change(thief, PASSWORD, NEW).status_code == 303


def test_a_new_password_that_is_too_short_or_mistyped_is_refused_in_plain_words(
    tmp_path: Path,
) -> None:
    h = hosted(tmp_path)
    here = sign_in(h.client(), "sam.okonkwo")

    short = _change(here, PASSWORD, "short")
    assert short.status_code == 422
    assert "at least 12 characters" in short.text and "not changed" in short.text
    assert "longer" in short.text  # what fixes it

    mistyped = _change(here, PASSWORD, NEW, confirm="a different password")
    assert mistyped.status_code == 422
    assert "different" in mistyped.text and "not changed" in mistyped.text
    assert "same" in mistyped.text  # what fixes it
    assert _can_sign_in(h, PASSWORD)


def test_changing_a_password_needs_the_sessions_csrf_token(tmp_path: Path) -> None:
    h = hosted(tmp_path)
    here = sign_in(h.client(), "sam.okonkwo")
    refused = _change(here, PASSWORD, NEW, csrf="not-the-token")
    assert refused.status_code == 403
    assert _can_sign_in(h, PASSWORD) and not _can_sign_in(h, NEW)


def test_an_account_with_no_password_is_told_why_and_what_to_ask_for(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING, logger="strata.hosted")
    h = hosted(tmp_path)
    accounts.add_user(h.instance.store, "provider.only", display_name="Provider Only")
    token, _session = accounts.create_session(
        h.instance.store, "provider.only", hours=1, now=h.clock()
    )
    client = h.client()
    client.cookies.set(h.server.session_cookie, token)

    page = client.get("/account/password")
    assert page.status_code == 200
    refused = client.post(
        "/account/password",
        data={
            "csrf_token": csrf_from(page.text),
            "current_password": "",
            "new_password": NEW,
            "confirm_password": NEW,
        },
    )

    assert refused.status_code == 422
    assert "no password" in refused.text and "another provider" in refused.text
    assert "administrator" in refused.text and "invitation" in refused.text
    assert "no password" in caplog.text
    assert accounts.get_user(h.instance.store, "provider.only").has_password is False  # type: ignore[union-attr]
