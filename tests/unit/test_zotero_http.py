"""The real HTTP transport, against a server on the loopback interface (no internet)."""

from __future__ import annotations

import json
import threading
import urllib.request
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from strata.integrations.zotero.http import TransportError, UrllibTransport


class _Handler(BaseHTTPRequestHandler):
    def _reply(self, status: int, body: bytes, headers: dict[str, str] | None = None) -> None:
        self.send_response(status)
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path.startswith("/busy"):
            self._reply(429, b"slow down", {"Retry-After": "9"})
        else:
            self._reply(200, json.dumps({"path": self.path}).encode(), {"Zotero-API-Version": "3"})

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        echoed = {
            "body": json.loads(self.rfile.read(length)),
            "token": self.headers.get("Zotero-Write-Token"),
        }
        self._reply(200, json.dumps(echoed).encode())

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        pass


@pytest.fixture
def server() -> Iterator[str]:
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_port}"
    httpd.shutdown()
    httpd.server_close()


def test_a_get_returns_status_body_and_lower_cased_headers(server: str) -> None:
    response = UrllibTransport().request("GET", f"{server}/api/x?a=1", {}, None, 5.0)

    assert response.status == 200
    assert json.loads(response.body) == {"path": "/api/x?a=1"}
    assert response.headers["zotero-api-version"] == "3"


def test_a_post_sends_its_body_and_headers(server: str) -> None:
    response = UrllibTransport().request(
        "POST",
        f"{server}/api/items",
        {"Zotero-Write-Token": "abc", "Content-Type": "application/json"},
        b'[{"itemType": "document"}]',
        5.0,
    )

    assert json.loads(response.body) == {"body": [{"itemType": "document"}], "token": "abc"}


def test_an_error_status_is_a_response_not_an_exception(server: str) -> None:
    response = UrllibTransport().request("GET", f"{server}/busy", {}, None, 5.0)

    assert response.status == 429
    assert response.headers["retry-after"] == "9"
    assert response.body == b"slow down"


def test_a_connection_that_is_refused_is_a_transport_error() -> None:
    with pytest.raises(TransportError):
        UrllibTransport().request("GET", "http://127.0.0.1:1/api/x", {}, None, 2.0)


def test_the_local_zotero_is_never_sent_through_a_proxy(
    server: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A proxy in the environment is for the internet: pointed at a port nothing listens on, it
    # would fail every request that used it. urllib builds its default opener lazily from the
    # environment, so reset it to make the variable count.
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("http_proxy", "http://127.0.0.1:9")
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.delenv("no_proxy", raising=False)
    monkeypatch.setattr(urllib.request, "_opener", None)

    response = UrllibTransport().request("GET", f"{server}/api/x", {}, None, 5.0)

    assert response.status == 200
