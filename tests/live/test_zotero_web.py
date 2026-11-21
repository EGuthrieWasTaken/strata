"""`strata`'s Zotero integration against the real Web API (`api.zotero.org`).

Covers openspec:zotero-integration (transport selection, identity mapping, append-only meets
mutable) against the throwaway account the captures in `tests/fixtures/zotero/captured/10/` came
from (`docs/zotero-real-run.md`). Needs `STRATA_ZOTERO_API_KEY`, a key for that account that can
write; without it every test here is skipped.

What the account must hold, as the first real run left it: a personal library with a collection
`strata-test` whose items include Cepeda et al. (2008) and Roediger & Karpicke (2006) with their
DOIs, and a group library. The tests add to it only what they remove again, plus collection
membership in `strata-ci` for an item strata did not create.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from strata.integrations.reference_manager import ItemRef
from strata.integrations.zotero import operations as zotero_ops
from strata.integrations.zotero.connect import Connection, connect
from strata.integrations.zotero.csl import read_csl
from strata.integrations.zotero.manager import list_libraries
from tests.integration._zotero import CEPEDA, ONLY_HERE, ROEDIGER, review_with
from tests.unit._m3 import decide
from tests.unit._zotero import MemoryKeystore

KEY_VAR = "STRATA_ZOTERO_API_KEY"
WHY = "the nightly check of the Zotero link against the real Web API"
CI_COLLECTION = "strata-ci"

pytestmark = pytest.mark.skipif(
    not os.environ.get(KEY_VAR), reason=f"needs ${KEY_VAR} (a key for the throwaway account)"
)


def _connect(preference: str = "web", need_write: bool = False) -> Connection:
    return connect(
        preference,
        need_write=need_write,
        store=MemoryKeystore(available_=False),
        environ={KEY_VAR: os.environ[KEY_VAR]},
    )


def _connector(preference: str, need_write: bool) -> Connection:
    # The runner has no Zotero desktop: whatever the link asks for, the Web API answers.
    return _connect("web", need_write)


@pytest.fixture(scope="module")
def web() -> Connection:
    return _connect()


def test_the_key_names_its_account_and_can_write_to_it(web: Connection) -> None:
    assert web.key_info is not None
    assert web.key_info.username == "strata-review"
    assert web.key_info.can_write(web.personal_library)


def test_the_libraries_include_the_group(web: Connection) -> None:
    libraries = list_libraries(web.api, web.personal_library, local=False)

    assert libraries[0].library == web.personal_library
    assert any(lib.library.startswith("groups/") for lib in libraries[1:])


def test_every_item_in_the_library_is_read(web: Connection) -> None:
    raw = list(web.api.get_pages(f"/{web.personal_library}/items/top", {"include": "data,csljson"}))
    items = web.manager(web.personal_library).all_items()

    bibliographic = [
        obj for page in raw for obj in page if obj["data"]["itemType"] not in {"note", "attachment"}
    ]
    assert len(items) == len(bibliographic) > 0
    for item in items:
        issued = item.csl.get("issued", {}).get("date-parts", [[0]])
        assert all(isinstance(part, int) for row in issued for part in row), item.ref.key
    assert all(read_csl(obj["csljson"]) is not None for obj in bibliographic)


def test_link_pull_and_status_through_the_web_api(tmp_path: Path, web: Connection) -> None:
    repo, ids = review_with(tmp_path, CEPEDA, ROEDIGER)

    linked = zotero_ops.link(
        repo,
        actor="ethan",
        connector=_connector,
        library=web.personal_library,
        web=True,
        rationale=WHY,
    )
    assert linked.write is True
    assert {m.record_id: m.via for m in linked.report.matched}.items() >= {
        ids[0]: "doi",
        ids[1]: "doi",
    }.items()

    pulled = zotero_ops.pull(
        repo,
        actor="ethan",
        connector=_connector,
        collection="strata-test",
        via="website",
        rationale=WHY,
    )
    assert pulled.items_pulled >= 9 and pulled.rejected == ()
    assert pulled.already_linked >= 2

    status = zotero_ops.status(repo, connector=_connector)
    assert status.unreachable is None and status.stale == ()


def _collection_key(web: Connection, name: str) -> str:
    manager = web.manager(web.personal_library, writable=True)
    for collection in manager.collections():
        if collection.name == name:
            return collection.key
    made = web.api.request(
        "POST", f"/{web.personal_library}/collections", body=[{"name": name}]
    ).json()
    return str(made["successful"]["0"]["key"])


def _top_keys(web: Connection) -> set[str]:
    return {i.ref.key for i in web.manager(web.personal_library).all_items()}


def test_a_push_adds_membership_creates_what_is_missing_and_deletes_nothing(
    tmp_path: Path, web: Connection
) -> None:
    _collection_key(web, CI_COLLECTION)
    before = _top_keys(web)
    repo, ids = review_with(tmp_path, CEPEDA, ONLY_HERE)
    decide(repo, "title-abstract", ids)
    decide(repo, "full-text", ids)
    zotero_ops.link(
        repo,
        actor="ethan",
        connector=_connector,
        library=web.personal_library,
        web=True,
        rationale=WHY,
    )

    result = zotero_ops.push(
        repo,
        actor="ethan",
        connector=_connector,
        set_name="included",
        collection=CI_COLLECTION,
        rationale=WHY,
    )

    outcomes = {o.record_id: o for o in result.outcomes}
    created = outcomes[ids[1]]
    try:
        assert outcomes[ids[0]].status in {"added", "unchanged"}  # unchanged on a later night
        assert created.status == "created" and created.ref is not None
        after = _top_keys(web)
        assert after == before | {created.ref.key}  # nothing strata did not create went away
        cepeda = web.manager(web.personal_library).resolve([outcomes[ids[0]].ref])  # type: ignore[list-item]
        assert all(r.present for r in cepeda.values())
    finally:
        if created.ref is not None and created.version is not None:
            _delete(web, created.ref)


def _delete(web: Connection, ref: ItemRef) -> None:
    current = web.api.get_json(f"/{web.personal_library}/items/{ref.key}")
    web.api.request(
        "DELETE",
        f"/{web.personal_library}/items/{ref.key}",
        headers={"If-Unmodified-Since-Version": str(current["version"])},
    )
