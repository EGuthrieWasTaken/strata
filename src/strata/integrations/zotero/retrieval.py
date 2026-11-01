"""Full texts through Zotero, for the retrieval queue and for full-text screening.

Implements openspec:zotero-integration#retrieval-through-zotero and the stale-link half of
openspec:zotero-integration#identity-mapping. Everything here is advice to a person about where a
document is; none of it can stop them working. A record with no link, an item deleted from Zotero,
or Zotero not running each become a line saying the full text is unavailable or unlooked-for, never
an error that blocks the queue or a screening decision.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from strata.core import records as records_mod
from strata.core.repo import Repo
from strata.integrations.reference_manager import ItemRef, ReferenceManagerError
from strata.integrations.zotero import mapping as mapping_mod
from strata.integrations.zotero.connect import read_link
from strata.integrations.zotero.operations import Connector

#: `pdf` and `files` mean an attachment is present (`files`: attachments, none of them a PDF);
#: `none` is a linked item with no attachment; `unlinked` is a record with no Zotero item; `stale`
#: is a link to an item that no longer exists.
DocumentState = Literal["pdf", "files", "none", "unlinked", "stale"]


@dataclass(frozen=True)
class ZoteroDocument:
    state: DocumentState
    ref: ItemRef | None = None
    #: A `zotero://` URI that opens the PDF, or else the item, in Zotero.
    uri: str | None = None

    @property
    def attachment_present(self) -> bool:
        return self.state in ("pdf", "files")

    @property
    def manifest_ref(self) -> dict[str, str] | None:
        """The Zotero item as a full-text manifest entry records it."""
        if self.ref is None:
            return None
        return {"library": self.ref.library, "item_key": self.ref.key}


@dataclass(frozen=True)
class DocumentLookup:
    """What Zotero holds for a set of records."""

    documents: dict[str, ZoteroDocument]
    #: Why Zotero could not be asked, when it could not; the queue carries on without it.
    unavailable: str | None = None
    notices: tuple[str, ...] = ()

    @property
    def attachments_found(self) -> int:
        return sum(1 for d in self.documents.values() if d.attachment_present)

    def get(self, record_id: str) -> ZoteroDocument:
        return self.documents.get(record_id, ZoteroDocument("unlinked"))


def lookup(repo: Repo, record_ids: Sequence[str], *, connector: Connector) -> DocumentLookup | None:
    """Where each record's full text is in Zotero; `None` if the review is not linked to Zotero.

    Never raises for a problem with Zotero: that is reported in `unavailable`.
    """
    link = read_link(repo)
    if link is None:
        return None
    records = records_mod.read_records(repo)
    absorbed = mapping_mod.absorbed_into(records)
    rows = mapping_mod.read_mapping(repo)

    documents: dict[str, ZoteroDocument] = {}
    mapped: dict[str, ItemRef] = {}
    for record_id in record_ids:
        row = mapping_mod.row_for_record(rows, link.library, record_id, follow=absorbed)
        if row is None:
            documents[record_id] = ZoteroDocument("unlinked")
        else:
            mapped[record_id] = ItemRef(link.library, row.item_key)
    if not mapped:
        return DocumentLookup(documents)

    try:
        connection = connector(link.transport, False)
        manager = connection.manager(link.library)
        resolved = manager.resolve(list(mapped.values()))
    except ReferenceManagerError as exc:
        return DocumentLookup(documents, unavailable=str(exc))

    for record_id, ref in mapped.items():
        resolution = resolved[ref.key]
        if not resolution.present:
            documents[record_id] = ZoteroDocument("stale", ref)
        elif resolution.pdf is not None:
            documents[record_id] = ZoteroDocument(
                "pdf", ref, manager.open(ref, attachment=resolution.pdf.key)
            )
        elif resolution.attachments:
            documents[record_id] = ZoteroDocument("files", ref, manager.open(ref))
        else:
            documents[record_id] = ZoteroDocument("none", ref, manager.open(ref))
    return DocumentLookup(documents, notices=connection.notices)
