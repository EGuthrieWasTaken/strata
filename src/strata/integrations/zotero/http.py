"""The one place `strata` opens a socket to Zotero.

Everything above this module takes an `HttpTransport`, so the clients are tested against an
in-process fake that speaks the API and never touch a network. `UrllibTransport` is the real thing,
tested separately against a server on the loopback interface.
"""

from __future__ import annotations

import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Protocol


class TransportError(OSError):
    """The request never produced a response: refused, unreachable, or timed out."""


@dataclass(frozen=True)
class HttpResponse:
    """A raw response. Header names are lower-cased."""

    status: int
    headers: dict[str, str]
    body: bytes


class HttpTransport(Protocol):
    def request(
        self,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout: float,
    ) -> HttpResponse: ...


_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})

# A proxy named in the environment (HTTP_PROXY and friends) is for the internet. The local Zotero
# is on this machine and must never be sent through one.
_DIRECT_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _lower(headers: Iterable[tuple[str, str]]) -> dict[str, str]:
    return {name.lower(): value for name, value in headers}


class UrllibTransport:
    """`HttpTransport` over the standard library."""

    def request(
        self,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout: float,
    ) -> HttpResponse:
        request = urllib.request.Request(url, data=body, headers=dict(headers), method=method)
        host = urllib.parse.urlsplit(url).hostname or ""
        open_url = _DIRECT_OPENER.open if host in _LOOPBACK_HOSTS else urllib.request.urlopen
        try:
            with open_url(request, timeout=timeout) as response:
                return HttpResponse(
                    response.status, _lower(response.headers.items()), response.read()
                )
        except urllib.error.HTTPError as exc:
            return HttpResponse(exc.code, _lower(exc.headers.items()), exc.read())
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            reason = getattr(exc, "reason", exc)
            raise TransportError(str(reason)) from None
