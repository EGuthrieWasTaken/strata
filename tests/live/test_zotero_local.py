"""`strata`'s Zotero integration against a real Zotero desktop app's local API.

Covers openspec:zotero-integration#transport-selection for the supported Zotero (10 or later).
`.github/workflows/zotero-live.yml` downloads the current Zotero, starts it under a virtual
display with the local API switched on, and saves the items in `SEEDED` through its connector
endpoint (the local API itself needs a per-program permission to write). Needs
`STRATA_ZOTERO_LOCAL=1`; without it every test here is skipped.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from strata.integrations.zotero import mapping as mapping_mod
from strata.integrations.zotero import operations as zotero_ops
from strata.integrations.zotero.connect import Connection, connect, make_http_transport
from strata.integrations.zotero.probe import probe_local
from tests.integration._zotero import CEPEDA, review_with
from tests.unit._zotero import MemoryKeystore

WHY = "the nightly check of the Zotero link against a real Zotero desktop app"

pytestmark = pytest.mark.skipif(
    not os.environ.get("STRATA_ZOTERO_LOCAL"),
    reason="needs a running Zotero (STRATA_ZOTERO_LOCAL=1)",
)


def _connector(preference: str, need_write: bool) -> Connection:
    return connect(
        "local", need_write=need_write, store=MemoryKeystore(available_=False), environ={}
    )


def test_the_probe_accepts_the_running_zotero() -> None:
    local, why = probe_local(make_http_transport())

    assert local is not None, why


def test_the_seeded_items_are_read_with_their_csl_json() -> None:
    connection = _connector("local", False)
    items = {
        i.csl.get("title"): i for i in connection.manager(connection.personal_library).all_items()
    }

    cepeda = items[CEPEDA["title"]]
    assert cepeda.version == 0  # the app's own versions are never recorded as Web ones
    assert cepeda.csl["DOI"].lower() == CEPEDA["DOI"].lower()
    assert (
        cepeda.csl["issued"]["date-parts"][0][0] == 2008
    )  # a number, though Zotero sends a string
    # typed as `11/1984`, which Zotero does not parse as a date: the year is still read
    hedges = items["An item whose date is not an ISO date"]
    assert hedges.csl["issued"]["date-parts"][0][0] == 1984
    # a PMID kept in `extra` comes back as CSL `note` and is read from there
    assert items["An item with its PMID in extra"].csl["PMID"] == "12345678"


def test_a_review_links_through_the_local_api(tmp_path: Path) -> None:
    repo, ids = review_with(tmp_path, CEPEDA)
    connection = _connector("local", False)

    result = zotero_ops.link(
        repo,
        actor="ethan",
        connector=_connector,
        library=connection.personal_library,
        rationale=WHY,
    )

    assert result.transport == "local" and result.write is False
    (row,) = mapping_mod.read_mapping(repo)
    assert (row.record, row.via, row.item_version) == (ids[0], "doi", 0)
