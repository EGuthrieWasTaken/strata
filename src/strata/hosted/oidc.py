"""Optional OpenID Connect sign-in: openspec:hosted-deployment#per-user-authentication.

Local accounts need nothing external; an operator may also configure providers in
`instance.toml`:

```toml
[[oidc]]
id = "university"                       # appears in the sign-in URL
label = "University sign-in"
kind = "oidc"                           # discovery from the issuer
issuer = "https://login.example.edu"
client_id = "strata"
client_secret = "oidc-university"       # the NAME of a secret (strata.hosted.secrets)

[[oidc]]
id = "github"
kind = "github"                         # GitHub's OAuth, which is not OpenID Connect proper
client_id = "Iv1.0123456789abcdef"
client_secret = "oidc-github"
```

The flow is the authorization-code flow with PKCE (S256), a random `state` and, for OpenID
Connect, a `nonce`. An OpenID Connect ID token is verified against the provider's published keys
(signature, issuer, audience, expiry, nonce); GitHub's user is read from its API with the access
token. The client secret is read from the instance's secrets when it is needed and never shown.

A provider identity (provider, subject) signs in the account it is *linked* to. It is linked when
an invited person accepts their invitation by signing in with the provider, so a stranger with an
account at the same provider cannot sign in, and a renamed GitHub login keeps working (the
subject is GitHub's numeric user id, not the login).
"""

from __future__ import annotations

import base64
import hashlib
import secrets as secrets_lib
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx2
import jwt

from strata.hosted.instance import Instance, OidcProvider
from strata.hosted.store import Store

FLOW_LIFETIME = 10 * 60.0
_ASYMMETRIC_ALGORITHMS = ("RS256", "RS384", "RS512", "PS256", "PS384", "PS512", "ES256",
                          "ES384", "ES512", "EdDSA")  # fmt: skip

GITHUB_ENDPOINTS = {
    "authorization_endpoint": "https://github.com/login/oauth/authorize",
    "token_endpoint": "https://github.com/login/oauth/access_token",
    "userinfo_endpoint": "https://api.github.com/user",
}


class OidcError(Exception):
    """The sign-in with a provider did not complete; the message is safe to show."""


@dataclass(frozen=True)
class Identity:
    provider: str
    subject: str
    email: str | None
    name: str | None
    #: The invitation the person started from, when they are accepting one.
    invitation: str | None


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def link_identity(store: Store, *, provider: str, subject: str, username: str) -> None:
    taken = user_for_identity(store, provider=provider, subject=subject)
    if taken is not None and taken != username:
        raise OidcError("that sign-in is already linked to another account")
    store.execute(
        "INSERT OR REPLACE INTO identities (provider, subject, username) VALUES (?, ?, ?)",
        (provider, subject, username),
    )


def user_for_identity(store: Store, *, provider: str, subject: str) -> str | None:
    row = store.one(
        "SELECT username FROM identities WHERE provider = ? AND subject = ?", (provider, subject)
    )
    return str(row["username"]) if row is not None else None


class OidcClient:
    """Sign-in with one configured provider."""

    def __init__(
        self,
        instance: Instance,
        provider: OidcProvider,
        *,
        redirect_uri: str,
        http: httpx2.Client | None = None,
        clock: Any = time.time,
    ) -> None:
        self.instance = instance
        self.provider = provider
        self.redirect_uri = redirect_uri
        self._http = http or httpx2.Client(timeout=15.0, follow_redirects=False)
        self._clock = clock
        self._metadata: dict[str, Any] | None = None

    def metadata(self) -> dict[str, Any]:
        if self._metadata is None:
            if self.provider.kind == "github":
                self._metadata = dict(GITHUB_ENDPOINTS)
            elif self.provider.kind == "oidc":
                if not self.provider.issuer:
                    raise OidcError(f"the provider {self.provider.id!r} has no issuer configured")
                url = self.provider.issuer.rstrip("/") + "/.well-known/openid-configuration"
                self._metadata = self._get_json(url)
                if self._metadata.get("issuer") != self.provider.issuer:
                    raise OidcError("the provider's discovery document names a different issuer")
            else:
                raise OidcError(f"unknown provider kind {self.provider.kind!r}")
        return self._metadata

    def _get_json(self, url: str, **kwargs: Any) -> dict[str, Any]:
        try:
            response = self._http.get(url, **kwargs)
        except httpx2.HTTPError as exc:
            raise OidcError(f"the sign-in provider could not be reached: {exc}") from None
        if response.status_code != 200:
            raise OidcError(f"the sign-in provider answered {response.status_code}")
        try:
            data: dict[str, Any] = response.json()
        except ValueError:
            raise OidcError("the sign-in provider did not answer with JSON") from None
        return data

    def _client_secret(self) -> str:
        value = self.instance.secrets.get(self.provider.client_secret)
        if not value:
            raise OidcError(
                f"the client secret for {self.provider.label} is not configured on this instance"
            )
        return value

    # -- the flow --------------------------------------------------------------------------

    def start(self, *, invitation: str | None = None) -> str:
        """Begin a sign-in; the URL to send the browser to."""
        state = secrets_lib.token_urlsafe(32)
        nonce = secrets_lib.token_urlsafe(32)
        verifier = secrets_lib.token_urlsafe(48)
        now = self._clock()
        store = self.instance.store
        store.execute("DELETE FROM oidc_flows WHERE created < ?", (now - FLOW_LIFETIME,))
        store.execute(
            "INSERT INTO oidc_flows (state, provider, nonce, verifier, invitation, created) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (state, self.provider.id, nonce, verifier, invitation, now),
        )
        params = {
            "response_type": "code",
            "client_id": self.provider.client_id,
            "redirect_uri": self.redirect_uri,
            "scope": "read:user user:email" if self.provider.kind == "github" else (
                self.provider.scopes
            ),
            "state": state,
            "code_challenge": _b64(hashlib.sha256(verifier.encode("ascii")).digest()),
            "code_challenge_method": "S256",
        }  # fmt: skip
        if self.provider.kind == "oidc":
            params["nonce"] = nonce
        return str(self.metadata()["authorization_endpoint"]) + "?" + urlencode(params)

    def finish(self, *, state: str | None, code: str | None) -> Identity:
        """Complete a sign-in from the provider's redirect back."""
        if not state or not code:
            raise OidcError("the sign-in was cancelled or the provider sent nothing back")
        store = self.instance.store
        with store.connect() as db:
            row = db.execute(
                "SELECT * FROM oidc_flows WHERE state = ? AND provider = ?",
                (state, self.provider.id),
            ).fetchone()
            db.execute("DELETE FROM oidc_flows WHERE state = ?", (state,))
        if row is None or self._clock() - row["created"] > FLOW_LIFETIME:
            raise OidcError("this sign-in has expired; start again")
        tokens = self._exchange(code, row["verifier"])
        if self.provider.kind == "github":
            return self._github_identity(tokens, row["invitation"])
        return self._oidc_identity(tokens, row["nonce"], row["invitation"])

    def _exchange(self, code: str, verifier: str) -> dict[str, Any]:
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.redirect_uri,
            "client_id": self.provider.client_id,
            "client_secret": self._client_secret(),
            "code_verifier": verifier,
        }
        try:
            response = self._http.post(
                str(self.metadata()["token_endpoint"]),
                data=data,
                headers={"Accept": "application/json"},
            )
        except httpx2.HTTPError as exc:
            raise OidcError(f"the sign-in provider could not be reached: {exc}") from None
        try:
            tokens: dict[str, Any] = response.json()
        except ValueError:
            tokens = {}
        if response.status_code != 200 or "error" in tokens:
            raise OidcError("the sign-in provider refused the sign-in")
        return tokens

    def _oidc_identity(
        self, tokens: dict[str, Any], nonce: str, invitation: str | None
    ) -> Identity:
        id_token = tokens.get("id_token")
        if not isinstance(id_token, str):
            raise OidcError("the sign-in provider sent no ID token")
        try:
            header = jwt.get_unverified_header(id_token)
        except jwt.PyJWTError:
            raise OidcError("the ID token is malformed") from None
        algorithm = header.get("alg")
        if algorithm not in _ASYMMETRIC_ALGORITHMS:
            raise OidcError("the ID token is not signed with an accepted algorithm")
        keys = self._get_json(str(self.metadata()["jwks_uri"])).get("keys", [])
        matching = [k for k in keys if header.get("kid") in (None, k.get("kid"))]
        if not matching:
            raise OidcError("the ID token was signed with a key the provider does not publish")
        try:
            key = jwt.PyJWK(matching[0], algorithm=algorithm)
            claims = jwt.decode(
                id_token,
                key.key,
                algorithms=[algorithm],
                audience=self.provider.client_id,
                issuer=self.provider.issuer,
                options={"require": ["exp", "iat", "sub", "iss", "aud"]},
                leeway=60,
            )
        except jwt.PyJWTError as exc:
            raise OidcError(f"the ID token did not verify: {exc}") from None
        if claims.get("nonce") != nonce:
            raise OidcError("the ID token does not belong to this sign-in")
        email = claims.get("email") if claims.get("email_verified", False) else None
        return Identity(
            provider=self.provider.id,
            subject=str(claims["sub"]),
            email=email,
            name=claims.get("name"),
            invitation=invitation,
        )

    def _github_identity(self, tokens: dict[str, Any], invitation: str | None) -> Identity:
        access = tokens.get("access_token")
        if not isinstance(access, str):
            raise OidcError("GitHub sent no access token")
        user = self._get_json(
            str(self.metadata()["userinfo_endpoint"]),
            headers={"Authorization": f"Bearer {access}", "Accept": "application/vnd.github+json"},
        )
        if "id" not in user:
            raise OidcError("GitHub did not say who signed in")
        return Identity(
            provider=self.provider.id,
            subject=str(user["id"]),
            email=user.get("email"),
            name=user.get("name") or user.get("login"),
            invitation=invitation,
        )
