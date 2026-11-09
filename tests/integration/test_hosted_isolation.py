"""Isolation between projects, blinding between users, and remote MCP on a hosted instance
(openspec:hosted-deployment#isolation-between-projects, #blinding-between-users,
#remote-mcp-access)."""

# ruff: noqa: E501

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from strata.core import records as records_mod
from strata.core.manifest import load_manifest_doc, write_manifest
from strata.hosted import accounts
from strata.hosted import members as members_mod
from strata.protocol import screening as screening_mod
from tests.integration._hosted import PASSWORD, Hosted, hosted, post, seed_review

_INIT = {
    "jsonrpc": "2.0", "id": 1, "method": "initialize",
    "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}},
}  # fmt: skip


def _mcp(
    client: TestClient,
    project: str,
    token: str | None,
    method: str,
    params: dict[str, Any] | None = None,
) -> Any:
    headers = {"content-type": "application/json", "accept": "application/json, text/event-stream",
               "mcp-protocol-version": "2025-06-18"}  # fmt: skip
    if token is not None:
        headers["authorization"] = f"Bearer {token}"
    body = (
        _INIT
        if method == "initialize"
        else {"jsonrpc": "2.0", "id": 2, "method": method, "params": params or {}}
    )
    return client.post(f"/p/{project}/mcp", headers=headers, json=body)


def _tool(client: TestClient, project: str, token: str, name: str, **arguments: Any) -> Any:
    response = _mcp(client, project, token, "tools/call", {"name": name, "arguments": arguments})
    assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert not result.get("isError"), result
    # A tool returning a list answers with one content item per element.
    items = [json.loads(item["text"]) for item in result["content"]]
    return (
        items[0] if len(items) == 1 and isinstance(items[0], dict) and name == "status" else items
    )


def _two_projects(tmp_path: Path) -> tuple[Hosted, list[str]]:
    """`spacing` (sam is a member) and `secret-trial` (sam is not), with distinctive data."""
    h = hosted(tmp_path)
    other_seed = seed_review(tmp_path, "other-seed", title="Confidential trial review", first=101)
    h.instance.add_project("secret-trial", remote=str(other_seed.root))
    accounts.add_user(h.instance.store, "zoe", password=PASSWORD)
    members_mod.add_member(h.instance, "secret-trial", "zoe", actor="ethan", role="lead")
    other_ids = sorted(
        r["id"] for r in records_mod.read_records(h.instance.open_project("secret-trial"))
    )
    return h, other_ids


# ----------------------------------------------------------------------- isolation (7.3)


def test_no_route_returns_another_projects_data_to_a_non_member(tmp_path: Path) -> None:
    h, other_ids = _two_projects(tmp_path)
    sam = h.signed_in("sam.okonkwo")
    record = other_ids[0]
    paths = [
        "/", "/records", f"/records/{record}", "/history", "/criteria", "/prisma", "/prisma.svg",
        "/searches", "/dedup", "/studies", "/retrieve", "/extract", "/rob", "/analysis",
        "/screen/title-abstract", "/rescreen/title-abstract", "/adjudicate/title-abstract",
        "/static/style.css", "/-/sync", "/-/members",
    ]  # fmt: skip
    for path in paths:
        response = sam.get(f"/p/secret-trial{path}")
        assert response.status_code == 404, (path, response.status_code)
        assert "Confidential" not in response.text and record not in response.text, path
    for path, data in (
        ("/screen/title-abstract", {"record_id": record, "decision": "include"}),
        (
            "/records/" + record + "/fix",
            {"field": "title", "value": "x", "rationale": "Correcting it."},
        ),
        ("/-/members", {"username": "sam.okonkwo", "actor": "sam", "role": "lead"}),
        ("/-/sync", {"action": "sync"}),
    ):
        response = sam.post(f"/p/secret-trial{path}", data={"csrf_token": "x", **data})
        assert response.status_code == 404, path
    # A record id from the other project, asked for inside one's own, is just unknown.
    own = sam.get(f"/p/spacing/records/{record}")
    assert own.status_code == 404 and "Confidential" not in own.text
    # The same answer as for a project that does not exist at all.
    assert sam.get("/p/no-such-project/").text == sam.get("/p/secret-trial/").text
    # The project list shows only one's own projects.
    assert "Confidential" not in sam.get("/").text
    assert (
        screening_mod.all_screen_events(h.instance.open_project("secret-trial"), "title-abstract")
        == []
    )


def test_mcp_returns_another_projects_data_to_no_one_but_its_members(tmp_path: Path) -> None:
    h, other_ids = _two_projects(tmp_path)
    client = h.client()
    sam_token = accounts.create_api_token(
        h.instance.store, "sam.okonkwo", label="mcp", now=h.clock()
    )
    refused = _mcp(
        client, "secret-trial", sam_token, "tools/call", {"name": "records", "arguments": {}}
    )
    assert refused.status_code == 404 and other_ids[0] not in refused.text
    assert "Confidential" not in refused.text
    zoe_token = accounts.create_api_token(h.instance.store, "zoe", label="mcp", now=h.clock())
    assert [r["id"] for r in _tool(client, "secret-trial", zoe_token, "records")] == other_ids
    assert _mcp(client, "spacing", zoe_token, "tools/list").status_code == 404


# ------------------------------------------------------------------------- remote MCP


def test_an_unauthenticated_mcp_client_is_refused(tmp_path: Path) -> None:
    h = hosted(tmp_path)
    client = h.client()
    for token in (None, "strata_not-a-token"):
        response = _mcp(client, "spacing", token, "initialize")
        assert response.status_code == 401
        assert response.headers["www-authenticate"].startswith("Bearer")
    # A browser session is not an MCP credential, and a disabled account's token stops working.
    sam = h.signed_in("sam.okonkwo")
    assert _mcp(sam, "spacing", None, "initialize").status_code == 401
    token = accounts.create_api_token(h.instance.store, "sam.okonkwo", label="mcp", now=h.clock())
    assert _mcp(client, "spacing", token, "initialize").status_code == 200
    accounts.disable_user(h.instance.store, "sam.okonkwo")
    assert _mcp(client, "spacing", token, "initialize").status_code == 401


def test_remote_mcp_serves_the_read_only_tools_and_nothing_that_writes(tmp_path: Path) -> None:
    h = hosted(tmp_path)
    client = h.client()
    token = accounts.create_api_token(h.instance.store, "olive", label="mcp", now=h.clock())
    listed = _mcp(client, "spacing", token, "tools/list")
    assert listed.status_code == 200
    names = sorted(tool["name"] for tool in listed.json()["result"]["tools"])
    from strata.mcpserver.server import READ_TOOLS, WRITE_TOOLS

    assert names == sorted(READ_TOOLS) and not set(names) & set(WRITE_TOOLS)
    assert _tool(client, "spacing", token, "status")["title"] == "Spacing review"
    called = _mcp(client, "spacing", token, "tools/call", {"name": "screen", "arguments": {}})
    assert "error" in called.json() or called.json()["result"].get("isError")
    # The token is stored only as a hash.
    assert token.encode() not in (h.instance.state_dir / "instance.db").read_bytes()


# ------------------------------------------------------------------------ blinding (7.4)


def _blinding_fixture(tmp_path: Path, *, blind: bool = True) -> tuple[Hosted, str]:
    """`sam` has excluded a record, with a note, and `ethan` (assigned to it too) has not
    decided it."""
    h = hosted(tmp_path)
    if not blind:
        doc = load_manifest_doc(h.repo.root)
        doc["screening"]["blind_reviewers"] = False
        write_manifest(h.repo.root, doc)
        from strata import gitio

        gitio.add_all(h.repo.root)
        gitio.commit(h.repo.root, "config: unblind\n\nStrata-Op: test\nStrata-Actor: ethan\n")
    record = sorted(r["id"] for r in records_mod.read_records(h.repo))[0]
    sam = h.signed_in("sam.okonkwo")
    response = post(sam, "/screen/title-abstract", {
        "record_id": record, "decision": "exclude", "criteria": "EXC-01",
        "note": "SAMS-PRIVATE-REASONING about this one",
    })  # fmt: skip
    assert response.status_code == 303
    h.server.sync.flush("spacing", actor="sam")  # committed, as it would be after a while
    return h, record


def _sams_opinion_shows(text: str) -> bool:
    return "SAMS-PRIVATE-REASONING" in text or "was exclude" in text


@pytest.mark.parametrize("path", ["/", "/records", "/records/{record}", "/history", "/screen/title-abstract",
                                  "/criteria/EXC-01/edit?direction=loosened", "/criteria/EXC-01/retire",
                                  "/adjudicate/title-abstract", "/prisma"])  # fmt: skip
def test_a_screener_never_sees_a_colleagues_opinion_on_an_undecided_record(
    tmp_path: Path, path: str
) -> None:
    h, record = _blinding_fixture(tmp_path)
    ethan = h.signed_in("ethan.g")
    page = ethan.get("/p/spacing" + path.format(record=record))
    assert page.status_code == 200, page.text
    assert not _sams_opinion_shows(page.text)
    if "retire" in path or "edit" in path:
        assert record not in page.text


def _a_resolved_decision_in_the_preview(monkeypatch: pytest.MonkeyPatch, record: str) -> None:
    """Make the impact preview list `record` as a stale exclusion, as it would after the record
    was resolved without ethan (an adjudication, then a new assignment that includes him)."""
    from strata.protocol import rescreen as rescreen_mod

    def preview(repo: Any, **_kwargs: Any) -> list[Any]:
        return [
            rescreen_mod.StaleRecord(
                record, "title-abstract", "exclude", ("EXC-01",), "criterion-retired", 2
            )
        ]

    monkeypatch.setattr(rescreen_mod, "preview_criterion_change_impact", preview)


def test_the_criteria_preview_hides_a_blinded_reviewers_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    h, record = _blinding_fixture(tmp_path)
    _a_resolved_decision_in_the_preview(monkeypatch, record)
    ethan = h.signed_in("ethan.g")
    page = ethan.get("/p/spacing/criteria/EXC-01/retire")
    assert record not in page.text and "was exclude" not in page.text
    # Once ethan has recorded his own decision, there is nothing left to protect.
    post(
        ethan,
        "/screen/title-abstract",
        {"record_id": record, "decision": "exclude", "criteria": "EXC-01"},
    )
    page = ethan.get("/p/spacing/criteria/EXC-01/retire")
    assert record in page.text and "was exclude" in page.text


def test_blinding_is_off_when_the_review_turns_it_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    h, record = _blinding_fixture(tmp_path, blind=False)
    _a_resolved_decision_in_the_preview(monkeypatch, record)
    token = accounts.create_api_token(h.instance.store, "ethan.g", label="mcp", now=h.clock())
    stale = _tool(h.client(), "spacing", token, "preview_criterion_change_impact",
                  criterion_id="EXC-01", direction="loosened", origin="retired")  # fmt: skip
    assert [s["record_id"] for s in stale] == [record]


def test_mcp_never_gives_a_screener_a_colleagues_undecided_record_opinion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    h, record = _blinding_fixture(tmp_path)
    client = h.client()
    ethan_token = accounts.create_api_token(h.instance.store, "ethan.g", label="mcp", now=h.clock())
    for name, arguments in (
        ("why", {"record_id": record}),
        ("records", {}),
        ("log", {}),
        ("status", {}),
        (
            "preview_criterion_change_impact",
            {"criterion_id": "EXC-01", "direction": "loosened", "origin": "retired"},
        ),
    ):
        response = _mcp(
            client, "spacing", ethan_token, "tools/call", {"name": name, "arguments": arguments}
        )
        assert response.status_code == 200
        assert "SAMS-PRIVATE-REASONING" not in response.text, name
    _a_resolved_decision_in_the_preview(monkeypatch, record)
    stale = _tool(client, "spacing", ethan_token, "preview_criterion_change_impact",
                  criterion_id="EXC-01", direction="loosened", origin="retired")  # fmt: skip
    assert stale == []
    # An observer screens nothing, so there is no independent judgement of theirs to protect.
    olive_token = accounts.create_api_token(h.instance.store, "olive", label="mcp", now=h.clock())
    seen = _tool(client, "spacing", olive_token, "preview_criterion_change_impact",
                 criterion_id="EXC-01", direction="loosened", origin="retired")  # fmt: skip
    assert [s["record_id"] for s in seen] == [record]


def test_blinded_records_are_the_reviewers_own_undecided_queue(tmp_path: Path) -> None:
    from strata.protocol import blinding

    h, record = _blinding_fixture(tmp_path)
    repo = h.repo
    assert record in blinding.blinded_records(repo, "ethan")["title-abstract"]
    assert record not in blinding.blinded_records(repo, "sam")["title-abstract"]
    assert blinding.blinded_records(repo, "olive") == {
        "title-abstract": frozenset(),
        "full-text": frozenset(),
    }
    items = [
        {"stage": "title-abstract", "record_id": record},
        {"stage": "title-abstract", "record_id": "rec_unknown"},
    ]
    assert blinding.visible(items, blinding.blinded_records(repo, "ethan")) == [items[1]]


def test_remote_mcp_offers_no_write_tool_even_when_the_review_enables_ai(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """openspec:hosted-deployment#remote-mcp-access: remote MCP stays unable to commit a decision,
    whatever the review's AI policy lets a local server offer."""
    from strata.core import agents as agents_mod
    from strata.mcpserver.server import WRITE_TOOLS

    h = hosted(tmp_path)
    monkeypatch.setattr(agents_mod, "is_enabled", lambda repo: True)
    token = accounts.create_api_token(h.instance.store, "ethan.g", label="mcp", now=h.clock())
    listed = _mcp(h.client(), "spacing", token, "tools/list").json()["result"]["tools"]
    assert listed and not {tool["name"] for tool in listed} & set(WRITE_TOOLS)
