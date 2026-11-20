"""Finding out what the Zotero running on this computer can do, rather than assuming.

Implements the capability probing of openspec:zotero-integration#transport-selection. The local API
exists in the Zotero `strata` supports (10 or later) only when the person has switched it on;
its shape is whatever this Zotero's version serves. The probe asks for one item the way
`strata` will ask for all of them and
accepts the answer only if it has the shape `strata` reads. Anything else is a reason, in words a
person can act on, and the caller falls back to the Web API.
"""

from __future__ import annotations

from dataclasses import dataclass

from strata.integrations.zotero.api import (
    API_VERSION,
    LOCAL_BASE_URL,
    ZoteroApi,
    ZoteroError,
    ZoteroUnavailableError,
)
from strata.integrations.zotero.csl import read_csl
from strata.integrations.zotero.http import HttpTransport

#: The local API's alias for "the library of the person using this Zotero".
LOCAL_USER_LIBRARY = "users/0"

SWITCH_ON = (
    "Settings > Advanced > 'Allow other applications on this computer to communicate with Zotero'"
)


@dataclass(frozen=True)
class LocalApi:
    """A usable local API."""

    #: The personal library as `users/<id>`; `users/0` when this Zotero has no account signed in.
    library: str
    api_version: str | None


def _library_of(item: dict[str, object]) -> str:
    library = item.get("library")
    if isinstance(library, dict) and library.get("type") == "user":
        user_id = library.get("id")
        if isinstance(user_id, int) and user_id > 0:
            return f"users/{user_id}"
    return LOCAL_USER_LIBRARY


def probe_local(
    transport: HttpTransport, *, base_url: str = LOCAL_BASE_URL, timeout: float = 10.0
) -> tuple[LocalApi | None, str]:
    """`(api, "")` if the local API is usable, else `(None, why not)`."""
    api = ZoteroApi(base_url, transport, timeout=timeout, max_retries=0)
    try:
        response = api.request(
            "GET",
            f"/{LOCAL_USER_LIBRARY}/items/top",
            params={"limit": 1, "format": "json", "include": "data,csljson"},
        )
    except ZoteroUnavailableError as exc:
        # A Zotero that is not running refuses at once; one that is there but slow (just started,
        # a large library) times out, which is a different thing to tell a person.
        if exc.timed_out:
            return None, f"Zotero is running but did not answer within {timeout:g} s; try again"
        return None, "Zotero is not running on this computer"
    except ZoteroError as exc:
        if exc.status == 404:
            return None, "this Zotero has no local API (strata supports Zotero 10 or later)"
        if exc.status in (401, 403):
            return None, f"the local API is switched off in Zotero ({SWITCH_ON})"
        return None, f"the local API answered with an error ({exc})"
    version = response.headers.get("zotero-api-version")
    if version is not None and version != API_VERSION:
        return None, f"the local API speaks Zotero API v{version}; strata reads v{API_VERSION}"
    try:
        items = response.json()
    except ZoteroError:
        return None, "the local API did not answer as Zotero's API does (the reply is not JSON)"
    if not isinstance(items, list):
        return None, "the local API did not answer as Zotero's API does (no list of items)"
    if items:
        first = items[0]
        if not (
            isinstance(first, dict)
            and {"key", "version", "data", "csljson"} <= first.keys()
            and read_csl(first["csljson"]) is not None
        ):
            return None, (
                "the local API does not provide items with their CSL-JSON, which strata reads"
            )
        return LocalApi(_library_of(first), version), ""
    return LocalApi(LOCAL_USER_LIBRARY, version), ""
