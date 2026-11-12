"""The hosted instance's web application: openspec:hosted-deployment.

Sign-in, sessions and the security baseline; memberships and roles enforced on every route;
commit attribution; the instance and project dashboards.
"""

# ruff: noqa: E501

from __future__ import annotations

from pathlib import Path

import pytest

from strata import gitio
from strata.hosted import accounts
from strata.hosted import members as members_mod
from strata.protocol import screening as screening_mod
from tests.integration._hosted import (
    PASSWORD,
    csrf_from,
    hosted,
    post,
    sign_in,
)


def _record_ids(h) -> list[str]:  # type: ignore[no-untyped-def]
    from strata.core import records as records_mod

    return sorted(r["id"] for r in records_mod.read_records(h.repo))


def _screen_events(h, actor: str) -> list[dict]:  # type: ignore[no-untyped-def]
    return [
        e for e in screening_mod.all_screen_events(h.repo, "title-abstract") if e["actor"] == actor
    ]


# ------------------------------------------------------------------------ security baseline


def test_plain_http_issues_no_session(tmp_path: Path) -> None:
    h = hosted(tmp_path)
    client = h.client(base_url="http://strata.example.test")
    response = client.post("/signin", data={"username": "sam.okonkwo", "password": PASSWORD})
    assert response.status_code == 403
    assert "set-cookie" not in response.headers
    assert accounts.signin_log(h.instance.store) == []
    redirected = client.get("/p/spacing/?x=1")
    assert redirected.status_code == 308
    assert redirected.headers["location"] == "https://strata.example.test/p/spacing/?x=1"


def test_plain_http_public_url_needs_local_testing_mode(tmp_path: Path) -> None:
    from strata.web.hosted import HostedConfigError, HostedServer
    from strata.web.security import parse_public_url

    h = hosted(tmp_path)
    with pytest.raises(HostedConfigError):
        HostedServer(
            h.instance, public_url=parse_public_url("http://localhost:8000"), background=False
        )
    server = HostedServer(
        h.instance, public_url=parse_public_url("http://localhost:8000"), allow_plain_http=True,
        background=False,
    )  # fmt: skip
    from fastapi.testclient import TestClient

    from strata.web.hosted import create_hosted_app

    client = TestClient(
        create_hosted_app(server), base_url="http://localhost:8000", follow_redirects=False
    )
    sign_in(client, "sam.okonkwo")
    assert client.get("/p/spacing/").status_code == 200


def test_host_and_origin_are_checked_against_the_public_url(tmp_path: Path) -> None:
    h = hosted(tmp_path)
    client = h.client()
    assert client.get("/signin", headers={"host": "evil.example"}).status_code == 400
    assert client.get("/signin", headers={"origin": "https://evil.example"}).status_code == 400
    assert (
        client.get("/signin", headers={"origin": "https://strata.example.test"}).status_code == 200
    )
    # The health probe answers whatever address the orchestrator uses, and says nothing else.
    health = client.get("/healthz", headers={"host": "10.0.0.5:8000"})
    assert health.status_code == 200
    assert health.json() == {"status": "ok"}


def test_session_cookie_is_secure_httponly_strict_and_expires(tmp_path: Path) -> None:
    h = hosted(tmp_path)
    client = h.client()
    page = client.get("/signin")
    response = client.post(
        "/signin",
        data={"csrf_token": csrf_from(page.text), "username": "sam.okonkwo", "password": PASSWORD},
    )
    assert response.status_code == 303
    cookie = next(
        v
        for k, v in response.headers.multi_items()
        if k == "set-cookie" and "__Host-strata_session" in v
    )
    lowered = cookie.lower()
    assert "secure" in lowered and "httponly" in lowered and "samesite=strict" in lowered
    assert "max-age=43200" in lowered and "path=/" in lowered
    # Every response carries the hardening headers, HSTS included.
    home = client.get("/")
    assert home.status_code == 200
    assert home.headers["strict-transport-security"].startswith("max-age=")
    assert home.headers["x-frame-options"] == "DENY"
    assert "default-src 'self'" in home.headers["content-security-policy"]


def test_signin_form_needs_its_csrf_token(tmp_path: Path) -> None:
    h = hosted(tmp_path)
    client = h.client()
    client.get("/signin")
    response = client.post(
        "/signin", data={"csrf_token": "forged", "username": "sam.okonkwo", "password": PASSWORD}
    )
    assert response.status_code == 403


def test_password_guessing_is_cooled_off_and_logged(tmp_path: Path) -> None:
    h = hosted(tmp_path)
    client = h.client()
    for _ in range(accounts.MAX_FAILURES_PER_ACCOUNT):
        page = client.get("/signin")
        response = client.post(
            "/signin",
            data={
                "csrf_token": csrf_from(page.text),
                "username": "sam.okonkwo",
                "password": "wrong password!",
            },
        )
        assert response.status_code == 401
    page = client.get("/signin")
    response = client.post(
        "/signin",
        data={"csrf_token": csrf_from(page.text), "username": "sam.okonkwo", "password": PASSWORD},
    )
    assert response.status_code == 429
    assert "__Host-strata_session" not in response.headers.get("set-cookie", "")
    outcomes = [row["outcome"] for row in accounts.signin_log(h.instance.store)]
    assert outcomes.count("failure") == accounts.MAX_FAILURES_PER_ACCOUNT
    assert outcomes[0] == "locked"
    h.clock.advance(accounts.LOCKOUT + 1)
    page = client.get("/signin")
    response = client.post(
        "/signin",
        data={"csrf_token": csrf_from(page.text), "username": "sam.okonkwo", "password": PASSWORD},
    )
    assert response.status_code == 303


def test_sessions_end_on_idle_timeout_sign_out_and_disable(tmp_path: Path) -> None:
    h = hosted(tmp_path)
    client = sign_in(h.client(), "sam.okonkwo")
    assert client.get("/").status_code == 200
    h.clock.advance(h.instance.settings.session_idle_minutes * 60 + 1)
    assert client.get("/").status_code == 303  # back to the sign-in page
    sign_in(client, "sam.okonkwo")
    home = client.get("/")
    assert client.post("/signout", data={"csrf_token": csrf_from(home.text)}).status_code == 303
    assert client.get("/").status_code == 303
    sign_in(client, "sam.okonkwo")
    accounts.disable_user(h.instance.store, "sam.okonkwo")
    assert client.get("/p/spacing/").status_code == 303


def test_the_inactivity_exit_is_disabled(tmp_path: Path) -> None:
    h = hosted(tmp_path)
    client = sign_in(h.client(), "sam.okonkwo")
    state = h.server.project_state(h.instance.get_project("spacing"))  # type: ignore[arg-type]
    assert state.clock.timeout_seconds == float("inf")
    assert client.get("/p/spacing/").status_code == 200


# ---------------------------------------------------------------------- authentication


def test_local_account_password_is_stored_as_argon2id(tmp_path: Path) -> None:
    h = hosted(tmp_path)
    row = h.instance.store.one("SELECT password_hash FROM users WHERE username = 'sam.okonkwo'")
    assert row is not None and row["password_hash"].startswith("$argon2id$")
    assert PASSWORD.encode() not in (h.instance.state_dir / "instance.db").read_bytes()
    sign_in(h.client(), "sam.okonkwo")


def test_unauthenticated_requests_cannot_record_a_decision(tmp_path: Path) -> None:
    h = hosted(tmp_path)
    client = h.client()
    record = _record_ids(h)[0]
    response = client.post(
        "/p/spacing/screen/title-abstract", data={"record_id": record, "decision": "include"}
    )
    assert response.status_code == 401
    assert client.get("/p/spacing/").status_code == 303
    assert screening_mod.all_screen_events(h.repo, "title-abstract") == []


def test_mutating_requests_need_the_sessions_csrf_token(tmp_path: Path) -> None:
    h = hosted(tmp_path)
    client = h.signed_in("sam.okonkwo")
    record = _record_ids(h)[0]
    response = client.post(
        "/p/spacing/screen/title-abstract",
        data={"csrf_token": "not-the-token", "record_id": record, "decision": "include"},
    )
    assert response.status_code == 403
    assert screening_mod.all_screen_events(h.repo, "title-abstract") == []


def test_invitation_sets_a_password_once(tmp_path: Path) -> None:
    h = hosted(tmp_path)
    accounts.add_user(h.instance.store, "priya", display_name="Priya")
    token = accounts.create_invitation(h.instance.store, "priya", now=h.clock())
    client = h.client()
    page = client.get(f"/invite/{token}")
    assert page.status_code == 200 and "Priya" in page.text
    response = client.post(
        f"/invite/{token}",
        data={"csrf_token": csrf_from(page.text), "password": "a brand new password"},
    )
    assert response.status_code == 303
    assert client.get("/").status_code == 200
    assert h.client().get(f"/invite/{token}").status_code == 404
    sign_in(h.client(), "priya", "a brand new password")


# ----------------------------------------------------------------- memberships and roles


def test_attributed_decision(tmp_path: Path) -> None:
    h = hosted(tmp_path)
    client = h.signed_in("sam.okonkwo")
    record = _record_ids(h)[0]
    response = post(client, "/screen/title-abstract", {"record_id": record, "decision": "include"})
    assert response.status_code == 303
    assert response.headers["location"].startswith("/p/spacing/screen/title-abstract")
    events = _screen_events(h, "sam")
    assert [e["body"]["record"] for e in events] == [record]
    # Signing out ends the screening session, which commits the batch as sam.
    home = client.get("/")
    client.post("/signout", data={"csrf_token": csrf_from(home.text)})
    log = gitio.log(h.repo.root, max_count=1, fmt="%an <%ae> | %cn <%ce> | %s")
    assert log == [
        "Sam Okonkwo <sam@example.org> | strata instance <strata@instance.invalid> | "
        "screen(title-abstract): screen 1 record (1 include)"
    ]
    assert "Strata-Actor: sam" in gitio.commit_message(h.repo.root, "HEAD")


def test_observer_cannot_record_a_decision(tmp_path: Path) -> None:
    h = hosted(tmp_path)
    client = h.signed_in("olive")
    record = _record_ids(h)[0]
    assert client.get("/p/spacing/records").status_code == 200
    response = post(client, "/screen/title-abstract", {"record_id": record, "decision": "include"})
    assert response.status_code == 403
    assert screening_mod.all_screen_events(h.repo, "title-abstract") == []
    assert not gitio.is_dirty(h.repo.root)


def test_roles_are_enforced_on_every_route(tmp_path: Path) -> None:
    h = hosted(tmp_path)
    sam = h.signed_in("sam.okonkwo")
    # Only adjudicators (and leads) see or resolve the adjudication queue.
    assert sam.get("/p/spacing/adjudicate/title-abstract").status_code == 403
    assert (
        post(
            sam, "/adjudicate/title-abstract", {"record_id": "x", "decision": "include"}
        ).status_code
        == 403
    )
    # A screener cannot change the protocol, import, or manage members.
    assert (
        post(
            sam,
            "/criteria/INC-01/edit",
            {"direction": "editorial", "rationale": "Tidying the wording."},
        ).status_code
        == 403
    )
    assert post(sam, "/dedup/run", {"rationale": "Merging duplicates now."}).status_code == 403
    assert sam.get("/p/spacing/-/members").status_code == 403
    ethan = h.signed_in("ethan.g")
    assert ethan.get("/p/spacing/adjudicate/title-abstract").status_code == 200
    assert ethan.get("/p/spacing/-/members").status_code == 200


def test_matrix_of_capabilities() -> None:
    may, need = members_mod.may, members_mod.required_capability
    assert need("GET", "/records") == members_mod.READ
    assert need("POST", "/screen/title-abstract") == members_mod.SCREEN
    assert need("POST", "/records/abc/fix") == members_mod.FIX_RECORD
    assert need("POST", "/criteria") == members_mod.LEAD
    assert need("POST", "/something-new") == members_mod.LEAD  # default deny
    assert not may("observer", members_mod.SCREEN)
    assert may("adjudicator", members_mod.ADJUDICATE) and not may(
        "screener", members_mod.ADJUDICATE
    )
    assert may("extractor", members_mod.EXTRACT) and not may("extractor", members_mod.SCREEN)
    assert may("lead", members_mod.LEAD)


def test_lead_manages_members_in_the_browser(tmp_path: Path) -> None:
    h = hosted(tmp_path)
    accounts.add_user(h.instance.store, "priya", password=PASSWORD)
    ethan = h.signed_in("ethan.g")
    page = ethan.get("/p/spacing/-/members")
    csrf = csrf_from(page.text)
    added = ethan.post(
        "/p/spacing/-/members",
        data={"csrf_token": csrf, "username": "priya", "actor": "priya", "role": "screener"},
    )
    assert added.status_code == 303
    assert members_mod.membership(h.instance, "spacing", "priya") is not None
    taken = ethan.post(
        "/p/spacing/-/members",
        data={"csrf_token": csrf, "username": "priya", "actor": "sam", "role": "screener"},
    )
    assert taken.status_code == 422 and "already belongs" in taken.text
    lone_lead = ethan.post(
        "/p/spacing/-/members/remove", data={"csrf_token": csrf, "username": "ethan.g"}
    )
    assert lone_lead.status_code == 422
    removed = ethan.post(
        "/p/spacing/-/members/remove", data={"csrf_token": csrf, "username": "priya"}
    )
    assert removed.status_code == 303
    assert members_mod.membership(h.instance, "spacing", "priya") is None


# ----------------------------------------------------------------------------- dashboards


def test_instance_dashboard_lists_the_users_projects(tmp_path: Path) -> None:
    h = hosted(tmp_path)
    h.instance.add_project("other", title="Another review", actor_handle="zoe", actor_name="Zoe")
    sam = h.signed_in("sam.okonkwo")
    page = sam.get("/")
    assert page.status_code == 200
    assert "Spacing review" in page.text and "/p/spacing/" in page.text
    assert "Another review" not in page.text


def test_project_dashboard_shows_last_sync_and_remote_status(tmp_path: Path) -> None:
    h = hosted(tmp_path)
    sam = h.signed_in("sam.okonkwo")
    page = sam.get("/p/spacing/")
    assert page.status_code == 200
    assert 'data-testid="project-sync"' in page.text
    assert str(h.bare) in page.text
    assert "Last synced with the shared remote: 2027-" in page.text  # the pull before the page
    # Every link the review's screens render carries the project's prefix.
    assert 'href="/p/spacing/records"' in page.text
    assert 'href="/records"' not in page.text


def test_strata_serve_never_offers_sign_in_or_a_second_repository(tmp_path: Path) -> None:
    """openspec:web-ui#strictly-local, "Hosted mode is explicit": only `strata host` has accounts."""
    from fastapi.testclient import TestClient

    from strata.web.app import create_app

    h = hosted(tmp_path)
    app = create_app(repo_root=h.repo.root, actor="ethan", session_token="tok-0123456789abcdef")
    client = TestClient(app, base_url="http://127.0.0.1:8000")
    for path in ("/signin", "/invite/x", "/auth/github/start", "/p/spacing/", "/-/members"):
        response = client.get(f"{path}?token=tok-0123456789abcdef")
        assert response.status_code == 404, path
    page = client.get("/?token=tok-0123456789abcdef")
    assert "Sign out" not in page.text and 'href="/records"' in page.text


def test_a_hook_pushed_to_the_remote_never_runs_on_the_instance(tmp_path: Path) -> None:
    """A review carries its git hooks; on a shared server they would be anyone-with-push's code."""
    from strata.core import sync as sync_mod
    from tests.integration._hosted import local_clone

    h = hosted(tmp_path)
    marker = tmp_path / "pwned"
    laptop = local_clone(h.bare, tmp_path / "laptop")
    hook = laptop.path(".strata", "hooks", "pre-commit")
    hook.write_text(f"#!/bin/sh\ntouch {marker}\nexec strata internal hook-pre-commit\n")
    gitio.add_all(laptop.root)
    gitio.run(
        ["commit", "--no-verify", "-m", "hooks: tweak\n\nStrata-Op: test\nStrata-Actor: ethan"],
        cwd=laptop.root,
    )
    marker.unlink(missing_ok=True)
    sync_mod.sync(laptop, actor="ethan", sleep=lambda _s: None)
    marker.unlink(missing_ok=True)
    assert gitio.get_config(h.repo.root, "core.hooksPath") == str(h.instance.hooks_dir)
    sam = h.signed_in("sam.okonkwo")
    h.clock.advance(h.instance.settings.sync_interval + 1)
    sam.get("/p/spacing/")  # pulls the new hook
    assert "touch" in h.repo.path(".strata", "hooks", "pre-commit").read_text()
    record = _record_ids(h)[0]
    post(sam, "/screen/title-abstract", {"record_id": record, "decision": "include"})
    h.server.sync.flush("spacing", actor="sam")  # a commit, which runs the pre-commit hook
    assert gitio.log(h.repo.root, max_count=1, fmt="%s")[0].startswith("screen(")
    assert not marker.exists()


def test_the_instances_own_forms_refuse_a_large_or_unsized_body(tmp_path: Path) -> None:
    h = hosted(tmp_path)
    client = h.client()
    big = client.post(
        "/signin",
        content=b"x" * (2 * 1024 * 1024),
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    assert big.status_code == 413


def test_an_instance_on_a_port_of_its_own_names_its_cookies_after_it(tmp_path: Path) -> None:
    """Cookies are shared by every port of a host name, so two instances (or an instance and a
    `strata serve`) on one host must not use the same cookie names (#85)."""
    from strata.web.hosted import HostedServer
    from strata.web.security import parse_public_url

    h = hosted(tmp_path)
    default = h.server
    assert default.session_cookie == "__Host-strata_session"
    assert default.signin_cookie == "__Host-strata_signin"
    assert default.oidc_state_cookie == "strata_oidc_state"
    other = HostedServer(
        h.instance,
        public_url=parse_public_url("https://strata.example.test:8443"),
        background=False,
    )
    assert other.session_cookie == "__Host-strata_session_8443"
    assert other.signin_cookie == "__Host-strata_signin_8443"
    assert other.oidc_state_cookie == "strata_oidc_state_8443"
    plain = HostedServer(
        h.instance,
        public_url=parse_public_url("http://localhost:8765"),
        background=False,
        allow_plain_http=True,
    )
    assert plain.session_cookie == "strata_session_8765"
