"""What the hosted service layer refuses, and says, when it is given something it cannot use
(openspec:hosted-deployment)."""

# ruff: noqa: E501

from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx2
import jwt
import pytest

from strata.hosted import accounts
from strata.hosted.instance import (
    Instance,
    InstanceError,
    OidcProvider,
    check_remote_url,
    default_data_dir,
)
from strata.hosted.oidc import OidcClient, OidcError
from strata.hosted.secrets import SecretError, SecretStore, git_credential_env
from strata.hosted.store import Store
from strata.protocol import blinding
from tests.unit.test_hosted_oidc import CLIENT_ID, ISSUER, REDIRECT, FakeProvider

PASSWORD = "a long enough password"


@pytest.fixture
def store(tmp_path: Path) -> Store:
    s = Store(tmp_path / "instance.db")
    s.create()
    return s


# --------------------------------------------------------------------------------- accounts


def test_account_operations_name_an_account_that_does_not_exist(store: Store) -> None:
    for call in (
        lambda: accounts.set_password(store, "ghost", PASSWORD),
        lambda: accounts.disable_user(store, "ghost"),
        lambda: accounts.enable_user(store, "ghost"),
        lambda: accounts.create_invitation(store, "ghost"),
        lambda: accounts.create_api_token(store, "ghost", label="x"),
    ):
        with pytest.raises(accounts.AccountError, match="no account called 'ghost'"):
            call()


def test_a_disabled_account_gets_no_token_and_its_invitation_stops_working(store: Store) -> None:
    accounts.add_user(store, "sam")
    invitation = accounts.create_invitation(store, "sam", now=0.0)
    accounts.disable_user(store, "sam")
    assert accounts.invitation_user(store, invitation, now=1.0) is None
    with pytest.raises(accounts.AccountError, match="disabled"):
        accounts.create_api_token(store, "sam", label="mcp")


def test_an_old_hash_is_upgraded_at_the_next_sign_in(store: Store) -> None:
    from argon2 import PasswordHasher

    weak = PasswordHasher(time_cost=1, memory_cost=8192, parallelism=1).hash(PASSWORD)
    accounts.add_user(store, "sam")
    store.execute("UPDATE users SET password_hash = ? WHERE username = 'sam'", (weak,))
    accounts.sign_in(store, "sam", PASSWORD, client="c", now=1.0)
    upgraded = store.one("SELECT password_hash FROM users WHERE username = 'sam'")
    assert upgraded is not None and upgraded["password_hash"] != weak
    assert accounts.sign_in(store, "sam", PASSWORD, client="c", now=2.0).username == "sam"


# ---------------------------------------------------------------------------------- secrets


def test_without_an_instance_key_nothing_can_be_stored(tmp_path: Path, store: Store) -> None:
    secrets = SecretStore(store, tmp_path / "missing.key", environ={}, secrets_dir=tmp_path)
    with pytest.raises(SecretError, match="there is no instance key"):
        secrets.put("x", "value")
    broken = SecretStore(
        store, tmp_path / "k", environ={"STRATA_INSTANCE_KEY": "not-a-key"}, secrets_dir=tmp_path
    )
    with pytest.raises(SecretError, match="not a valid key"):
        broken.put("x", "value")


def test_an_unknown_credential_kind_is_refused(tmp_path: Path, store: Store) -> None:
    secrets = SecretStore(store, tmp_path / "k.key", environ={}, secrets_dir=tmp_path)
    secrets.ensure_key()
    secrets.put("cred", "value")
    with (
        pytest.raises(SecretError, match="unknown credential kind 'password'"),
        git_credential_env(
            secrets, kind="password", secret="cred", username=None, tmp_dir=tmp_path / "t"
        ),
    ):
        pass


# --------------------------------------------------------------------------------- instance


def test_remote_urls_and_settings_are_checked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(InstanceError, match="empty"):
        check_remote_url("  ")
    with pytest.raises(InstanceError, match="is not a remote URL"):
        check_remote_url("--upload-pack=evil")
    assert check_remote_url("git@github.com:lab/review.git") == "git@github.com:lab/review.git"
    monkeypatch.setenv("STRATA_DATA", str(tmp_path / "elsewhere"))
    assert default_data_dir() == tmp_path / "elsewhere"
    monkeypatch.delenv("STRATA_DATA")
    assert default_data_dir() == Path("/data")

    instance = Instance(tmp_path / "data", environ={})
    instance.initialise()
    instance.settings_path.write_text("public_url = [unclosed\n")
    with pytest.raises(InstanceError, match="not valid TOML"):
        _ = instance.settings
    instance._settings = None
    instance.settings_path.write_text('[[oidc]]\nid = "x"\nclient_id = "y"\n')
    with pytest.raises(InstanceError, match="has no 'client_secret'"):
        _ = instance.settings


def test_a_project_needs_a_whole_credential_with_a_remote(tmp_path: Path) -> None:
    instance = Instance(tmp_path / "data", environ={})
    with pytest.raises(InstanceError, match="strata host init"):
        instance.add_project("spacing", actor_handle="a", actor_name="A")
    instance.initialise()
    with pytest.raises(InstanceError, match="invalid project id"):
        instance.add_project("Spacing Review")
    with pytest.raises(InstanceError, match="both its kind and the name"):
        instance.add_project("spacing", remote="x", credential_kind="token")
    with pytest.raises(InstanceError, match="unknown credential kind"):
        instance.add_project("spacing", remote="x", credential_kind="basic", credential_secret="s")
    with pytest.raises(InstanceError, match="only used with a remote"):
        instance.add_project("spacing", credential_kind="token", credential_secret="s")
    with pytest.raises(InstanceError, match="could not clone"):
        instance.add_project("spacing", remote=str(tmp_path / "no-such-remote.git"))
    assert not (instance.projects_dir / "spacing").exists() and instance.list_projects() == []


# --------------------------------------------------------------------------------- blinding


def test_blinded_without_a_stage_means_at_any_stage() -> None:
    blinded = {"title-abstract": frozenset({"r1"}), "full-text": frozenset()}
    assert blinding.is_blinded(blinded, None, "r1")
    assert not blinding.is_blinded(blinded, None, "r2")
    assert not blinding.is_blinded(blinded, "title-abstract", None)


# ------------------------------------------------------------------------------------- OIDC


def _instance(tmp_path: Path) -> Instance:
    instance = Instance(tmp_path / "data", environ={"STRATA_SECRET_OIDC": "client-secret"})
    instance.initialise()
    return instance


def _client(tmp_path: Path, handler: Any, **provider: Any) -> OidcClient:
    settings = {"id": "u", "label": "University", "kind": "oidc", "client_id": CLIENT_ID,
                "client_secret": "oidc", "issuer": ISSUER, **provider}  # fmt: skip
    return OidcClient(_instance(tmp_path), OidcProvider(**settings), redirect_uri=REDIRECT,
                      http=httpx2.Client(transport=httpx2.MockTransport(handler)))  # fmt: skip


def _failing(
    *, discovery: Any = None, jwks: Any = None, token: Any = None, user: Any = None
) -> Any:
    """A provider handler where each endpoint can be swapped for a failing answer."""
    fake = FakeProvider()

    def handler(request: httpx2.Request) -> httpx2.Response:
        url = str(request.url)
        for suffix, override in (("openid-configuration", discovery), ("/jwks", jwks), ("/token", token),
                                 ("access_token", token), ("api.github.com/user", user)):  # fmt: skip
            if url.endswith(suffix) and override is not None:
                return override(request)  # type: ignore[no-any-return]
        return fake.handler(request)

    handler.fake = fake  # type: ignore[attr-defined]
    return handler


def _unreachable(request: httpx2.Request) -> httpx2.Response:
    raise httpx2.ConnectError("connection refused", request=request)


@pytest.mark.parametrize(
    ("provider", "handler", "message"),
    [
        ({"issuer": None}, _failing(), "has no issuer configured"),
        ({"kind": "saml"}, _failing(), "unknown provider kind"),
        (
            {},
            _failing(discovery=lambda r: httpx2.Response(200, json={"issuer": "https://other"})),
            "names a different issuer",
        ),
        ({}, _failing(discovery=_unreachable), "could not be reached"),
        ({}, _failing(discovery=lambda r: httpx2.Response(500)), "answered 500"),
        (
            {},
            _failing(discovery=lambda r: httpx2.Response(200, text="<html>")),
            "did not answer with JSON",
        ),
    ],
)
def test_a_provider_that_cannot_be_discovered_is_reported(
    tmp_path: Path, provider: dict[str, Any], handler: Any, message: str
) -> None:
    with pytest.raises(OidcError, match=message):
        _client(tmp_path, handler, **provider).start()


def _finish(client: OidcClient, handler: Any, code: str = "good-code") -> Any:
    query = parse_qs(urlsplit(client.start()).query)
    handler.fake.nonce = query.get("nonce", [None])[0]
    return client.finish(state=query["state"][0], code=code)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"token": _unreachable}, "could not be reached"),
        (
            {"token": lambda r: httpx2.Response(502, text="<html>bad gateway")},
            "refused the sign-in",
        ),
        ({"token": lambda r: httpx2.Response(200, json={"access_token": "x"})}, "sent no ID token"),
        ({"token": lambda r: httpx2.Response(200, json={"id_token": "not.a.jwt"})}, "malformed"),
        (
            {
                "jwks": lambda r: httpx2.Response(
                    200, json={"keys": [{"kid": "other", "kty": "RSA"}]}
                )
            },
            "does not publish",
        ),
    ],
)
def test_a_token_answer_that_cannot_be_used_is_refused(
    tmp_path: Path, overrides: dict[str, Any], message: str
) -> None:
    handler = _failing(**overrides)
    with pytest.raises(OidcError, match=message):
        _finish(_client(tmp_path, handler), handler)


def test_a_cancelled_sign_in_is_refused(tmp_path: Path) -> None:
    client = _client(tmp_path, _failing())
    with pytest.raises(OidcError, match="cancelled"):
        client.finish(state=None, code=None)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        (
            {"token": lambda r: httpx2.Response(200, json={"token_type": "bearer"})},
            "GitHub sent no access token",
        ),
        (
            {"user": lambda r: httpx2.Response(200, json={"login": "who"})},
            "did not say who signed in",
        ),
    ],
)
def test_github_answers_that_name_nobody_are_refused(
    tmp_path: Path, overrides: dict[str, Any], message: str
) -> None:
    handler = _failing(**overrides)
    handler.fake.kind = "github"
    with pytest.raises(OidcError, match=message):
        _finish(_client(tmp_path, handler, kind="github", issuer=None), handler)


def test_the_id_token_header_must_be_readable(tmp_path: Path) -> None:
    assert jwt  # the header check runs before any key is fetched
    client = _client(tmp_path, _failing())
    with pytest.raises(OidcError, match="malformed"):
        client._oidc_identity({"id_token": "garbage"}, "n", None)
