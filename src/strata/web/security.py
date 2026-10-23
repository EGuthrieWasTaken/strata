"""Security baseline for `strata serve`: openspec:web-ui#localhost-security (normative).

A local server is still attack surface -- any page open in the user's
browser can issue requests to `127.0.0.1`. Every control this module
implements defends against that, not against a network attacker:

- A per-process session token (`SESSION_COOKIE_NAME`), delivered once via
  the URL `strata serve` opens and then carried as a `SameSite=Strict`,
  `HttpOnly` cookie. A page on another origin cannot read or set it, and
  `SameSite=Strict` keeps the browser from attaching it to a cross-site
  request at all.
- The same token doubles as the CSRF token, embedded as a hidden form
  field by every mutating form the templates render. This is the
  "double-submit cookie" pattern: forging a mutating request from another
  origin would require *reading* the httponly cookie's value to also send
  it as the form field, which that origin cannot do.
- `Origin`/`Host` header validation, which is what actually defeats DNS
  rebinding: a hostile page can get the browser to resolve an
  attacker-controlled domain name to `127.0.0.1` after the fact, at which
  point `SameSite`/CORS alone would not save this server, because the
  browser now genuinely believes it is talking to that domain. Checking
  the `Host` header against the address this server was actually told to
  bind to closes that gap.
"""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

SESSION_COOKIE_NAME = "strata_session"
CSRF_FIELD_NAME = "csrf_token"
MUTATING_METHODS = frozenset({"POST", "PUT", "DELETE", "PATCH"})
DEFAULT_INACTIVITY_TIMEOUT_SECONDS = 60 * 60  # openspec:web-ui#localhost-security


def generate_token() -> str:
    """A fresh per-process session/CSRF token: 256 bits, URL-safe."""
    return secrets.token_urlsafe(32)


@dataclass(frozen=True)
class PublicUrl:
    """The URL a browser uses to reach the server (`--public-url`), as the `Host` and `Origin`
    header values it will send: browsers leave a scheme's default port out of both."""

    scheme: str
    hostname: str
    port: int | None  # None when the URL leaves the default port implicit

    @property
    def host_header(self) -> str:
        return self.hostname if self.port is None else f"{self.hostname}:{self.port}"

    @property
    def origin(self) -> str:
        return f"{self.scheme}://{self.host_header}"


def parse_public_url(raw: str) -> PublicUrl:
    """Parse `--public-url`; `ValueError` says what is wrong
    (openspec:web-ui#configurable-public-url).

    Only the scheme, host and port matter to header validation, so a path is accepted (a hosted
    instance may live under one) but ignored.
    """
    text = raw.strip()
    parts = urlsplit(text)
    if parts.scheme not in ("http", "https"):
        raise ValueError(
            f"{raw!r} needs a scheme: use an absolute http:// or https:// URL, "
            "for example http://localhost:8765"
        )
    if not parts.hostname:
        raise ValueError(f"{raw!r} has no host name")
    try:
        port = parts.port
    except ValueError:
        raise ValueError(f"{raw!r} has an invalid port") from None
    if port == {"http": 80, "https": 443}[parts.scheme]:
        port = None
    hostname = f"[{parts.hostname}]" if ":" in parts.hostname else parts.hostname
    return PublicUrl(parts.scheme, hostname, port)


def allowed_hosts(host: str, port: int, public_url: PublicUrl | None = None) -> frozenset[str]:
    """`Host` header values this server accepts, given the address it bound to.

    With a public URL the answer is exactly that URL's host: the address the server bound to is
    not what a browser sends when a port is published or a proxy sits in front.

    Includes both the bind address and, for the common `127.0.0.1` case,
    `localhost` too -- a browser opening either name against the same
    loopback address is legitimate, and rejecting one but not the other
    would just be a usability trap, not a real security boundary (both
    resolve to the same loopback interface).
    """
    if public_url is not None:
        return frozenset({public_url.host_header})
    names = {host}
    if host in ("127.0.0.1", "localhost"):
        names |= {"127.0.0.1", "localhost"}
    return frozenset(f"{name}:{port}" for name in names)


def is_host_allowed(host_header: str | None, allowed: frozenset[str]) -> bool:
    return host_header is not None and host_header in allowed


def is_origin_allowed(
    origin_header: str | None, host: str, port: int, public_url: PublicUrl | None = None
) -> bool:
    """No `Origin` header (a same-origin navigation/form submit, or a
    non-browser client) is allowed through; a *present* header MUST name
    this exact server (or, given one, the public URL)."""
    if origin_header is None:
        return True
    if public_url is not None:
        return origin_header == public_url.origin
    expected = {f"http://{name}" for name in (host, "localhost" if host == "127.0.0.1" else host)}
    expected = {f"{e}:{port}" for e in expected}
    return origin_header in expected


class InactivityClock:
    """Tracks the server's last-activity timestamp for the auto-shutdown
    timer (openspec:web-ui#localhost-security's "exits after 60 minutes of
    inactivity"). A tiny wrapper, not a bare module-level global, purely
    so a test can inject a fake clock rather than sleeping for real."""

    def __init__(self, timeout_seconds: float, *, now: float | None = None) -> None:
        self.timeout_seconds = timeout_seconds
        self.last_activity = now if now is not None else time.monotonic()

    def touch(self, *, now: float | None = None) -> None:
        self.last_activity = now if now is not None else time.monotonic()

    def is_expired(self, *, now: float | None = None) -> bool:
        current = now if now is not None else time.monotonic()
        return (current - self.last_activity) >= self.timeout_seconds
