"""`ZoteroManager`: reading a library, resolving attachments, and pushing into a collection
(openspec:zotero-integration#append-only-meets-mutable, #retrieval-through-zotero)."""

from __future__ import annotations

from typing import Any

import pytest

from strata.integrations.reference_manager import ItemRef, PushItem
from strata.integrations.zotero.api import ZoteroError, ZoteroNotFoundError
from strata.integrations.zotero.manager import (
    BATCH,
    ZoteroManager,
    key_info,
    list_libraries,
)
from tests.unit._zotero import local_api, local_manager, web_api, web_manager
from tests.zotero_fake import FakeZotero

LIB = "users/12345"


def _ref(key: str) -> ItemRef:
    return ItemRef(LIB, key)


def _journal_csl(title: str = "A new trial", **fields: Any) -> dict[str, Any]:
    return {
        "type": "article-journal",
        "title": title,
        "author": [{"family": "Okonkwo", "given": "Ada"}],
        "container-title": "Journal of Trials",
        "volume": "4",
        "page": "10-20",
        "DOI": "10.1000/new.1",
        "issued": {"date-parts": [[2020, 5]]},
        **fields,
    }


# --------------------------------------------------------------------------------- collections


def test_collections_are_listed_and_found_by_name_or_key() -> None:
    manager = web_manager(FakeZotero())

    assert {c.name for c in manager.collections()} >= {"Included studies", "Hand-searched trials"}
    assert manager.find_collection("Included studies").key == "INCLUDED"
    assert manager.find_collection("HANDPICK").name == "Hand-searched trials"


def test_an_ambiguous_collection_name_is_an_error_naming_the_keys_not_a_guess() -> None:
    with pytest.raises(ZoteroError, match="2 collections are named 'Reading list'.*SAMENAME"):
        web_manager(FakeZotero()).find_collection("Reading list")


def test_a_missing_collection_lists_the_ones_there_are() -> None:
    with pytest.raises(ZoteroNotFoundError, match="Hand-searched trials"):
        web_manager(FakeZotero()).find_collection("Nope")


# ------------------------------------------------------------------------------------- pulling


@pytest.mark.parametrize("transport", ["local", "web"])
def test_a_collection_is_pulled_as_items_with_csl_versions_and_collections(
    transport: str,
) -> None:
    fake = FakeZotero("7")
    manager = local_manager(fake) if transport == "local" else web_manager(fake)

    pulled = manager.pull("Hand-searched trials")

    assert pulled.collection.key == "HANDPICK"
    assert [i.ref.key for i in pulled.items] == ["AB3D9XYZ", "CD4E5FGH", "JK6L7MNP"]
    cepeda = pulled.items[0]
    assert cepeda.version == 8842
    assert cepeda.collections == ("HANDPICK",)
    assert cepeda.csl["DOI"] == "10.1111/j.1467-9280.2008.02209.x"
    assert "id" not in cepeda.csl  # Zotero's own id is not a strata record id


def test_the_local_api_addresses_the_personal_library_as_users_0() -> None:
    fake = FakeZotero("7")
    local_manager(fake).pull("Hand-searched trials")

    assert all("/users/0/" in r.path for r in fake.requests)


def test_every_top_level_item_is_read_and_attachments_are_not_items() -> None:
    items = web_manager(FakeZotero()).all_items()

    assert [i.ref.key for i in items] == ["AB3D9XYZ", "CD4E5FGH", "JK6L7MNP", "QR8S2TUV"]


def test_a_group_library_is_read_in_its_own_right() -> None:
    manager = web_manager(FakeZotero(), "groups/777")

    assert [i.ref.key for i in manager.pull("Shared trials").items] == ["GR0UPAAA"]


def test_libraries_are_the_personal_one_and_each_group() -> None:
    libraries = list_libraries(web_api(FakeZotero()), "users/12345", local=False)

    assert [(lib.library, lib.name) for lib in libraries] == [
        ("users/12345", "My Library"),
        ("groups/777", "Lab reading group"),
    ]


def test_what_a_key_may_write_is_read_from_zotero() -> None:
    info = key_info(web_api(FakeZotero(key_can_write=True, group_can_write=False)))

    assert info.user_id == 12345
    assert info.can_write("users/12345") is True
    assert info.can_write("groups/777") is False
    assert key_info(web_api(FakeZotero(key_can_write=False))).can_write("users/12345") is False


# ----------------------------------------------------------------------------------- resolving


def test_resolving_finds_the_pdf_and_ignores_snapshots_and_links() -> None:
    manager = local_manager(FakeZotero("7"))

    resolved = manager.resolve([_ref("AB3D9XYZ"), _ref("CD4E5FGH"), _ref("JK6L7MNP")])

    assert resolved["AB3D9XYZ"].pdf is not None and resolved["AB3D9XYZ"].pdf.key == "PDF1AAAA"
    # CD4E5FGH has an HTML snapshot and a link to a web page: neither is a file to read
    assert resolved["CD4E5FGH"].present and resolved["CD4E5FGH"].attachments[0].key == "HTM2BBBB"
    assert resolved["CD4E5FGH"].pdf is None
    assert resolved["JK6L7MNP"].present and resolved["JK6L7MNP"].attachments == ()


def test_an_item_deleted_in_zotero_resolves_as_absent_not_as_an_error() -> None:
    fake = FakeZotero()
    fake.delete_item(LIB, "AB3D9XYZ")

    resolved = web_manager(fake).resolve([_ref("AB3D9XYZ"), _ref("CD4E5FGH")])

    assert resolved["AB3D9XYZ"].present is False
    assert resolved["AB3D9XYZ"].version is None and resolved["AB3D9XYZ"].attachments == ()
    assert resolved["CD4E5FGH"].present is True


def test_many_items_are_resolved_from_one_listing_of_attachments_not_a_request_each() -> None:
    fake = FakeZotero()
    for n in range(6):
        fake.add_item(LIB, f"EXTRA00{n}", f"Extra item {n}")
    refs = [_ref(k) for k in ("AB3D9XYZ", "CD4E5FGH", "JK6L7MNP", "QR8S2TUV")]
    refs += [_ref(f"EXTRA00{n}") for n in range(6)]  # ten items: past the few-items shortcut

    resolved = web_manager(fake).resolve(refs)

    assert resolved["AB3D9XYZ"].pdf is not None
    assert not any("/children" in r.path for r in fake.requests)
    assert sum(r.query.get("itemType") == "attachment" for r in fake.requests) == 1


def test_a_few_items_are_asked_about_one_by_one() -> None:
    fake = FakeZotero()

    web_manager(fake).resolve([_ref("AB3D9XYZ")])

    assert any(r.path.endswith("/items/AB3D9XYZ/children") for r in fake.requests)


def test_keys_are_looked_up_in_batches_within_the_apis_limit() -> None:
    fake = FakeZotero()
    refs = [_ref(f"KEY{n:05d}") for n in range(BATCH + 20)]

    web_manager(fake).resolve(refs)

    lookups = [r for r in fake.requests if "itemKey" in r.query]
    assert [len(r.query["itemKey"].split(",")) for r in lookups] == [BATCH, 20]


# ---------------------------------------------------------------------------------------- open


def test_the_uris_that_open_an_item_or_its_pdf_in_zotero() -> None:
    manager = web_manager(FakeZotero())

    assert manager.open(_ref("AB3D9XYZ")) == "zotero://select/library/items/AB3D9XYZ"
    assert (
        manager.open(_ref("AB3D9XYZ"), attachment="PDF1AAAA")
        == "zotero://open-pdf/library/items/PDF1AAAA"
    )
    group = ItemRef("groups/777", "GR0UPAAA")
    assert manager.open(group) == "zotero://select/groups/777/items/GR0UPAAA"
    assert (
        manager.open(group, attachment="ZZZZZZZZ") == "zotero://open-pdf/groups/777/items/ZZZZZZZZ"
    )


# ------------------------------------------------------------------------------------ pushing


def test_a_record_zotero_lacks_becomes_a_new_item_built_on_zoteros_own_template() -> None:
    fake = FakeZotero()
    manager = web_manager(fake)

    (outcome,) = manager.push([PushItem("rec_a", _journal_csl(PMID="12345"))], "Included studies")

    assert outcome.status == "created" and outcome.ref == _ref("NEW00001")
    (write,) = fake.writes()
    (sent,) = write.body
    assert sent["itemType"] == "journalArticle"
    assert sent["title"] == "A new trial"
    assert sent["publicationTitle"] == "Journal of Trials"
    assert sent["pages"] == "10-20" and sent["date"] == "2020-05" and sent["DOI"] == "10.1000/new.1"
    assert sent["creators"] == [
        {"creatorType": "author", "firstName": "Ada", "lastName": "Okonkwo"}
    ]
    assert sent["extra"] == "PMID: 12345"  # no PMID field in Zotero: kept where Zotero keeps such
    assert sent["collections"] == ["INCLUDED"]
    assert set(sent) <= set(fake.templates["journalArticle"])  # only fields the type has
    assert write.headers["zotero-write-token"]  # so a retried POST cannot create twice


def test_a_type_zotero_has_no_template_for_is_filed_as_a_document() -> None:
    fake = FakeZotero()

    web_manager(fake).push(
        [PushItem("rec_a", _journal_csl(type="dataset", **{"container-title": "Journal X"}))],
        "Included studies",
    )

    (sent,) = fake.writes()[0].body
    assert sent["itemType"] == "document"
    assert "publicationTitle" not in sent
    # nothing is lost: what the document type has no slot for is kept in `extra`
    assert "container-title: Journal X" in sent["extra"].splitlines()
    assert "DOI: 10.1000/new.1" in sent["extra"].splitlines()


def test_an_item_already_in_zotero_is_only_added_to_the_collection() -> None:
    fake = FakeZotero()
    manager = web_manager(fake)
    existing = PushItem("rec_a", _journal_csl(), existing=_ref("JK6L7MNP"), existing_version=7000)

    (outcome,) = manager.push([existing], "Included studies")

    stored = fake.libraries[LIB].items["JK6L7MNP"]
    assert outcome.status == "added"
    assert outcome.version == stored["version"] and outcome.version > 7000  # the new version
    (write,) = fake.writes()
    # the item's other collections are kept, and nothing about it but its collections is sent
    assert write.body == [
        {"key": "JK6L7MNP", "version": 7000, "collections": ["HANDPICK", "INCLUDED"]}
    ]
    assert fake.libraries[LIB].items["JK6L7MNP"]["csl"]["title"].startswith("Spacing effects")


def test_an_item_already_in_the_collection_is_left_alone() -> None:
    fake = FakeZotero()
    existing = PushItem("rec_a", _journal_csl(), existing=_ref("CD4E5FGH"), existing_version=9001)

    (outcome,) = web_manager(fake).push([existing], "Included studies")

    assert outcome.status == "unchanged"
    assert fake.writes() == []


def test_an_item_edited_in_zotero_since_strata_saw_it_is_refused_and_not_written() -> None:
    fake = FakeZotero()
    fake.edit_item(LIB, "JK6L7MNP", title="Corrected title")
    existing = PushItem("rec_a", _journal_csl(), existing=_ref("JK6L7MNP"), existing_version=7000)

    (outcome,) = web_manager(fake).push([existing], "Included studies")

    assert outcome.status == "refused"
    assert outcome.detail is not None and "edited in Zotero" in outcome.detail
    assert "7000" in outcome.detail and "pull it" in outcome.detail
    assert fake.writes() == []
    assert fake.libraries[LIB].items["JK6L7MNP"]["collections"] == ["HANDPICK"]


def test_an_item_edited_in_the_instant_between_the_check_and_the_write_is_still_refused() -> None:
    fake = FakeZotero()
    manager = web_manager(fake)
    first_lookup = {"done": False}
    real = fake.request

    def racing(method, url, headers, body, timeout):  # type: ignore[no-untyped-def]
        response = real(method, url, headers, body, timeout)
        if "itemKey" in url and not first_lookup["done"]:
            first_lookup["done"] = True
            fake.edit_item(LIB, "JK6L7MNP", title="Edited in the meantime")
        return response

    fake.request = racing  # type: ignore[method-assign]
    existing = PushItem("rec_a", _journal_csl(), existing=_ref("JK6L7MNP"), existing_version=7000)

    (outcome,) = manager.push([existing], "Included studies")

    assert outcome.status == "refused"  # Zotero's own version check, not strata's, caught it
    assert outcome.detail is not None and "modified since specified version" in outcome.detail
    assert fake.libraries[LIB].items["JK6L7MNP"]["collections"] == ["HANDPICK"]


def test_a_mapped_item_deleted_in_zotero_is_reported_stale_not_recreated() -> None:
    fake = FakeZotero()
    fake.delete_item(LIB, "JK6L7MNP")
    existing = PushItem("rec_a", _journal_csl(), existing=_ref("JK6L7MNP"), existing_version=7000)

    (outcome,) = web_manager(fake).push([existing], "Included studies")

    assert outcome.status == "stale"
    assert fake.writes() == []


def test_a_push_never_deletes_and_never_sends_more_than_membership_for_an_existing_item() -> None:
    fake = FakeZotero()
    items = [
        PushItem("rec_new", _journal_csl()),
        PushItem("rec_a", _journal_csl(), existing=_ref("JK6L7MNP"), existing_version=7000),
        PushItem("rec_b", _journal_csl(), existing=_ref("AB3D9XYZ"), existing_version=8842),
        PushItem("rec_c", _journal_csl(), existing=_ref("CD4E5FGH"), existing_version=9001),
    ]

    outcomes = web_manager(fake).push(items, "Included studies")

    assert [o.status for o in outcomes] == ["created", "added", "added", "unchanged"]
    assert {r.method for r in fake.requests} <= {"GET", "POST"}  # no DELETE, PUT or PATCH
    for write in fake.writes():
        for sent in write.body:
            if "key" in sent:
                assert set(sent) == {"key", "version", "collections"}
    before = {k: i["csl"]["title"] for k, i in fake.libraries[LIB].items.items()}
    assert before["AB3D9XYZ"].startswith("Spacing effects")  # the existing items' content is intact
    assert "CD4E5FGH" in fake.libraries[LIB].items  # nothing removed


def test_the_guard_refuses_to_send_content_for_an_item_strata_did_not_create() -> None:
    update = {"key": "AB3D9XYZ", "version": 1, "collections": ["INCLUDED"], "title": "Overwritten"}
    item = PushItem("rec_a", _journal_csl(), existing=_ref("AB3D9XYZ"), created_by_strata=False)

    with pytest.raises(ZoteroError, match=r"refusing to change \['title'\]"):
        ZoteroManager._check_membership_only(item, update)
    # An item strata made itself is not guarded by this check (a push still only sends membership).
    ZoteroManager._check_membership_only(
        PushItem("rec_a", {}, existing=_ref("AB3D9XYZ"), created_by_strata=True), update
    )


def test_many_records_are_written_in_batches_within_the_apis_limit() -> None:
    fake = FakeZotero()
    items = [
        PushItem(f"rec_{n}", _journal_csl(f"Trial {n}", DOI=f"10.1000/{n}")) for n in range(120)
    ]

    outcomes = web_manager(fake).push(items, "Included studies")

    assert [len(w.body) for w in fake.writes()] == [BATCH, BATCH, 20]
    assert all(o.status == "created" for o in outcomes)
    assert len({o.ref.key for o in outcomes if o.ref}) == 120
    assert sum(r.path == "/items/new" for r in fake.requests) == 1  # the template is fetched once


def test_a_manager_whose_link_cannot_write_refuses_before_sending_anything() -> None:
    fake = FakeZotero()

    with pytest.raises(ZoteroError, match="cannot write"):
        web_manager(fake, writable=False).push(
            [PushItem("rec_a", _journal_csl())], "Included studies"
        )

    assert fake.requests == []


def test_a_key_without_write_access_is_refused_by_zotero_itself() -> None:
    fake = FakeZotero(key_can_write=False)

    with pytest.raises(ZoteroError, match="lacks permission"):
        web_manager(fake).push([PushItem("rec_a", _journal_csl())], "Included studies")


def test_the_local_api_cannot_write() -> None:
    fake = FakeZotero("7")
    manager = ZoteroManager(local_api(fake), LIB, local=True, writable=True)

    with pytest.raises(ZoteroError, match="local API is read-only"):
        manager.push([PushItem("rec_a", _journal_csl())], "Included studies")
    assert fake.writes() == []


# ------------------------------------------------------------------- replies of an unknown shape


class _Canned:
    """A Zotero whose every reply to a path is the JSON given, whatever was asked."""

    def __init__(self, replies: dict[str, Any]) -> None:
        self.replies = replies

    def request(self, method, url, headers, body, timeout):  # type: ignore[no-untyped-def]
        import json
        import urllib.parse

        from strata.integrations.zotero.http import HttpResponse

        path = urllib.parse.urlsplit(url).path
        for suffix, payload in self.replies.items():
            if path.endswith(suffix):
                return HttpResponse(200, {}, json.dumps(payload).encode())
        return HttpResponse(404, {}, b"")


def _canned_manager(replies: dict[str, Any]) -> ZoteroManager:
    from strata.integrations.zotero.api import WEB_BASE_URL, ZoteroApi

    api = ZoteroApi(WEB_BASE_URL, _Canned(replies), api_key="K", sleep=lambda _s: None)
    return ZoteroManager(api, LIB, local=False, writable=True)


@pytest.mark.parametrize(
    "call",
    [
        lambda m: m.collections(),
        lambda m: m.all_items(),
        lambda m: m.pull("Whatever"),
        lambda m: m.resolve([_ref("AB3D9XYZ")]),
    ],
    ids=["collections", "all_items", "pull", "resolve"],
)
def test_a_reply_of_a_shape_strata_does_not_know_is_an_error_that_says_so(call: Any) -> None:
    manager = _canned_manager(
        {
            "/collections": [{"unexpected": True}],
            "/items/top": [{"unexpected": True}],
            "/items": [{"unexpected": True}],
        }
    )

    with pytest.raises(
        ZoteroError,
        match="could not read.*version of Zotero strata does not know|without its CSL-JSON",
    ):
        call(manager)


def test_a_key_reply_that_is_not_a_mapping_is_an_error_that_says_so() -> None:
    from strata.integrations.zotero.api import WEB_BASE_URL, ZoteroApi

    api = ZoteroApi(WEB_BASE_URL, _Canned({"/keys/current": ["nope"]}), api_key="K")

    with pytest.raises(ZoteroError):
        key_info(api)
