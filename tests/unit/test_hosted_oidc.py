"""OpenID Connect and GitHub sign-in against a fake provider
(openspec:hosted-deployment#per-user-authentication)."""

# ruff: noqa: E501

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx2
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from strata.hosted import accounts
from strata.hosted.instance import Instance, OidcProvider
from strata.hosted.oidc import OidcClient, OidcError, link_identity, user_for_identity

ISSUER = "https://login.example.edu"
CLIENT_ID = "strata-instance"
REDIRECT = "https://strata.example.test/auth/university/callback"


class FakeProvider:
    """An OpenID Connect provider (or GitHub) answering over an httpx2 mock transport."""

    def __init__(self, *, kind: str = "oidc") -> None:
        self.kind = kind
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.claims: dict[str, Any] = {}
        self.nonce: str | None = None
        self.token_requests: list[dict[str, list[str]]] = []
        self.github_user = {"id": 4242, "login": "samok", "name": "Sam Okonkwo", "email": None}

    def jwk(self) -> dict[str, Any]:
        public = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(self.key.public_key()))
        return {**public, "kid": "k1", "alg": "RS256", "use": "sig"}

    def id_token(self, **overrides: Any) -> str:
        now = int(time.time())
        claims = {"iss": ISSUER, "aud": CLIENT_ID, "sub": "u-123", "iat": now, "exp": now + 300,
                  "nonce": self.nonce, "email": "sam@example.edu", "email_verified": True, "name": "Sam"}  # fmt: skip
        claims.update(self.claims)
        claims.update(overrides)
        return jwt.encode(claims, self.key, algorithm="RS256", headers={"kid": "k1"})

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        url = str(request.url)
        if url == f"{ISSUER}/.well-known/openid-configuration":
            return httpx2.Response(200, json={
                "issuer": ISSUER, "authorization_endpoint": f"{ISSUER}/authorize",
                "token_endpoint": f"{ISSUER}/token", "jwks_uri": f"{ISSUER}/jwks",
            })  # fmt: skip
        if url == f"{ISSUER}/jwks":
            return httpx2.Response(200, json={"keys": [self.jwk()]})
        if url in (f"{ISSUER}/token", "https://github.com/login/oauth/access_token"):
            form = parse_qs(request.content.decode())
            self.token_requests.append(form)
            if form.get("code") != ["good-code"]:
                return httpx2.Response(400, json={"error": "invalid_grant"})
            if self.kind == "github":
                return httpx2.Response(200, json={"access_token": "gho_x", "token_type": "bearer"})
            return httpx2.Response(200, json={"access_token": "at", "id_token": self.id_token()})
        if url == "https://api.github.com/user":
            assert request.headers["authorization"] == "Bearer gho_x"
            return httpx2.Response(200, json=self.github_user)
        return httpx2.Response(404)


def _instance(tmp_path: Path) -> Instance:
    instance = Instance(
        tmp_path / "data", environ={"STRATA_SECRET_OIDC_UNIVERSITY": "client-secret-value"}
    )
    instance.initialise(public_url="https://strata.example.test")
    return instance


def _client(instance: Instance, fake: FakeProvider, kind: str = "oidc") -> OidcClient:
    provider = OidcProvider(id="university", label="University", kind=kind, client_id=CLIENT_ID,
                            client_secret="oidc-university", issuer=ISSUER if kind == "oidc" else None)  # fmt: skip
    return OidcClient(
        instance,
        provider,
        redirect_uri=REDIRECT,
        http=httpx2.Client(transport=httpx2.MockTransport(fake.handler)),
    )


def _begin(client: OidcClient, fake: FakeProvider, **kwargs: Any) -> str:
    url = client.start(**kwargs)
    query = parse_qs(urlsplit(url).query)
    assert query["code_challenge_method"] == ["S256"] and query["redirect_uri"] == [REDIRECT]
    fake.nonce = query.get("nonce", [None])[0]
    return query["state"][0]


def test_an_oidc_sign_in_yields_the_providers_verified_identity(tmp_path: Path) -> None:
    fake = FakeProvider()
    client = _client(_instance(tmp_path), fake)
    state = _begin(client, fake)
    identity = client.finish(state=state, code="good-code")
    assert (identity.provider, identity.subject, identity.email) == (
        "university",
        "u-123",
        "sam@example.edu",
    )
    sent = fake.token_requests[0]
    assert sent["client_secret"] == ["client-secret-value"] and sent["code_verifier"]
    # The state is single use.
    with pytest.raises(OidcError, match="expired"):
        client.finish(state=state, code="good-code")


@pytest.mark.parametrize(
    ("claims", "message"),
    [
        ({"nonce": "someone-elses"}, "does not belong"),
        ({"aud": "another-client"}, "did not verify"),
        ({"iss": "https://evil.example"}, "did not verify"),
        ({"exp": int(time.time()) - 3600}, "did not verify"),
    ],
)
def test_an_id_token_that_is_not_for_this_sign_in_is_refused(
    tmp_path: Path, claims: dict[str, Any], message: str
) -> None:
    fake = FakeProvider()
    fake.claims = claims
    client = _client(_instance(tmp_path), fake)
    state = _begin(client, fake)
    with pytest.raises(OidcError, match=message):
        client.finish(state=state, code="good-code")


def test_an_unsigned_or_wrongly_signed_id_token_is_refused(tmp_path: Path) -> None:
    fake = FakeProvider()
    instance = _instance(tmp_path)
    client = _client(instance, fake)
    state = _begin(client, fake)
    unsigned = jwt.encode({"sub": "x", "iss": ISSUER, "aud": CLIENT_ID}, key=None, algorithm="none")
    with pytest.raises(OidcError, match="accepted algorithm"):
        client._oidc_identity({"id_token": unsigned}, "n", None)
    impostor = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    forged = jwt.encode({"sub": "x", "iss": ISSUER, "aud": CLIENT_ID, "iat": 1, "exp": 2**31, "nonce": "n"},
                        impostor, algorithm="RS256", headers={"kid": "k1"})  # fmt: skip
    with pytest.raises(OidcError, match="did not verify"):
        client._oidc_identity({"id_token": forged}, "n", None)
    with pytest.raises(OidcError, match="refused"):
        client.finish(state=state, code="bad-code")


def test_github_sign_in_uses_the_numeric_user_id(tmp_path: Path) -> None:
    fake = FakeProvider(kind="github")
    client = _client(_instance(tmp_path), fake, kind="github")
    state = _begin(client, fake)
    identity = client.finish(state=state, code="good-code")
    assert identity.subject == "4242" and identity.name == "Sam Okonkwo"


def test_a_missing_client_secret_is_reported_without_its_value(tmp_path: Path) -> None:
    fake = FakeProvider()
    instance = Instance(tmp_path / "data", environ={})
    instance.initialise()
    client = _client(instance, fake)
    state = _begin(client, fake)
    with pytest.raises(OidcError, match="client secret for University is not configured"):
        client.finish(state=state, code="good-code")


def test_identities_link_to_one_account_each(tmp_path: Path) -> None:
    instance = _instance(tmp_path)
    accounts.add_user(instance.store, "sam")
    accounts.add_user(instance.store, "other")
    link_identity(instance.store, provider="github", subject="4242", username="sam")
    assert user_for_identity(instance.store, provider="github", subject="4242") == "sam"
    assert user_for_identity(instance.store, provider="university", subject="4242") is None
    with pytest.raises(OidcError, match="already linked"):
        link_identity(instance.store, provider="github", subject="4242", username="other")
