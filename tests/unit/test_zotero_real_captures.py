"""What a running Zotero really sent, read by `strata`'s own code.

Covers openspec:zotero-integration (task 5.1: tests pinned per Zotero major version). The other
Zotero tests talk to `tests/zotero_fake.py`; these replay responses captured from a running
Zotero 10.0.8 and from `api.zotero.org` (`tests/fixtures/zotero/captured/10/`, described in
`docs/zotero-real-run.md`), so a reader that only suits the fake fails here.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from strata.integrations.reference_manager import ItemRef, PushItem
from strata.integrations.zotero import launch
from strata.integrations.zotero.api import LOCAL_BASE_URL, WEB_BASE_URL, ZoteroApi
from strata.integrations.zotero.csl import read_csl
from strata.integrations.zotero.http import HttpResponse
from strata.integrations.zotero.manager import ZoteroManager, key_info
from strata.integrations.zotero.probe import probe_local
from tests.unit._zotero import Sleeper

CAPTURED = Path(__file__).parent.parent / "fixtures" / "zotero" / "captured" / "10"
LIB = "users/22585168"


def _capture(name: str) -> dict[str, Any]:
    return json.loads((CAPTURED / name).read_text(encoding="utf-8"))  # type: ignore[no-any-return]


class Replay:
    """A transport that answers each request, in order, with a captured response."""

    def __init__(self, *names: str) -> None:
        self.responses = [_capture(name)["response"] for name in names]
        self.sent: list[tuple[str, str, Any]] = []

    def request(
        self,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout: float,
    ) -> HttpResponse:
        self.sent.append((method, url, json.loads(body) if body else None))
        response = self.responses.pop(0)
        raw = response["body"]
        payload = raw if response["body_encoding"] == "text" else json.dumps(raw)
        return HttpResponse(
            response["status"],
            {name.lower(): value for name, value in response["headers"]},
            payload.encode("utf-8"),
        )


def _local(*names: str) -> ZoteroManager:
    return ZoteroManager(
        ZoteroApi(LOCAL_BASE_URL, Replay(*names), sleep=Sleeper()), LIB, local=True
    )


def _web(replay: Replay) -> ZoteroManager:
    api = ZoteroApi(WEB_BASE_URL, replay, api_key="k", sleep=Sleeper())
    return ZoteroManager(api, LIB, local=False, writable=True)


# ------------------------------------------------------------------------------- reading


def test_the_desktop_apps_items_are_read_though_their_csl_json_is_a_string() -> None:
    raw = _capture("local/personal/items-top-data-csljson.json")["response"]["body"]
    assert all(isinstance(item["csljson"], str) for item in raw)  # what Zotero 10 sends

    items = _local("local/personal/items-top-data-csljson.json").all_items()

    assert len(items) == len(raw) == 12
    cepeda = next(i for i in items if i.ref.key == "BEITJ9RM")
    assert cepeda.csl["type"] == "article-journal" and "id" not in cepeda.csl
    assert cepeda.csl["issued"] == {"date-parts": [[2008, 11]]}  # sent as [["2008", 11]]
    # the app's item versions are its own, so none is recorded as one strata can compare
    assert {i.version for i in items} == {0}


def test_the_probe_accepts_the_desktop_app_and_says_when_it_is_switched_off() -> None:
    on, why = probe_local(Replay("local/personal/items-top-data-csljson.json"))
    off, why_not = probe_local(Replay("local/off/items-top.json"))

    assert on is not None and on.library == LIB and why == ""
    assert off is None and "switched off" in why_not


def test_the_web_apis_items_keep_their_versions() -> None:
    items = _web(Replay("web/personal/items-top-data-csljson.json")).all_items()

    versions = {i.ref.key: i.version for i in items}
    assert versions["BEITJ9RM"] == 4 and versions["G9PKINI3"] == 20


def test_a_date_zotero_could_not_parse_does_not_stop_the_item_being_read() -> None:
    web = _capture("web/personal/item-hedges-olkin-nonISO-date.json")["response"]["body"]
    local = _capture("local/personal/item-hedges-olkin-nonISO-date.json")["response"]["body"]
    assert web["data"]["date"] == "11/1984"
    assert web["csljson"]["issued"] == {"date-parts": [["1984"]]}  # a string, month dropped

    assert read_csl(web["csljson"])["issued"] == {"date-parts": [[1984]]}  # type: ignore[index]
    assert read_csl(local["csljson"])["issued"] == {"date-parts": [[1984, 11]]}  # type: ignore[index]


def test_a_pmid_is_read_from_a_native_field_and_from_extra() -> None:
    native = _capture("web/write/get-native-pmid-item-with-csljson.json")["response"]["body"]
    items = _web(Replay("web/personal/items-top-data-csljson.json")).all_items()
    in_extra = next(i for i in items if i.ref.key == "BEITJ9RM")

    assert read_csl(native["csljson"])["PMID"] == "99999991"  # type: ignore[index]
    # `extra: "PMID: 19076480"` reaches CSL-JSON as `note`, never as `PMID`
    assert in_extra.csl["note"] == "PMID: 19076480" and in_extra.csl["PMID"] == "19076480"


def test_the_key_report_is_read() -> None:
    info = key_info(ZoteroApi(WEB_BASE_URL, Replay("web/keys-current.json"), api_key="k"))

    assert info.user_id == 22585168 and info.username == "strata-review"
    assert info.can_write(LIB) and info.can_write("groups/6762415")


# ------------------------------------------------------------------------------- writing


def test_a_new_item_uses_the_native_pmid_field_where_the_real_template_has_one() -> None:
    replay = Replay(
        "web/personal/items-new-journalArticle.json", "web/personal/items-new-thesis.json"
    )
    manager = _web(replay)
    csl = {"title": "T", "PMID": "123", "DOI": "10.1/x", "issued": {"date-parts": [[2020, 5]]}}

    article = manager._new_item({**csl, "type": "article-journal"}, "COLL0001")
    thesis = manager._new_item({**csl, "type": "thesis"}, "COLL0001")

    assert article["PMID"] == "123" and "extra" not in article
    assert thesis["extra"] == "PMID: 123" and "PMID" not in thesis  # only articles have the field
    assert thesis["DOI"] == "10.1/x" and article["date"] == "2020-05"


def test_a_created_item_and_a_refused_one_are_read_from_the_real_write_replies() -> None:
    manager = _web(Replay("web/write/post-items-create-ok.json"))
    (created,) = manager._write(
        [(0, {"itemType": "journalArticle"})], [PushItem("rec_a", {"title": "T"})]
    ).values()
    assert (created.status, created.ref, created.version) == (
        "created",
        ItemRef(LIB, "6HPCSR64"),
        24,
    )

    # one request, two objects: the first unchanged, the second edited since the version sent
    manager = _web(Replay("web/write/post-items-stale-version-mixed-batch.json"))
    held = [
        PushItem("rec_a", {}, existing=ItemRef(LIB, "G9PKINI3"), existing_version=20),
        PushItem("rec_b", {}, existing=ItemRef(LIB, "BEITJ9RM"), existing_version=1),
    ]
    outcomes = manager._write(
        [(0, {"key": "G9PKINI3", "version": 20}), (1, {"key": "BEITJ9RM", "version": 1})], held
    )
    assert outcomes[0].status == "unchanged"
    assert outcomes[1].status == "refused"  # a per-object 412 inside a 200, with no key in it
    assert "modified since specified version" in (outcomes[1].detail or "")


# ------------------------------------------------------------------------------- opening


def test_a_zotero_link_goes_to_the_operating_system_not_the_browser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ran: list[list[str]] = []
    browser: list[str] = []
    monkeypatch.setattr(launch.sys, "platform", "linux")
    monkeypatch.setattr(launch.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(
        launch.subprocess,
        "run",
        lambda argv, **_: ran.append(argv) or subprocess.CompletedProcess(argv, 0),
    )
    monkeypatch.setattr(launch.webbrowser, "open", lambda uri: browser.append(uri) or True)

    assert launch.open_link("zotero://select/library/items/BEITJ9RM") is True
    assert ran == [["/usr/bin/xdg-open", "zotero://select/library/items/BEITJ9RM"]]
    assert browser == []

    # with no opener on the machine, the browser is the fallback
    monkeypatch.setattr(launch.shutil, "which", lambda name: None)
    assert launch.open_link("zotero://select/library/items/BEITJ9RM") is True
    assert browser == ["zotero://select/library/items/BEITJ9RM"]
