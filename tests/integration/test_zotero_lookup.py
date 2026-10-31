"""Where full texts are in Zotero (`strata.integrations.zotero.retrieval`): advice that never fails
(openspec:zotero-integration#retrieval-through-zotero, #identity-mapping)."""

from __future__ import annotations

from pathlib import Path

import pytest

from strata.integrations.reference_manager import ItemRef
from strata.integrations.zotero import operations as zotero_ops
from strata.integrations.zotero.retrieval import ZoteroDocument, lookup
from tests.integration._zotero import CEPEDA, ONLY_HERE, connector_for, review_with
from tests.zotero_fake import FakeZotero

LIB = "users/12345"
WHY = "recording what this step did to the review's Zotero link"


def test_a_review_with_no_link_is_not_looked_up_and_zotero_is_never_asked(tmp_path: Path) -> None:
    repo, ids = review_with(tmp_path, CEPEDA)

    def forbidden(preference: str, need_write: bool):  # type: ignore[no-untyped-def]
        raise AssertionError("asked for a connection to Zotero")

    assert lookup(repo, ids, connector=forbidden) is None


def test_records_with_no_zotero_item_are_unlinked_without_asking_zotero(tmp_path: Path) -> None:
    repo, ids = review_with(tmp_path, CEPEDA, ONLY_HERE)
    fake = FakeZotero("7")
    zotero_ops.link(repo, actor="ethan", connector=connector_for(fake), library=LIB, rationale=WHY)
    asked_before = len(fake.requests)

    found = lookup(repo, [ids[1]], connector=connector_for(fake))

    assert found is not None and found.documents[ids[1]].state == "unlinked"
    assert found.unavailable is None and len(fake.requests) == asked_before
    assert found.documents[ids[1]].manifest_ref is None
    assert found.get("rec_not_asked_about").state == "unlinked"


def test_a_zotero_that_cannot_be_asked_is_reported_not_raised(tmp_path: Path) -> None:
    repo, ids = review_with(tmp_path, CEPEDA)
    zotero_ops.link(
        repo, actor="ethan", connector=connector_for(FakeZotero("7")), library=LIB, rationale=WHY
    )

    found = lookup(
        repo, ids, connector=connector_for(FakeZotero("7", local_running=False), keychain=False)
    )

    assert found is not None
    assert found.unavailable is not None and found.documents == {}
    assert found.attachments_found == 0


def test_the_manifest_reference_names_the_library_and_item() -> None:
    document = ZoteroDocument("pdf", ItemRef(LIB, "AB3D9XYZ"), "zotero://x")

    assert document.manifest_ref == {"library": LIB, "item_key": "AB3D9XYZ"}
    assert document.attachment_present is True
    assert ZoteroDocument("stale", ItemRef(LIB, "AB3D9XYZ")).attachment_present is False


@pytest.mark.parametrize("state", ["none", "stale", "unlinked"])
def test_only_a_file_counts_as_an_attachment(state: str) -> None:
    assert ZoteroDocument(state).attachment_present is False  # type: ignore[arg-type]
