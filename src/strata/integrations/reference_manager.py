"""The generic reference-manager boundary.

Implements openspec:zotero-integration#optional-and-isolated: a reference manager does four things
for `strata` -- *resolve* what it holds for an item, *pull* a collection, *push* included studies
into one, and say how to *open* an item -- and nothing else here knows which manager it is talking
to. Zotero is the first implementation (`strata.integrations.zotero`); Mendeley, EndNote and
Paperpile are meant to be plugins behind this same interface rather than a rewrite.

The principle every implementation keeps: the manager owns the documents, `strata` owns the
decisions. A manager is never asked to hold a screening decision, and `strata` never deletes or
overwrites an item it did not create.

This module has no I/O and imports nothing from the rest of `strata`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal


class ReferenceManagerError(RuntimeError):
    """A reference manager could not do what was asked; `str()` is fit to show a person."""


class ReferenceManagerUnavailableError(ReferenceManagerError):
    """The manager could not be reached: it is not running, there is no network, or there are no
    credentials. Callers that merely *use* the manager (the retrieval queue) carry on without it."""


@dataclass(frozen=True)
class ItemRef:
    """One item in one library of a reference manager."""

    library: str
    key: str


@dataclass(frozen=True)
class RemoteItem:
    """A bibliographic item as the manager holds it right now.

    `csl` is the item as CSL-JSON, the form `strata` records are already in. `version` is the
    manager's own per-item version, the basis of optimistic concurrency. `collections` are the
    keys of the collections the item belongs to.
    """

    ref: ItemRef
    version: int
    csl: dict[str, Any]
    collections: tuple[str, ...] = ()


@dataclass(frozen=True)
class Attachment:
    """A file attached to an item."""

    key: str
    parent_key: str
    content_type: str | None
    title: str

    @property
    def is_pdf(self) -> bool:
        return self.content_type == "application/pdf"


@dataclass(frozen=True)
class Resolution:
    """What the manager holds for one `ItemRef` now.

    `present` is false when the item no longer exists, which is how a stale link shows itself.
    """

    ref: ItemRef
    present: bool
    version: int | None
    attachments: tuple[Attachment, ...] = ()

    @property
    def pdf(self) -> Attachment | None:
        """The first PDF attachment, if the item has one."""
        return next((a for a in self.attachments if a.is_pdf), None)


@dataclass(frozen=True)
class Collection:
    """A named group of items in a library."""

    library: str
    key: str
    name: str


@dataclass(frozen=True)
class Pulled:
    """The bibliographic items of one collection."""

    collection: Collection
    items: tuple[RemoteItem, ...]


@dataclass(frozen=True)
class PushItem:
    """One record to be put in a collection.

    `existing` is the manager's item already mapped to the record, if any, with the `version`
    `strata` last saw; `created_by_strata` says whether `strata` made that item itself, which is
    the only kind it may ever change the content of.
    """

    record_id: str
    csl: dict[str, Any]
    existing: ItemRef | None = None
    existing_version: int | None = None
    created_by_strata: bool = False


PushStatus = Literal["created", "added", "unchanged", "refused", "stale", "failed"]


@dataclass(frozen=True)
class PushOutcome:
    """What a push did for one record.

    `created` and `added` wrote something; `unchanged` found the item already in the collection;
    `refused` declined because the manager holds a newer version than `strata` last saw;
    `stale` found that the mapped item no longer exists; `failed` was rejected by the manager.
    """

    record_id: str
    status: PushStatus
    ref: ItemRef | None = None
    version: int | None = None
    detail: str | None = None


class ReferenceManager(ABC):
    """What `strata` asks of a reference manager."""

    #: A short stable name used in messages and records, e.g. `zotero`.
    name: str

    @abstractmethod
    def resolve(self, refs: Sequence[ItemRef]) -> dict[str, Resolution]:
        """What is held for each item, keyed by `ItemRef.key`; an item that is gone is `present`
        false, never an error."""

    @abstractmethod
    def pull(self, collection: str) -> Pulled:
        """The bibliographic items of a collection named by its name or its key."""

    @abstractmethod
    def push(self, items: Sequence[PushItem], collection: str) -> list[PushOutcome]:
        """Put records in a collection, creating items for those the manager lacks.

        Never deletes, and never changes the content of an item `strata` did not create; an item
        whose version is newer than `PushItem.existing_version` is refused rather than overwritten.
        One outcome per item, in order.
        """

    @abstractmethod
    def open(self, ref: ItemRef, *, attachment: str | None = None) -> str:
        """A URI that opens the item (or one of its attachments) in the manager's own program."""
