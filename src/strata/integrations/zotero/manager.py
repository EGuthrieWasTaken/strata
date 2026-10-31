"""`ReferenceManager` for Zotero, over the local API or the Web API.

Implements openspec:zotero-integration#append-only-meets-mutable. Zotero is mutable and `strata` is
append-only, so what crosses between them is deliberately narrow:

- A pull only reads.
- A push *creates* items for records Zotero lacks, and otherwise only *adds* an item to a
  collection. It never deletes, never writes the bibliographic fields of an item that already
  exists (Zotero wins on those), and never removes an item from a collection.
- Every write to an existing item carries the item's version, which Zotero checks: if the item has
  changed since `strata` last saw it the write is refused for that item and reported.
"""

from __future__ import annotations

import functools
import re
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, ParamSpec, TypeVar

from strata.integrations.reference_manager import (
    Attachment,
    Collection,
    ItemRef,
    Pulled,
    PushItem,
    PushOutcome,
    PushStatus,
    ReferenceManager,
    RemoteItem,
    Resolution,
)
from strata.integrations.zotero.api import ZoteroApi, ZoteroError, ZoteroNotFoundError
from strata.integrations.zotero.probe import LOCAL_USER_LIBRARY

#: Item types that are not bibliographic items in their own right.
NON_BIBLIOGRAPHIC = frozenset({"attachment", "note", "annotation"})

#: How many keys or objects one request carries (the API's limit for both).
BATCH = 50

_KEY_RE = re.compile(r"^[0-9A-Z]{8}$")

#: CSL type -> Zotero item type; anything else is filed as a generic `document`.
_ITEM_TYPES = {
    "article-journal": "journalArticle",
    "article": "journalArticle",
    "book": "book",
    "chapter": "bookSection",
    "paper-conference": "conferencePaper",
    "thesis": "thesis",
    "report": "report",
    "webpage": "webpage",
}

#: CSL field -> the Zotero fields that can hold it, first one the item type has wins.
_FIELD_CANDIDATES: dict[str, tuple[str, ...]] = {
    "title": ("title",),
    "container-title": ("publicationTitle", "bookTitle", "proceedingsTitle", "websiteTitle"),
    "volume": ("volume",),
    "issue": ("issue",),
    "page": ("pages",),
    "DOI": ("DOI",),
    "URL": ("url",),
    "abstract": ("abstractNote",),
    "language": ("language",),
    "ISBN": ("ISBN",),
    "publisher": ("publisher",),
}

#: Fields Zotero has no slot for, kept in the item's `extra` as `Label: value` lines.
_EXTRA_LABELS = {"PMID": "PMID", "PMCID": "PMCID"}


_P = ParamSpec("_P")
_R = TypeVar("_R")


def _reads_replies_safely(func: Callable[_P, _R]) -> Callable[_P, _R]:
    """Report a reply `strata` cannot read as an error that says so, not as a bare `KeyError`.

    The shape of Zotero's replies is the thing most likely to change between versions; when it does,
    the person should be told it is a reply they got, from a version `strata` may not know.
    """

    @functools.wraps(func)
    def wrapper(*args: _P.args, **kwargs: _P.kwargs) -> _R:
        try:
            return func(*args, **kwargs)
        except (KeyError, TypeError, AttributeError, ValueError) as exc:
            raise ZoteroError(
                f"Zotero sent a reply strata could not read ({type(exc).__name__}: {exc}); it may "
                "come from a version of Zotero strata does not know"
            ) from None

    return wrapper


@dataclass(frozen=True)
class LibraryInfo:
    library: str
    name: str


@dataclass(frozen=True)
class KeyInfo:
    """What a Web API key may do (`GET /keys/current`)."""

    user_id: int
    username: str
    user_write: bool
    group_write: Mapping[str, bool]
    all_groups_write: bool

    def can_write(self, library: str) -> bool:
        if library.startswith("users/"):
            return self.user_write and library == f"users/{self.user_id}"
        group = library.split("/", 1)[1]
        return self.group_write.get(group, self.all_groups_write)


@_reads_replies_safely
def key_info(api: ZoteroApi) -> KeyInfo:
    data = api.get_json("/keys/current")
    access = data.get("access", {}) if isinstance(data, dict) else {}
    user = access.get("user", {})
    groups = access.get("groups", {})
    if not isinstance(data, dict) or "userID" not in data:
        raise ZoteroError("Zotero did not say whose key this is")
    return KeyInfo(
        user_id=int(data["userID"]),
        username=str(data.get("username", "")),
        user_write=bool(user.get("write", False)),
        group_write={
            gid: bool(perm.get("write", False))
            for gid, perm in groups.items()
            if gid != "all" and isinstance(perm, dict)
        },
        all_groups_write=bool(groups.get("all", {}).get("write", False)),
    )


@_reads_replies_safely
def list_libraries(api: ZoteroApi, personal: str, *, local: bool) -> list[LibraryInfo]:
    """The personal library and every group the person belongs to."""
    libraries = [LibraryInfo(personal, "My Library")]
    owner = LOCAL_USER_LIBRARY if local else personal
    for page in api.get_pages(f"/{owner}/groups"):
        for group in page:
            data = group.get("data", {})
            libraries.append(
                LibraryInfo(f"groups/{group['id']}", str(data.get("name", group["id"])))
            )
    return libraries


def _date_of(issued: Mapping[str, Any] | None) -> str:
    parts = ((issued or {}).get("date-parts") or [[]])[0]
    return "-".join(f"{p:02d}" if i else str(p) for i, p in enumerate(parts))


class ZoteroManager(ReferenceManager):
    """Zotero, one library at a time.

    `local` says the API is the desktop app's, where the personal library is addressed as
    `users/0`; `library` is always the real `users/<id>` or `groups/<id>`. `writable` is what the
    link recorded about the key's permission to write.
    """

    name = "zotero"

    def __init__(
        self,
        api: ZoteroApi,
        library: str,
        *,
        local: bool,
        writable: bool = False,
        write_token: Callable[[], str] = lambda: uuid.uuid4().hex,
    ) -> None:
        self.api = api
        self.library = library
        self.local = local
        self.writable = writable
        self._write_token = write_token
        prefix = LOCAL_USER_LIBRARY if local and library.startswith("users/") else library
        self._path = f"/{prefix}"
        self._templates: dict[str, dict[str, Any]] = {}

    # ------------------------------------------------------------------ reading

    @_reads_replies_safely
    def collections(self) -> list[Collection]:
        found: list[Collection] = []
        for page in self.api.get_pages(f"{self._path}/collections"):
            for obj in page:
                found.append(Collection(self.library, str(obj["key"]), str(obj["data"]["name"])))
        return found

    def find_collection(self, ident: str) -> Collection:
        """A collection by key or by exact name; an ambiguous name is an error, not a guess."""
        available = self.collections()
        if _KEY_RE.match(ident):
            for collection in available:
                if collection.key == ident:
                    return collection
        named = [c for c in available if c.name == ident]
        if len(named) == 1:
            return named[0]
        if not named:
            names = ", ".join(sorted(c.name for c in available)) or "(none)"
            raise ZoteroNotFoundError(
                f"no collection {ident!r} in {self.library}; the collections are: {names}"
            )
        keys = ", ".join(c.key for c in named)
        raise ZoteroError(f"{len(named)} collections are named {ident!r} ({keys}); pass the key")

    @_reads_replies_safely
    def pull(self, collection: str) -> Pulled:
        found = self.find_collection(collection)
        return Pulled(found, tuple(self._items(f"{self._path}/collections/{found.key}/items/top")))

    @_reads_replies_safely
    def all_items(self) -> list[RemoteItem]:
        """Every top-level bibliographic item in the library."""
        return self._items(f"{self._path}/items/top")

    @_reads_replies_safely
    def resolve(self, refs: Sequence[ItemRef]) -> dict[str, Resolution]:
        keys = sorted({r.key for r in refs})
        current = self._current(keys)
        present = {key for key, state in current.items() if state is not None}
        attachments = self._attachments(present)
        resolved: dict[str, Resolution] = {}
        for key in keys:
            state = current.get(key)
            ref = ItemRef(self.library, key)
            if state is None:
                resolved[key] = Resolution(ref, present=False, version=None)
            else:
                resolved[key] = Resolution(
                    ref, present=True, version=state[0], attachments=tuple(attachments.get(key, ()))
                )
        return resolved

    def open(self, ref: ItemRef, *, attachment: str | None = None) -> str:
        where = "library" if ref.library.startswith("users/") else ref.library
        if attachment:
            return f"zotero://open-pdf/{where}/items/{attachment}"
        return f"zotero://select/{where}/items/{ref.key}"

    def _items(self, path: str) -> list[RemoteItem]:
        items: list[RemoteItem] = []
        for page in self.api.get_pages(path, {"format": "json", "include": "data,csljson"}):
            for obj in page:
                item = self._remote_item(obj)
                if item is not None:
                    items.append(item)
        return items

    def _remote_item(self, obj: Mapping[str, Any]) -> RemoteItem | None:
        data = obj.get("data", {})
        if data.get("itemType") in NON_BIBLIOGRAPHIC:
            return None
        csl = obj.get("csljson")
        if isinstance(csl, list):
            csl = csl[0] if csl else None
        if not isinstance(csl, dict):
            raise ZoteroError(
                f"Zotero sent an item without its CSL-JSON (key {obj.get('key')!r}), "
                "which strata needs to read it"
            )
        return RemoteItem(
            ref=ItemRef(self.library, str(obj["key"])),
            version=int(obj["version"]),
            csl={k: v for k, v in csl.items() if k != "id"},
            collections=tuple(str(c) for c in data.get("collections", [])),
        )

    def _current(self, keys: Sequence[str]) -> dict[str, tuple[int, tuple[str, ...]] | None]:
        """`(version, collections)` for each key now, or `None` for an item that is gone."""
        current: dict[str, tuple[int, tuple[str, ...]] | None] = dict.fromkeys(keys)
        for start in range(0, len(keys), BATCH):
            batch = keys[start : start + BATCH]
            found = self.api.get_json(
                f"{self._path}/items", {"itemKey": ",".join(batch), "format": "json"}
            )
            for obj in found:
                data = obj.get("data", {})
                current[str(obj["key"])] = (
                    int(obj["version"]),
                    tuple(str(c) for c in data.get("collections", [])),
                )
        return current

    def _attachments(self, parents: set[str]) -> dict[str, list[Attachment]]:
        """File attachments of the given items. A few items are asked about one by one; many are
        read off one listing of every attachment in the library, which is far fewer requests."""
        found: dict[str, list[Attachment]] = {}
        if not parents:
            return found
        if len(parents) <= 8:
            for key in sorted(parents):
                for obj in self.api.get_json(
                    f"{self._path}/items/{key}/children", {"format": "json"}
                ):
                    self._collect_attachment(obj, found, parents)
            return found
        for page in self.api.get_pages(
            f"{self._path}/items", {"itemType": "attachment", "format": "json"}
        ):
            for obj in page:
                self._collect_attachment(obj, found, parents)
        return found

    @staticmethod
    def _collect_attachment(
        obj: Mapping[str, Any], found: dict[str, list[Attachment]], parents: set[str]
    ) -> None:
        data = obj.get("data", {})
        parent = data.get("parentItem")
        if data.get("itemType") != "attachment" or parent not in parents:
            return
        if data.get("linkMode") == "linked_url":
            return  # a link to a web page, not a file
        found.setdefault(str(parent), []).append(
            Attachment(
                key=str(obj["key"]),
                parent_key=str(parent),
                content_type=data.get("contentType") or None,
                title=str(data.get("title") or data.get("filename") or ""),
            )
        )

    # ------------------------------------------------------------------ writing

    @_reads_replies_safely
    def push(self, items: Sequence[PushItem], collection: str) -> list[PushOutcome]:
        if self.local:
            raise ZoteroError("the local API is read-only; writing goes through the Web API")
        if not self.writable:
            raise ZoteroError(
                f"this link cannot write to {self.library}; run `strata zotero link --web` with "
                "an API key that has write access"
            )
        target = self.find_collection(collection)
        existing_keys = sorted({i.existing.key for i in items if i.existing is not None})
        current = self._current(existing_keys)

        outcomes: dict[int, PushOutcome] = {}
        writes: list[tuple[int, dict[str, Any]]] = []
        for position, item in enumerate(items):
            if item.existing is None:
                writes.append((position, self._new_item(item.csl, target.key)))
                continue
            state = current.get(item.existing.key)
            if state is None:
                outcomes[position] = PushOutcome(
                    item.record_id,
                    "stale",
                    item.existing,
                    detail="the mapped item no longer exists in Zotero",
                )
                continue
            version, member_of = state
            if target.key in member_of:
                outcomes[position] = PushOutcome(
                    item.record_id, "unchanged", item.existing, version
                )
            elif item.existing_version is not None and version != item.existing_version:
                outcomes[position] = PushOutcome(
                    item.record_id,
                    "refused",
                    item.existing,
                    version,
                    f"edited in Zotero since strata last saw it (version {item.existing_version} "
                    f"is now {version}); pull it, then push again",
                )
            else:
                update = {
                    "key": item.existing.key,
                    "version": version,
                    "collections": sorted({*member_of, target.key}),
                }
                self._check_membership_only(item, update)
                writes.append((position, update))

        for start in range(0, len(writes), BATCH):
            chunk = writes[start : start + BATCH]
            outcomes.update(self._write(chunk, items))
        return [outcomes[position] for position in range(len(items))]

    @staticmethod
    def _check_membership_only(item: PushItem, update: Mapping[str, Any]) -> None:
        """An item `strata` did not create may be given a collection and nothing else."""
        if item.created_by_strata:
            return
        extra = set(update) - {"key", "version", "collections"}
        if extra:
            raise ZoteroError(
                f"refusing to change {sorted(extra)} of Zotero item {update.get('key')}, "
                "which strata did not create"
            )

    def _write(
        self, chunk: Sequence[tuple[int, dict[str, Any]]], items: Sequence[PushItem]
    ) -> dict[int, PushOutcome]:
        response = self.api.request(
            "POST",
            f"{self._path}/items",
            body=[body for _, body in chunk],
            headers={"Zotero-Write-Token": self._write_token()},
        ).json()
        outcomes: dict[int, PushOutcome] = {}
        successful = response.get("successful", {})
        unchanged = response.get("unchanged", {})
        failed = response.get("failed", {})
        for index, (position, body) in enumerate(chunk):
            item = items[position]
            slot = str(index)
            if slot in successful:
                made = successful[slot]
                ref = ItemRef(self.library, str(made["key"]))
                status: PushStatus = "added" if "key" in body else "created"
                outcomes[position] = PushOutcome(item.record_id, status, ref, int(made["version"]))
            elif slot in unchanged:
                outcomes[position] = PushOutcome(item.record_id, "unchanged", item.existing)
            else:
                problem = failed.get(slot, {})
                code = problem.get("code")
                message = str(problem.get("message", "Zotero did not accept it"))
                outcomes[position] = PushOutcome(
                    item.record_id,
                    "refused" if code == 412 else "failed",
                    item.existing,
                    detail=message,
                )
        return outcomes

    def _template(self, item_type: str) -> dict[str, Any]:
        if item_type not in self._templates:
            template = self.api.get_json("/items/new", {"itemType": item_type})
            if not isinstance(template, dict):
                raise ZoteroError(f"Zotero has no template for item type {item_type!r}")
            self._templates[item_type] = template
        return self._templates[item_type]

    def _new_item(self, csl: Mapping[str, Any], collection_key: str) -> dict[str, Any]:
        """Zotero item JSON for a record, built on Zotero's own template for the item type so that
        only fields that type really has are sent; the rest go in `extra`."""
        item_type = _ITEM_TYPES.get(str(csl.get("type")), "document")
        template = self._template(item_type)
        item: dict[str, Any] = {"itemType": item_type}
        extra: list[str] = []

        for csl_field, candidates in _FIELD_CANDIDATES.items():
            value = csl.get(csl_field)
            if not value:
                continue
            slot = next((name for name in candidates if name in template), None)
            if slot is not None:
                item[slot] = str(value)
            else:
                extra.append(f"{csl_field}: {value}")
        for csl_field, label in _EXTRA_LABELS.items():
            if csl.get(csl_field):
                extra.append(f"{label}: {csl[csl_field]}")
        date = _date_of(csl.get("issued"))
        if date and "date" in template:
            item["date"] = date
        creators = [self._creator(a) for a in csl.get("author") or [] if isinstance(a, dict)]
        if creators:
            item["creators"] = [c for c in creators if c]
        if extra and "extra" in template:
            item["extra"] = "\n".join(extra)
        item["collections"] = [collection_key]
        return item

    @staticmethod
    def _creator(author: Mapping[str, Any]) -> dict[str, str]:
        if author.get("family"):
            return {
                "creatorType": "author",
                "firstName": str(author.get("given", "")),
                "lastName": str(author["family"]),
            }
        if author.get("literal"):
            return {"creatorType": "author", "name": str(author["literal"])}
        return {}
