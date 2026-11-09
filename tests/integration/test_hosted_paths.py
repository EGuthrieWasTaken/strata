"""The hosted instance's less travelled paths (openspec:hosted-deployment): the background
worker, later screening batches, projects without a remote, a busy or dirty project, and the
forms and routes that refuse what they cannot use."""

# ruff: noqa: E501

from __future__ import annotations

import time
from pathlib import Path

import httpx2
from fastapi.testclient import TestClient

from strata import gitio
from strata.core import records as records_mod
from strata.hosted import accounts
from strata.hosted import members as members_mod
from strata.web.hosted import HostedServer, create_hosted_app
from strata.web.security import parse_public_url
from tests.integration._hosted import PASSWORD, PUBLIC_URL, csrf_from, hosted, post, sign_in


def _ids(h) -> list[str]:  # type: ignore[no-untyped-def]
    return sorted(r["id"] for r in records_mod.read_records(h.repo))


def _remote_head(bare: Path) -> str:
    return gitio.run(["rev-parse", "refs/heads/main"], cwd=bare).stdout.strip()


# ----------------------------------------------------------------------------- the sync loop


def test_the_background_worker_pushes_a_commit_while_the_server_runs(tmp_path: Path) -> None:
    h = hosted(tmp_path)
    server = HostedServer(h.instance, public_url=parse_public_url(PUBLIC_URL), background=True)
    assert server.worker is not None
    before = _remote_head(h.bare)
    with TestClient(
        create_hosted_app(server), base_url=PUBLIC_URL, follow_redirects=False
    ) as client:
        sign_in(client, "ethan.g")
        response = post(
            client,
            "/criteria/EXC-01/edit",
            {
                "direction": "tightened",
                "definition": "Wrong population: not adults.",
                "rationale": "Rewording the criterion.",
            },
        )
        assert response.status_code == 303
        deadline = time.monotonic() + 60
        while _remote_head(h.bare) == before and time.monotonic() < deadline:
            time.sleep(0.2)  # the commit woke the worker; it pushes in its own thread
        assert _remote_head(h.bare) == gitio.current_commit(h.repo.root)
    assert server.worker._thread is None  # stopped with the server


def test_a_later_batch_counts_only_its_own_decisions(tmp_path: Path) -> None:
    h = hosted(tmp_path)
    sam = h.signed_in("sam.okonkwo")
    first, second, third = _ids(h)[:3]
    post(sam, "/screen/title-abstract", {"record_id": first, "decision": "include"})
    h.server.sync.flush("spacing", actor="sam")
    post(sam, "/screen/title-abstract", {"record_id": second, "decision": "maybe"})
    post(sam, "/screen/title-abstract", {"record_id": third, "decision": "include"})
    h.server.sync.flush("spacing", actor="sam")
    subjects = gitio.log(h.repo.root, max_count=2, fmt="%s")
    assert subjects == [
        "screen(title-abstract): screen 2 records (1 include, 1 maybe)",
        "screen(title-abstract): screen 1 record (1 include)",
    ]
    assert h.server.sync.flush("spacing", actor="sam") == 0  # nothing left to commit


def test_a_project_without_a_remote_is_never_synced(tmp_path: Path) -> None:
    h = hosted(tmp_path)
    h.instance.add_project("pilot", title="Pilot", actor_handle="ethan", actor_name="Ethan")
    members_mod.add_member(h.instance, "pilot", "ethan.g", actor="ethan", role="lead")
    ethan = h.signed_in("ethan.g")
    assert "This project has no remote" in ethan.get("/p/pilot/").text
    assert (
        post(
            ethan,
            "/criteria",
            {
                "kind": "exclusion",
                "label": "Wrong design",
                "definition": "Not a trial.",
                "applies_at": "title-abstract",
                "rationale": "Adding the design criterion.",
            },
            project="pilot",
        ).status_code
        == 303
    )
    loop = h.server.sync
    assert loop.status("pilot").push_pending is False
    assert loop.push("pilot") is False and loop.run_due() == []
    assert (
        loop.resolve("pilot", "ethan", {}).remote is None
        and loop.sync_now("pilot", "ethan").remote is None
    )
    page = ethan.get("/p/pilot/-/sync")
    assert page.status_code == 200 and "no remote" in page.text
    assert not gitio.is_dirty(h.instance.project_dir("pilot"))


def test_a_page_is_served_from_the_current_copy_while_a_sync_runs(tmp_path: Path) -> None:
    h = hosted(tmp_path)
    loop = h.server.sync
    with loop._lock("spacing"):
        loop.pull_before_read("spacing", "sam")
    assert loop.status("spacing").last_fetch is None


def test_changes_the_instance_did_not_make_stop_the_sync_and_are_named(tmp_path: Path) -> None:
    h = hosted(tmp_path)
    (h.repo.root / "notes-left-by-hand.txt").write_text("a hand edit\n")
    h.server.sync.note_commit("spacing", "ethan")
    assert h.server.sync.run_due() == []
    status = h.server.sync.status("spacing")
    assert "uncommitted changes the instance did not make" in (status.last_error or "")
    assert status.push_pending and status.failures == 1


def test_a_member_can_sync_now_and_an_observer_cannot(tmp_path: Path) -> None:
    h = hosted(tmp_path)
    sam, olive = h.signed_in("sam.okonkwo"), h.signed_in("olive")
    csrf = csrf_from(sam.get("/p/spacing/-/sync").text)
    assert (
        sam.post("/p/spacing/-/sync", data={"csrf_token": csrf, "action": "sync"}).status_code
        == 303
    )
    assert h.server.sync.status("spacing").last_success is not None
    olive_csrf = csrf_from(olive.get("/p/spacing/-/sync").text)
    assert (
        olive.post(
            "/p/spacing/-/sync", data={"csrf_token": olive_csrf, "action": "sync"}
        ).status_code
        == 403
    )
    assert (
        sam.post("/p/spacing/-/sync", data={"csrf_token": "forged", "action": "sync"}).status_code
        == 403
    )


# ---------------------------------------------------------------------- forms that refuse


def test_the_sign_in_and_invitation_forms_refuse_what_they_cannot_use(tmp_path: Path) -> None:
    h = hosted(tmp_path)
    sam = h.signed_in("sam.okonkwo")
    assert sam.get("/signin").status_code == 303  # already signed in
    assert sam.post("/signout", data={"csrf_token": "forged"}).status_code == 403
    assert sam.get("/").status_code == 200  # still signed in
    accounts.add_user(h.instance.store, "priya")
    token = accounts.create_invitation(h.instance.store, "priya", now=h.clock())
    browser = h.client()
    page = browser.get(f"/invite/{token}")
    assert (
        browser.post(
            f"/invite/{token}", data={"csrf_token": "forged", "password": PASSWORD}
        ).status_code
        == 403
    )
    short = browser.post(
        f"/invite/{token}", data={"csrf_token": csrf_from(page.text), "password": "short"}
    )
    assert short.status_code == 422 and "at least 12" in short.text
    assert (
        accounts.invitation_user(h.instance.store, token, now=h.clock()) == "priya"
    )  # not used up


def test_sign_in_providers_that_do_not_exist_or_cannot_be_reached(tmp_path: Path) -> None:
    h = hosted(tmp_path)
    with h.instance.settings_path.open("a", encoding="utf-8") as handle:
        handle.write(
            '\n[[oidc]]\nid = "uni"\nkind = "oidc"\nissuer = "https://login.example.edu"\nclient_id = "c"\nclient_secret = "s"\n'
        )
    h.instance._settings = None

    def unreachable(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("connection refused", request=request)

    server = HostedServer(h.instance, public_url=parse_public_url(PUBLIC_URL), background=False,
                          oidc_http=httpx2.Client(transport=httpx2.MockTransport(unreachable)))  # fmt: skip
    client = TestClient(create_hosted_app(server), base_url=PUBLIC_URL, follow_redirects=False)
    assert client.get("/auth/nope/start").status_code == 404
    assert client.get("/auth/nope/callback?state=x&code=y").status_code == 404
    down = client.get("/auth/uni/start")
    assert down.status_code == 502 and "could not be reached" in down.text
    import hashlib

    client.cookies.set(
        "strata_oidc_state",
        hashlib.sha256(b"made-up").hexdigest(),
        domain="strata.example.test",
        path="/auth/",
    )
    stale = client.get("/auth/uni/callback?state=made-up&code=y")
    assert stale.status_code == 403 and "expired" in stale.text


def test_the_members_and_sync_forms_check_who_is_asking(tmp_path: Path) -> None:
    h = hosted(tmp_path)
    assert h.client().get("/p/spacing/-/members").status_code == 303  # to the sign-in page
    sam, ethan = h.signed_in("sam.okonkwo"), h.signed_in("ethan.g")
    assert post(sam, "/-/members/remove", {"username": "olive"}).status_code == 403
    assert (
        ethan.post(
            "/p/spacing/-/members",
            data={"csrf_token": "forged", "username": "x", "actor": "sam", "role": "screener"},
        ).status_code
        == 403
    )
    assert (
        ethan.post(
            "/p/spacing/-/members/remove", data={"csrf_token": "forged", "username": "olive"}
        ).status_code
        == 403
    )
    assert members_mod.membership(h.instance, "spacing", "olive") is not None


def test_a_write_to_a_project_must_be_a_form_within_the_upload_limit(tmp_path: Path) -> None:
    h = hosted(tmp_path)
    ethan = h.signed_in("ethan.g")
    as_json = ethan.post(
        "/p/spacing/screen/title-abstract", json={"record_id": "x", "decision": "include"}
    )
    assert as_json.status_code == 403
    limit = h.instance.settings.max_upload_mb * 1024 * 1024
    too_big = ethan.post(
        "/p/spacing/import",
        headers={
            "content-type": "multipart/form-data; boundary=x",
            "content-length": str(limit + 1),
        },
        content=b"x",
    )
    assert too_big.status_code == 413
