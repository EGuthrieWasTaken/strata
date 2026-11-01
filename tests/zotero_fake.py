"""An in-process Zotero for tests: it answers the requests `strata` makes, over no network.

`FakeZotero` implements `strata.integrations.zotero.http.HttpTransport`, so it stands in for the
real transport. It serves `tests/fixtures/zotero/library.json` the way the Zotero API v3 does, and
behaves as the local server of a given Zotero *major version* does (`<major>/profile.json`). It
enforces the rules `strata` relies on, so a client that breaks one fails here rather than in a
person's library:

- an item has a version, and a write that names a stale version is refused (412) for that item;
- the local API is read-only; the Web API needs a key, and a key may or may not allow writing;
- a busy server answers 429 with `Retry-After`, and may add `Backoff` to a good response;
- every request is recorded in `requests`, including any DELETE, so a test can show one never came.

Hand-written from the Zotero API v3 documentation, not captured from Zotero; see
`tests/fixtures/zotero/README.md`.
"""

from __future__ import annotations

import copy
import json
import re
import urllib.parse
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from strata.integrations.zotero.http import HttpResponse, TransportError

FIXTURES = Path(__file__).parent / "fixtures" / "zotero"
LOCAL_HOST = "127.0.0.1:23119"
WEB_HOST = "api.zotero.org"
API_KEY = "TESTKEYTESTKEYTESTKEY"

#: The Zotero majors the integration tests are pinned to.
MAJOR_VERSIONS = ("6", "7")


@dataclass
class Recorded:
    method: str
    host: str
    path: str
    query: dict[str, str]
    headers: dict[str, str]
    body: Any

    @property
    def writes(self) -> bool:
        return self.method != "GET"


@dataclass
class Library:
    library_id: str
    meta: dict[str, Any]
    collections: list[dict[str, Any]]
    items: dict[str, dict[str, Any]]
    attachments: dict[str, dict[str, Any]]
    version: int = 0
    created: int = 0

    def bump(self) -> int:
        self.version += 1
        return self.version


def _json(status: int, payload: Any, headers: Mapping[str, str] | None = None) -> HttpResponse:
    return HttpResponse(
        status,
        {"content-type": "application/json", **{k.lower(): v for k, v in (headers or {}).items()}},
        json.dumps(payload).encode("utf-8"),
    )


def _text(status: int, text: str) -> HttpResponse:
    return HttpResponse(status, {"content-type": "text/plain"}, text.encode("utf-8"))


class FakeZotero:
    """Zotero, as seen from `strata`. Construct one per test."""

    def __init__(
        self,
        major: str = "7",
        *,
        local_running: bool = True,
        local_api_enabled: bool = True,
        key: str = API_KEY,
        key_can_write: bool = True,
        group_can_write: bool = True,
        reshape_local: bool = False,
    ) -> None:
        self.profile = json.loads((FIXTURES / major / "profile.json").read_text(encoding="utf-8"))
        data = json.loads((FIXTURES / "library.json").read_text(encoding="utf-8"))
        self.templates: dict[str, dict[str, Any]] = data["templates"]
        self.libraries: dict[str, Library] = {}
        for library_id, raw in copy.deepcopy(data["libraries"]).items():
            items = {i["key"]: i for i in raw["items"]}
            attachments = {a["key"]: a for a in raw["attachments"]}
            library = Library(library_id, raw["meta"], raw["collections"], items, attachments)
            library.version = max(
                [i["version"] for i in items.values()]
                + [a["version"] for a in attachments.values()]
                + [0]
            )
            self.libraries[library_id] = library
        self.local_running = local_running
        self.local_api_enabled = local_api_enabled
        self.key = key
        self.key_can_write = key_can_write
        self.group_can_write = group_can_write
        self.reshape_local = reshape_local
        self.requests: list[Recorded] = []
        self._throttle = 0
        self._retry_after = "1"
        self._backoff_next: str | None = None

    # -------------------------------------------------------------------- levers for tests

    def edit_item(self, library_id: str, key: str, **csl_changes: Any) -> int:
        """Change an item in Zotero as a person would; returns the item's new version."""
        library = self.libraries[library_id]
        item = library.items[key]
        item["csl"].update(csl_changes)
        item["version"] = library.bump()
        return int(item["version"])

    def add_item(
        self, library_id: str, key: str, title: str, collections: tuple[str, ...] = (), **csl: Any
    ) -> None:
        """Add a top-level item to a library, as a person would."""
        library = self.libraries[library_id]
        library.items[key] = {
            "key": key,
            "version": library.bump(),
            "collections": list(collections),
            "csl": {"type": "article-journal", "title": title, **csl},
        }

    def delete_item(self, library_id: str, key: str) -> None:
        self.libraries[library_id].items.pop(key)

    def add_pdf(self, library_id: str, parent: str, key: str = "NEWPDF01") -> None:
        library = self.libraries[library_id]
        library.attachments[key] = {
            "key": key,
            "version": library.bump(),
            "parent": parent,
            "linkMode": "imported_file",
            "contentType": "application/pdf",
            "title": "Full Text PDF",
        }

    def throttle(self, times: int, retry_after: str = "1") -> None:
        """Answer the next `times` requests with 429 and this `Retry-After`."""
        self._throttle, self._retry_after = times, retry_after

    def backoff_after_next(self, seconds: str) -> None:
        """Add `Backoff: seconds` to the next successful response."""
        self._backoff_next = seconds

    def writes(self) -> list[Recorded]:
        return [r for r in self.requests if r.writes]

    # -------------------------------------------------------------------- the transport

    def request(
        self,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout: float,
    ) -> HttpResponse:
        parts = urllib.parse.urlsplit(url)
        query = {k: v[0] for k, v in urllib.parse.parse_qs(parts.query).items()}
        sent = {k.lower(): v for k, v in headers.items()}
        payload = json.loads(body) if body else None
        self.requests.append(Recorded(method, parts.netloc, parts.path, query, sent, payload))

        if parts.netloc == LOCAL_HOST:
            response = self._local(method, parts.path, query, sent, payload)
        elif parts.netloc == WEB_HOST:
            response = self._web(method, parts.path, query, sent, payload)
        else:
            raise TransportError(f"no route to host {parts.netloc}")
        if response.status == 200 and self._backoff_next is not None:
            response.headers["backoff"] = self._backoff_next
            self._backoff_next = None
        return response

    def _local(
        self, method: str, path: str, query: dict[str, str], headers: dict[str, str], body: Any
    ) -> HttpResponse:
        if not self.local_running:
            raise TransportError("[Errno 111] Connection refused")
        if not path.startswith("/api/") or not self.profile["local_api"]:
            return _text(404, "Not Found")
        if self.profile["local_api_needs_preference"] and not self.local_api_enabled:
            return _text(403, "Local API is not enabled")
        if method != "GET" and not self.profile["local_api_writable"]:
            return _text(501, "Method Not Implemented")
        if self.reshape_local:
            return _json(200, {"items": []})
        api_path = path[len("/api") :]
        api_path = re.sub(r"^/users/0(?=/|$)", "/users/12345", api_path)
        return self._api(method, api_path, query, body, local=True)

    def _web(
        self, method: str, path: str, query: dict[str, str], headers: dict[str, str], body: Any
    ) -> HttpResponse:
        if path == "/items/new":
            template = self.templates.get(query.get("itemType", ""))
            if template is None:
                return _text(400, "Invalid item type")
            return _json(200, template)
        if headers.get("zotero-api-key") != self.key:
            return _text(403, "Forbidden")
        if path == "/keys/current":
            return _json(
                200,
                {
                    "key": self.key,
                    "userID": 12345,
                    "username": "ethan",
                    "access": {
                        "user": {"library": True, "write": self.key_can_write},
                        "groups": {"all": {"library": True, "write": self.group_can_write}},
                    },
                },
            )
        return self._api(method, path, query, body, local=False)

    # -------------------------------------------------------------------- the API proper

    def _api(
        self, method: str, path: str, query: dict[str, str], body: Any, *, local: bool
    ) -> HttpResponse:
        if self._throttle > 0:
            self._throttle -= 1
            return HttpResponse(429, {"retry-after": self._retry_after}, b"Too Many Requests")

        if match := re.fullmatch(r"/users/(\d+)/groups", path):
            return self._page(self._groups(), query)
        match = re.fullmatch(r"/((?:users|groups)/\d+)(/.*)", path)
        if match is None or match.group(1) not in self.libraries:
            return _text(404, "Not Found")
        library = self.libraries[match.group(1)]
        rest = match.group(2)

        if method == "GET":
            if rest == "/collections":
                return self._page(
                    [{"key": c["key"], "version": 1, "data": {"key": c["key"], "name": c["name"]}}
                     for c in library.collections],
                    query,
                )  # fmt: skip
            if m := re.fullmatch(r"/collections/(\w+)/items/top", rest):
                keys = [k for k, i in library.items.items() if m.group(1) in i["collections"]]
                return self._page([self._item(library, k, query) for k in sorted(keys)], query)
            if rest == "/items/top":
                return self._page(
                    [self._item(library, k, query) for k in sorted(library.items)], query
                )
            if rest == "/items":
                return self._items(library, query)
            if m := re.fullmatch(r"/items/(\w+)/children", rest):
                return self._page(self._children(library, m.group(1)), query)
        elif method == "POST" and rest == "/items":
            return self._write_items(library, body, local=local)
        elif method == "DELETE":
            if m := re.fullmatch(r"/items/(\w+)", rest):
                library.items.pop(m.group(1), None)
                return HttpResponse(204, {}, b"")
        return _text(405, "Method Not Allowed")

    def _groups(self) -> list[dict[str, Any]]:
        return [
            {
                "id": lib.meta["id"],
                "version": 1,
                "data": {"id": lib.meta["id"], "name": lib.meta["name"]},
            }
            for lib_id, lib in self.libraries.items()
            if lib_id.startswith("groups/")
        ]

    def _page(self, rows: list[Any], query: dict[str, str]) -> HttpResponse:
        start = int(query.get("start", 0))
        limit = int(query.get("limit", 25))
        return _json(200, rows[start : start + limit], {"Total-Results": str(len(rows))})

    def _items(self, library: Library, query: dict[str, str]) -> HttpResponse:
        if "itemKey" in query:
            wanted = query["itemKey"].split(",")
            if len(wanted) > 50:
                return _text(400, "'itemKey' can't have more than 50 keys")
            return _json(200, [self._item(library, k, query) for k in wanted if k in library.items])
        if query.get("itemType") == "attachment":
            rows = [
                self._attachment_json(library, a)
                for a in sorted(library.attachments.values(), key=lambda a: a["key"])
            ]
            return self._page(rows, query)
        return self._page([self._item(library, k, query) for k in sorted(library.items)], query)

    def _item(self, library: Library, key: str, query: dict[str, str]) -> dict[str, Any]:
        item = library.items[key]
        data = {
            "key": key,
            "version": item["version"],
            "itemType": _zotero_type(item["csl"]),
            "title": item["csl"].get("title", ""),
            "collections": list(item["collections"]),
        }
        out: dict[str, Any] = {
            "key": key,
            "version": item["version"],
            "library": {"type": library.meta["type"], "id": library.meta["id"]},
            "data": data,
        }
        if "csljson" in query.get("include", ""):
            out["csljson"] = {"id": f"{library.meta['id']}/{key}", **item["csl"]}
        return out

    def _children(self, library: Library, parent: str) -> list[dict[str, Any]]:
        return [
            self._attachment_json(library, a)
            for a in library.attachments.values()
            if a["parent"] == parent
        ]

    @staticmethod
    def _attachment_json(library: Library, a: dict[str, Any]) -> dict[str, Any]:
        return {
            "key": a["key"],
            "version": a["version"],
            "library": {"type": library.meta["type"], "id": library.meta["id"]},
            "data": {
                "key": a["key"],
                "itemType": "attachment",
                "parentItem": a["parent"],
                "linkMode": a["linkMode"],
                "contentType": a["contentType"],
                "title": a["title"],
            },
        }

    def _write_items(self, library: Library, body: Any, *, local: bool) -> HttpResponse:
        writable = (
            self.key_can_write if library.library_id.startswith("users/") else self.group_can_write
        )
        if not writable:
            return _text(403, "Write access denied")
        if not isinstance(body, list) or len(body) > 50:
            return _text(413, "Too many items")
        successful: dict[str, Any] = {}
        failed: dict[str, Any] = {}
        for index, obj in enumerate(body):
            slot = str(index)
            if "key" in obj:
                item = library.items.get(obj["key"])
                if item is None:
                    failed[slot] = {"key": obj["key"], "code": 404, "message": "Item not found"}
                elif obj.get("version") != item["version"]:
                    failed[slot] = {
                        "key": obj["key"],
                        "code": 412,
                        "message": f"Item {obj['key']} has been modified since specified version "
                        f"(expected {obj.get('version')}, found {item['version']})",
                    }
                else:
                    if "collections" in obj:
                        item["collections"] = list(obj["collections"])
                    item["version"] = library.bump()
                    successful[slot] = {"key": obj["key"], "version": item["version"]}
                continue
            template = self.templates.get(obj.get("itemType", ""))
            unknown = sorted(set(obj) - set(template or {}))
            if template is None or unknown:
                failed[slot] = {
                    "code": 400,
                    "message": f"invalid itemType or fields {unknown or obj.get('itemType')}",
                }
                continue
            library.created += 1
            key = f"NEW{library.created:05d}"
            csl = _csl_of(obj)
            version = library.bump()
            library.items[key] = {
                "key": key,
                "version": version,
                "collections": list(obj.get("collections", [])),
                "csl": csl,
                "zotero": obj,
            }
            successful[slot] = {"key": key, "version": version}
        return _json(
            200,
            {"successful": successful, "success": {}, "unchanged": {}, "failed": failed},
            {"Last-Modified-Version": str(library.version)},
        )


_TYPE_OF = {
    "article-journal": "journalArticle",
    "book": "book",
    "chapter": "bookSection",
}


def _zotero_type(csl: Mapping[str, Any]) -> str:
    return _TYPE_OF.get(str(csl.get("type")), "document")


def _csl_of(obj: Mapping[str, Any]) -> dict[str, Any]:
    """The CSL an item created through the API reads back as (enough for the tests that read it)."""
    csl: dict[str, Any] = {"type": "article-journal", "title": obj.get("title", "")}
    if obj.get("DOI"):
        csl["DOI"] = obj["DOI"]
    authors = [
        {"family": c["lastName"], "given": c.get("firstName", "")}
        for c in obj.get("creators", [])
        if c.get("lastName")
    ]
    if authors:
        csl["author"] = authors
    return csl


@dataclass
class FakeHttp:
    """`make_http_transport` replacement that hands out one `FakeZotero`."""

    zotero: FakeZotero
    calls: list[str] = field(default_factory=list)

    def __call__(self) -> FakeZotero:
        self.calls.append("transport")
        return self.zotero
