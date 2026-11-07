"""Signing in with an OpenID Connect provider, and the identity's mapping to an actor handle
(openspec:hosted-deployment#per-user-authentication, #membership-maps-users-to-actors)."""

# ruff: noqa: E501

from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx2

from strata.core import records as records_mod
from strata.hosted import accounts
from strata.hosted import members as members_mod
from strata.protocol import screening as screening_mod
from strata.web.hosted import HostedServer
from strata.web.security import parse_public_url
from tests.integration._hosted import PUBLIC_URL, hosted, post
from tests.unit.test_hosted_oidc import CLIENT_ID, ISSUER, FakeProvider

_PROVIDER = f"""
[[oidc]]
id = "university"
label = "University sign-in"
kind = "oidc"
issuer = "{ISSUER}"
client_id = "{CLIENT_ID}"
client_secret = "oidc-university"
"""


def _with_provider(tmp_path: Path):  # type: ignore[no-untyped-def]
    h = hosted(tmp_path)
    with h.instance.settings_path.open("a", encoding="utf-8") as handle:
        handle.write(_PROVIDER)
    h.instance._settings = None
    h.instance.secrets.put("oidc-university", "client-secret-value")
    fake = FakeProvider()
    h.server = HostedServer(
        h.instance, public_url=parse_public_url(PUBLIC_URL), background=False, clock=h.clock,
        oidc_http=httpx2.Client(transport=httpx2.MockTransport(fake.handler)),
    )  # fmt: skip
    return h, fake


def _round_trip(client, fake, start: str) -> object:  # type: ignore[no-untyped-def]
    """Follow the browser to the provider and back, as the provider would redirect it."""
    to_provider = client.get(start)
    assert to_provider.status_code == 303, to_provider.text
    query = parse_qs(urlsplit(to_provider.headers["location"]).query)
    assert to_provider.headers["location"].startswith(f"{ISSUER}/authorize?")
    fake.nonce = query["nonce"][0]
    return client.get(f"/auth/university/callback?state={query['state'][0]}&code=good-code")


def test_an_invited_person_links_a_provider_and_acts_as_their_actor(tmp_path: Path) -> None:
    h, fake = _with_provider(tmp_path)
    accounts.add_user(h.instance.store, "priya", display_name="Priya Raman")
    members_mod.add_member(h.instance, "spacing", "priya", actor="priya", role="screener")
    invitation = accounts.create_invitation(h.instance.store, "priya", now=h.clock())

    browser = h.client()
    assert "University sign-in" in browser.get(f"/invite/{invitation}").text
    back = _round_trip(browser, fake, f"/auth/university/start?invite={invitation}")
    # A page that moves on by itself, so the next request is same-site and carries the session.
    assert back.status_code == 200 and 'http-equiv="refresh" content="0; url=/"' in back.text  # type: ignore[attr-defined]
    assert browser.get("/").status_code == 200

    record = sorted(r["id"] for r in records_mod.read_records(h.repo))[0]
    assert (
        post(
            browser, "/screen/title-abstract", {"record_id": record, "decision": "include"}
        ).status_code
        == 303
    )
    events = screening_mod.all_screen_events(h.repo, "title-abstract")
    assert [(e["actor"], e["body"]["record"]) for e in events] == [("priya", record)]

    # Later sign-ins with the same provider identity reach the same account, with no invitation.
    again = h.client()
    assert _round_trip(again, fake, "/auth/university/start").status_code == 200  # type: ignore[attr-defined]
    assert again.get("/p/spacing/").status_code == 200
    methods = [
        (r["username"], r["method"], r["outcome"]) for r in accounts.signin_log(h.instance.store)
    ]
    assert methods[:2] == [("priya", "oidc:university", "success")] * 2


def test_a_provider_identity_not_linked_to_an_account_is_refused_and_logged(tmp_path: Path) -> None:
    h, fake = _with_provider(tmp_path)
    browser = h.client()
    refused = _round_trip(browser, fake, "/auth/university/start")
    assert refused.status_code == 403  # type: ignore[attr-defined]
    assert "not linked to an account" in refused.text  # type: ignore[attr-defined]
    assert browser.get("/").status_code == 303
    assert accounts.signin_log(h.instance.store)[0]["outcome"] == "failure"
    # An invitation cannot be used twice, by a provider or a password.
    invitation = accounts.create_invitation(h.instance.store, "sam.okonkwo", now=h.clock())
    _round_trip(h.client(), fake, f"/auth/university/start?invite={invitation}")
    assert h.client().get(f"/auth/university/start?invite={invitation}").status_code == 404


def test_the_providers_client_secret_is_never_shown(tmp_path: Path) -> None:
    h, _fake = _with_provider(tmp_path)
    browser = h.client()
    for path in ("/signin", "/auth/university/start"):
        response = browser.get(path)
        assert "client-secret-value" not in response.text
        assert "client-secret-value" not in response.headers.get("location", "")


def test_a_callback_started_in_another_browser_signs_nobody_in(tmp_path: Path) -> None:
    """Login CSRF: an attacker's half-finished sign-in, completed in a victim's browser."""
    h, fake = _with_provider(tmp_path)
    accounts.add_user(h.instance.store, "mallory")
    invitation = accounts.create_invitation(h.instance.store, "mallory", now=h.clock())
    attacker = h.client()
    started = attacker.get(f"/auth/university/start?invite={invitation}")
    query = parse_qs(urlsplit(started.headers["location"]).query)
    fake.nonce = query["nonce"][0]
    victim = h.client()
    response = victim.get(f"/auth/university/callback?state={query['state'][0]}&code=good-code")
    assert response.status_code == 403 and "not started in this browser" in response.text
    assert victim.get("/").status_code == 303
    assert accounts.invitation_user(h.instance.store, invitation, now=h.clock()) == "mallory"
