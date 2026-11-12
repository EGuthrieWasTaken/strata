"""Integration tests for the `strata serve` FastAPI app: openspec:web-ui.

Uses FastAPI's TestClient (an in-process ASGI transport, no real socket)
against a real temporary repository -- the same fidelity level as the CLI's
own `typer.testing.CliRunner` tests, at the HTTP layer instead.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from strata.core.init import init_repository
from strata.core.records import write_records
from strata.core.repo import open_repo
from strata.protocol.criteria import add_criterion
from strata.web.app import create_app

_TOKEN = "test-session-token-0123456789"


def _record(record_id: str, **overrides: object) -> dict:
    base = {
        "id": record_id,
        "type": "article-journal",
        "title": f"Title for {record_id}",
        "abstract": "An abstract to screen.",
        "author": [{"family": "Smith"}],
        "strata": {
            "canonical_key": f"sig:{record_id}",
            "canonical": True,
            "sources": [{"import": "imp_01arz3ndektsv4rrffq69g5fav"}],
        },
    }
    base.update(overrides)
    base = {k: v for k, v in base.items() if v is not None}
    return base


def _repo_with_records(tmp_path: Path, records: list[dict]):  # type: ignore[no-untyped-def]
    root = tmp_path / "review"
    init_repository(root, title="Web Test Review", actor_handle="ethan", actor_name="Ethan")
    repo = open_repo(root)
    if records:
        write_records(repo, records)
        repo = open_repo(root)
    return repo


def _client(repo, *, actor: str = "ethan", **kwargs: object) -> TestClient:  # type: ignore[no-untyped-def]
    app = create_app(repo_root=repo.root, actor=actor, session_token=_TOKEN, **kwargs)
    return TestClient(app, base_url="http://127.0.0.1:8000")


def _authenticated(client: TestClient) -> TestClient:
    r = client.get(f"/?token={_TOKEN}")
    assert r.status_code == 200
    return client


# ---------------------------------------------------------------- security


def test_first_request_with_token_sets_the_session_cookie(tmp_path: Path) -> None:
    repo = _repo_with_records(tmp_path, [])
    client = _client(repo)
    r = client.get(f"/?token={_TOKEN}")
    assert r.status_code == 200
    assert client.cookies.get("strata_session_8000") == _TOKEN


def test_two_servers_on_one_host_each_keep_their_own_session(tmp_path: Path) -> None:
    """Cookies ignore ports, so a cookie both servers called `strata_session` was overwritten by
    whichever was opened last, and the other answered "missing or invalid session" (#85)."""
    first = _repo_with_records(tmp_path / "a", [])
    second = _repo_with_records(tmp_path / "b", [])
    app_a = create_app(repo_root=first.root, actor="ethan", session_token="token-a", port=8801)
    app_b = create_app(repo_root=second.root, actor="ethan", session_token="token-b", port=8802)
    a = TestClient(app_a, base_url="http://127.0.0.1:8801")
    b = TestClient(app_b, base_url="http://127.0.0.1:8802")

    # One browser keeps one cookie jar for the host, whatever the port: what either server sets,
    # the other is sent.
    assert a.get("/?token=token-a").status_code == 200
    b.cookies.update(a.cookies)
    assert b.get("/?token=token-b").status_code == 200
    a.cookies.update(b.cookies)
    # Back to the first by plain path, then the second: both still signed in.
    assert a.get("/").status_code == 200
    assert b.get("/").status_code == 200
    assert a.cookies.get("strata_session_8801") == "token-a"
    assert a.cookies.get("strata_session_8802") == "token-b"


def test_a_public_url_names_the_cookie_after_the_port_the_browser_uses(tmp_path: Path) -> None:
    from strata.web.security import parse_public_url, session_cookie_name

    # Two containers both listening on 8000 inside, published on different ports.
    assert session_cookie_name(8000, parse_public_url("http://localhost:8765")) == (
        "strata_session_8765"
    )
    assert session_cookie_name(8000, parse_public_url("https://review.example.org")) == (
        "strata_session"
    )
    assert session_cookie_name(8000) == "strata_session_8000"


def test_a_request_with_no_session_is_told_what_to_do(tmp_path: Path) -> None:
    repo = _repo_with_records(tmp_path, [])
    refused = _client(repo).get("/records")
    assert refused.status_code == 403
    assert refused.headers["content-type"].startswith("text/plain")
    assert "?token=" in refused.text and "strata serve" in refused.text


def test_request_without_token_or_cookie_is_rejected(tmp_path: Path) -> None:
    repo = _repo_with_records(tmp_path, [])
    client = _client(repo)
    r = client.get("/")
    assert r.status_code == 403


def test_request_with_wrong_token_is_rejected(tmp_path: Path) -> None:
    repo = _repo_with_records(tmp_path, [])
    client = _client(repo)
    r = client.get("/?token=wrong")
    assert r.status_code == 403


def test_mutating_request_without_csrf_field_is_rejected(tmp_path: Path) -> None:
    records = [_record("rec_0000000000000001")]
    repo = _repo_with_records(tmp_path, records)
    client = _authenticated(_client(repo))
    r = client.post(
        "/screen/title-abstract",
        data={"record_id": "rec_0000000000000001", "decision": "include", "skip": ""},
    )
    assert r.status_code == 403


def test_mutating_request_with_wrong_csrf_field_is_rejected(tmp_path: Path) -> None:
    records = [_record("rec_0000000000000001")]
    repo = _repo_with_records(tmp_path, records)
    client = _authenticated(_client(repo))
    r = client.post(
        "/screen/title-abstract",
        data={
            "record_id": "rec_0000000000000001",
            "decision": "include",
            "skip": "",
            "csrf_token": "wrong",
        },
    )
    assert r.status_code == 403


def test_mismatched_host_header_is_rejected(tmp_path: Path) -> None:
    repo = _repo_with_records(tmp_path, [])
    client = _client(repo)
    r = client.get("/", headers={"Host": "evil.example"})
    assert r.status_code == 400


def test_mismatched_origin_header_is_rejected(tmp_path: Path) -> None:
    repo = _repo_with_records(tmp_path, [])
    client = _client(repo)
    r = client.get("/?token=" + _TOKEN, headers={"Origin": "http://evil.example"})
    assert r.status_code == 400


def test_matching_origin_header_is_allowed(tmp_path: Path) -> None:
    repo = _repo_with_records(tmp_path, [])
    client = _client(repo)
    r = client.get("/?token=" + _TOKEN, headers={"Origin": "http://127.0.0.1:8000"})
    assert r.status_code == 200


def test_response_carries_security_headers(tmp_path: Path) -> None:
    repo = _repo_with_records(tmp_path, [])
    client = _authenticated(_client(repo))
    r = client.get("/")
    assert "Content-Security-Policy" in r.headers
    assert r.headers["X-Frame-Options"] == "DENY"
    assert r.headers["X-Content-Type-Options"] == "nosniff"


def test_the_referrer_policy_lets_a_browser_send_its_real_origin(tmp_path: Path) -> None:
    """Under `Referrer-Policy: no-referrer` a browser sends `Origin: null` on every form post, the
    interface's own same-origin forms included, and the Origin check then refuses all of them.
    The in-process client sends no Origin header, so only the policy itself can be pinned here;
    `tests/browser` posts a form from a real browser."""
    repo = _repo_with_records(tmp_path, [])
    client = _authenticated(_client(repo))

    policy = client.get("/").headers["Referrer-Policy"]

    assert policy == "same-origin"


def test_a_post_from_a_page_sandboxed_into_a_null_origin_is_still_refused(tmp_path: Path) -> None:
    repo = _repo_with_records(tmp_path, [])
    client = _authenticated(_client(repo))

    r = client.post(
        "/dedup/run", data={"csrf_token": _TOKEN, "rationale": "x" * 20}, headers={"origin": "null"}
    )

    assert r.status_code == 400 and r.text == "invalid Origin header"


def test_expired_session_is_rejected(tmp_path: Path) -> None:
    repo = _repo_with_records(tmp_path, [])
    client = _client(repo, inactivity_timeout=0.0)
    r = client.get(f"/?token={_TOKEN}")
    assert r.status_code == 503


# --------------------------------------------------------------- dashboard


def test_dashboard_renders_project_title_and_actor(tmp_path: Path) -> None:
    repo = _repo_with_records(tmp_path, [])
    client = _authenticated(_client(repo))
    r = client.get("/")
    assert r.status_code == 200
    assert "Web Test Review" in r.text
    assert "ethan" in r.text


def test_dashboard_reflects_screening_progress(tmp_path: Path) -> None:
    from strata.protocol.screening import record_screen_decision

    records = [_record("rec_0000000000000001")]
    repo = _repo_with_records(tmp_path, records)
    record_screen_decision(
        repo,
        stage="title-abstract",
        record_id="rec_0000000000000001",
        decision="include",
        actor="ethan",
    )
    repo = open_repo(repo.root)
    client = _authenticated(_client(repo))
    r = client.get("/")
    assert '<td data-label="Resolved">1</td>' in r.text  # resolved count for title-abstract


# -------------------------------------------------------------- screening


def test_screen_unknown_stage_is_404(tmp_path: Path) -> None:
    repo = _repo_with_records(tmp_path, [])
    client = _authenticated(_client(repo))
    r = client.get("/screen/not-a-stage")
    assert r.status_code == 404


def test_screen_with_nothing_to_screen(tmp_path: Path) -> None:
    repo = _repo_with_records(tmp_path, [])
    client = _authenticated(_client(repo))
    r = client.get("/screen/title-abstract")
    assert r.status_code == 200
    assert "Nothing left to screen" in r.text


def test_screen_shows_the_first_queued_record(tmp_path: Path) -> None:
    records = [_record("rec_0000000000000001", title="Unique Title A")]
    repo = _repo_with_records(tmp_path, records)
    client = _authenticated(_client(repo))
    r = client.get("/screen/title-abstract")
    assert r.status_code == 200
    assert "Unique Title A" in r.text
    assert "1 of 1" in r.text


def test_screen_shows_no_abstract_flag(tmp_path: Path) -> None:
    records = [_record("rec_0000000000000001", abstract=None)]
    repo = _repo_with_records(tmp_path, records)
    client = _authenticated(_client(repo))
    r = client.get("/screen/title-abstract")
    assert "no abstract on file" in r.text


def test_screen_hides_metadata_when_blind_metadata_is_set(tmp_path: Path) -> None:
    from strata.core import manifest as manifest_mod

    records = [_record("rec_0000000000000001")]
    repo = _repo_with_records(tmp_path, records)
    doc = manifest_mod.load_manifest_doc(repo.root)
    manifest_mod.set_value(doc, "screening.blind_metadata", True)
    manifest_mod.write_manifest(repo.root, doc)
    repo = open_repo(repo.root)
    client = _authenticated(_client(repo))
    r = client.get("/screen/title-abstract")
    assert "Smith" not in r.text


def test_screen_lists_active_exclusion_criteria(tmp_path: Path) -> None:
    records = [_record("rec_0000000000000001")]
    repo = _repo_with_records(tmp_path, records)
    add_criterion(
        repo,
        kind="exclusion",
        label="Not empirical",
        definition="Not an empirical study.",
        applies_at=["title-abstract"],
        actor="ethan",
        rationale="Establishing the initial protocol criteria.",
        criterion_id="EXC-01",
    )
    repo = open_repo(repo.root)
    client = _authenticated(_client(repo))
    r = client.get("/screen/title-abstract")
    assert "EXC-01" in r.text
    assert "Not empirical" in r.text


def test_screen_post_records_an_include_decision_and_redirects(tmp_path: Path) -> None:
    from strata.protocol.screening import all_screen_events

    records = [_record("rec_0000000000000001")]
    repo = _repo_with_records(tmp_path, records)
    client = _authenticated(_client(repo))
    r = client.post(
        "/screen/title-abstract",
        data={
            "record_id": "rec_0000000000000001",
            "decision": "include",
            "skip": "",
            "csrf_token": _TOKEN,
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/screen/title-abstract?prev=rec_0000000000000001"

    repo = open_repo(repo.root)
    events = all_screen_events(repo, "title-abstract")
    assert len(events) == 1
    assert events[0]["body"]["decision"] == "include"


def test_screen_post_exclude_with_citation(tmp_path: Path) -> None:
    from strata.protocol.screening import all_screen_events

    records = [_record("rec_0000000000000001")]
    repo = _repo_with_records(tmp_path, records)
    add_criterion(
        repo,
        kind="exclusion",
        label="Not empirical",
        definition="Not an empirical study.",
        applies_at=["title-abstract"],
        actor="ethan",
        rationale="Establishing the initial protocol criteria.",
        criterion_id="EXC-01",
    )
    repo = open_repo(repo.root)
    client = _authenticated(_client(repo))
    r = client.post(
        "/screen/title-abstract",
        data={
            "record_id": "rec_0000000000000001",
            "decision": "exclude",
            "criteria": "EXC-01",
            "skip": "",
            "csrf_token": _TOKEN,
        },
    )
    assert r.status_code == 200  # after the 303 redirect is followed

    repo = open_repo(repo.root)
    events = all_screen_events(repo, "title-abstract")
    assert events[0]["body"]["decision"] == "exclude"
    assert events[0]["body"]["criteria"] == ["EXC-01"]


def test_screen_post_exclude_without_citation_is_rejected_with_the_same_record_shown(
    tmp_path: Path,
) -> None:
    records = [_record("rec_0000000000000001", title="Needs A Reason")]
    repo = _repo_with_records(tmp_path, records)
    client = _authenticated(_client(repo))
    r = client.post(
        "/screen/title-abstract",
        data={
            "record_id": "rec_0000000000000001",
            "decision": "exclude",
            "skip": "",
            "csrf_token": _TOKEN,
        },
    )
    assert r.status_code == 422
    assert "Needs A Reason" in r.text
    assert "cited criterion" in r.text or "criterion" in r.text


def test_screen_post_unknown_record_shows_generic_error(tmp_path: Path) -> None:
    repo = _repo_with_records(tmp_path, [])
    client = _authenticated(_client(repo))
    r = client.post(
        "/screen/title-abstract",
        data={
            "record_id": "rec_nonexistent0000",
            "decision": "include",
            "skip": "",
            "csrf_token": _TOKEN,
        },
    )
    assert r.status_code == 422


def test_screen_queue_advances_after_a_decision(tmp_path: Path) -> None:
    records = [
        _record("rec_0000000000000001", title="First Record"),
        _record("rec_0000000000000002", title="Second Record"),
    ]
    repo = _repo_with_records(tmp_path, records)
    client = _authenticated(_client(repo))

    r1 = client.get("/screen/title-abstract")
    first_shown = "First Record" if "First Record" in r1.text else "Second Record"

    client.post(
        "/screen/title-abstract",
        data={
            "record_id": "rec_0000000000000001"
            if first_shown == "First Record"
            else "rec_0000000000000002",
            "decision": "include",
            "skip": "",
            "csrf_token": _TOKEN,
        },
    )
    r2 = client.get("/screen/title-abstract")
    assert first_shown not in r2.text
    other = "Second Record" if first_shown == "First Record" else "First Record"
    assert other in r2.text
    assert "2 of 2" in r2.text


def test_screen_skip_moves_past_a_record_without_deciding(tmp_path: Path) -> None:
    records = [
        _record("rec_0000000000000001", title="First Record"),
        _record("rec_0000000000000002", title="Second Record"),
    ]
    repo = _repo_with_records(tmp_path, records)
    client = _authenticated(_client(repo))

    r1 = client.get("/screen/title-abstract")
    assert "rec_0000000000000001" in r1.text  # hidden record_id field

    r2 = client.get("/screen/title-abstract?skip=rec_0000000000000001")
    assert "Second Record" in r2.text
    from strata.protocol.screening import all_screen_events

    assert all_screen_events(repo, "title-abstract") == []  # nothing decided


def test_screen_redo_reopens_a_specific_record(tmp_path: Path) -> None:
    records = [_record("rec_0000000000000001", title="Only Record")]
    repo = _repo_with_records(tmp_path, records)
    client = _authenticated(_client(repo))
    client.post(
        "/screen/title-abstract",
        data={
            "record_id": "rec_0000000000000001",
            "decision": "include",
            "skip": "",
            "csrf_token": _TOKEN,
        },
    )
    r = client.get("/screen/title-abstract?redo=rec_0000000000000001")
    assert "Only Record" in r.text


def test_screen_records_a_note(tmp_path: Path) -> None:
    from strata.protocol.screening import all_screen_events

    records = [_record("rec_0000000000000001")]
    repo = _repo_with_records(tmp_path, records)
    client = _authenticated(_client(repo))
    client.post(
        "/screen/title-abstract",
        data={
            "record_id": "rec_0000000000000001",
            "decision": "maybe",
            "note": "double check the sample size",
            "skip": "",
            "csrf_token": _TOKEN,
        },
    )
    repo = open_repo(repo.root)
    events = all_screen_events(repo, "title-abstract")
    assert events[0]["body"]["note"] == "double check the sample size"


@pytest.mark.parametrize("stage", ["title-abstract", "full-text"])
def test_both_configured_stages_are_reachable(tmp_path: Path, stage: str) -> None:
    repo = _repo_with_records(tmp_path, [])
    client = _authenticated(_client(repo))
    r = client.get(f"/screen/{stage}")
    assert r.status_code == 200


def test_screen_shows_a_plain_string_author(tmp_path: Path) -> None:
    """The record schema requires structured `author` objects, so a plain
    string entry can only occur via a hand-edited/pre-schema file on disk
    (openspec:git-integration#git-is-never-the-user-interface: "every invariant is restorable"
    after manual git surgery) -- `_author_display` defends against it
    anyway rather than crashing the whole screening page over one odd
    record."""
    repo = _repo_with_records(tmp_path, [])
    path = repo.path("records", "records.ndjson")
    path.write_text(
        '{"id":"rec_0000000000000001","type":"article-journal",'
        '"title":"T","abstract":"a","author":["Jo Smith"],'
        '"strata":{"canonical":true,"canonical_key":"sig:1","sources":[]}}\n',
        encoding="utf-8",
    )
    client = _authenticated(_client(repo))
    r = client.get("/screen/title-abstract")
    assert "Jo Smith" in r.text


def test_mutating_request_without_a_form_body_is_rejected(tmp_path: Path) -> None:
    repo = _repo_with_records(tmp_path, [])
    client = _authenticated(_client(repo))
    r = client.post(
        "/screen/title-abstract", content=b"{}", headers={"content-type": "application/json"}
    )
    assert r.status_code == 403


def test_screen_post_success_carries_the_skip_list_into_the_redirect(tmp_path: Path) -> None:
    records = [
        _record("rec_0000000000000001", title="First Record"),
        _record("rec_0000000000000002", title="Second Record"),
    ]
    repo = _repo_with_records(tmp_path, records)
    client = _authenticated(_client(repo))
    r = client.post(
        "/screen/title-abstract",
        data={
            "record_id": "rec_0000000000000001",
            "decision": "include",
            "skip": "rec_0000000000000002",
            "csrf_token": _TOKEN,
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "skip=rec_0000000000000002" in r.headers["location"]


# --- openspec:web-ui#configurable-public-url and #health-endpoint ----------------------------


def _public_client(repo, public_url: str, base_url: str) -> TestClient:  # type: ignore[no-untyped-def]
    from strata.web.security import parse_public_url

    app = create_app(
        repo_root=repo.root,
        actor="ethan",
        session_token=_TOKEN,
        host="0.0.0.0",  # noqa: S104 - the bind address inside a container
        port=8765,
        public_url=parse_public_url(public_url),
    )
    return TestClient(app, base_url=base_url)


def test_behind_a_published_port_the_public_host_is_accepted(tmp_path: Path) -> None:
    repo = _repo_with_records(tmp_path, [])
    client = _public_client(repo, "http://localhost:8765", "http://localhost:8765")
    assert client.get(f"/?token={_TOKEN}").status_code == 200


def test_dns_rebinding_is_still_refused_behind_a_public_url(tmp_path: Path) -> None:
    repo = _repo_with_records(tmp_path, [])
    attacker = _public_client(repo, "http://localhost:8765", "http://attacker.example:8765")
    response = attacker.get(f"/?token={_TOKEN}")
    assert response.status_code == 400 and "Host" in response.text
    # nor does the bind address itself get in: only the public URL's host does
    bound = _public_client(repo, "http://localhost:8765", "http://0.0.0.0:8765")  # noqa: S104
    assert bound.get(f"/?token={_TOKEN}").status_code == 400


def test_a_cross_origin_post_is_refused_behind_a_public_url(tmp_path: Path) -> None:
    repo = _repo_with_records(tmp_path, [])
    client = _public_client(repo, "https://strata.example.edu", "https://strata.example.edu")
    ok = client.get(f"/?token={_TOKEN}", headers={"Origin": "https://strata.example.edu"})
    assert ok.status_code == 200
    bad = client.get(f"/?token={_TOKEN}", headers={"Origin": "https://attacker.example"})
    assert bad.status_code == 400 and "Origin" in bad.text


def test_healthz_needs_no_session_and_returns_no_repository_data(tmp_path: Path) -> None:
    repo = _repo_with_records(tmp_path, [_record("rec_0000000000000001")])
    client = _client(repo)
    response = client.get("/healthz")  # no cookie, no token
    assert response.status_code == 200 and response.json() == {"status": "ok"}
    assert "Web Test Review" not in response.text and "rec_" not in response.text
    assert client.head("/healthz").status_code == 200
    # everything else still wants the session
    assert client.get("/").status_code == 403


def test_healthz_answers_whatever_host_the_probe_uses(tmp_path: Path) -> None:
    repo = _repo_with_records(tmp_path, [])
    client = _public_client(repo, "http://localhost:8765", "http://10.0.0.7:8765")
    assert client.get("/healthz").status_code == 200  # an orchestrator calls by pod address


def test_healthz_does_not_count_as_activity(tmp_path: Path) -> None:
    repo = _repo_with_records(tmp_path, [])
    app = create_app(
        repo_root=repo.root, actor="ethan", session_token=_TOKEN, inactivity_timeout=60
    )
    client = TestClient(app, base_url="http://127.0.0.1:8000")
    before = app.state.strata.clock.last_activity
    assert client.get("/healthz").status_code == 200
    assert app.state.strata.clock.last_activity == before


def test_healthz_reports_unavailable_when_the_repository_cannot_be_read(tmp_path: Path) -> None:
    repo = _repo_with_records(tmp_path, [])
    client = _client(repo)
    (repo.root / "strata.toml").unlink()
    response = client.get("/healthz")
    assert response.status_code == 503 and response.json() == {"status": "unavailable"}
