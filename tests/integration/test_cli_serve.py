"""`strata serve`: openspec:web-ui, openspec:cli.

Unlike every other `test_cli_*.py` file, this one cannot use
`typer.testing.CliRunner` (in-process, synchronous): `strata serve` blocks
running a real ASGI server until it is interrupted or its inactivity
timeout elapses (tests/e2e/test_e2e_09_interrupted_screening.py hit the
same constraint for `strata screen` under SIGKILL specifically; this is
the same "drive a real subprocess" pattern, for the same reason). These
tests exercise the actual CLI wiring end to end: real port binding, a real
HTTP request against the opened URL, and a real process exit once idle --
the parts `tests/unit/test_web_server.py`'s pure-logic tests and
`tests/integration/test_web_app.py`'s in-process ASGI-transport tests
cannot reach.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from typer.testing import CliRunner

from strata.cli.main import EXIT_OK, app

runner = CliRunner()


def _init(tmp_path: Path) -> Path:
    root = tmp_path / "review"
    result = runner.invoke(
        app,
        ["init", str(root), "--title", "Serve Test", "--actor", "ethan", "--actor-name", "Ethan"],
    )
    assert result.exit_code == EXIT_OK, result.output
    return root


_URL_RE = re.compile(r"http://\S+")


def _wait_for_url(proc: subprocess.Popen, deadline: float) -> str:
    """The URL `strata serve` announces on startup, tolerant of `rich`
    wrapping the announcement across several output lines when stdout
    isn't a real terminal."""
    assert proc.stdout is not None
    lines: list[str] = []
    while time.monotonic() < deadline:
        line = proc.stdout.readline()
        if not line:
            break
        lines.append(line)
        match = _URL_RE.search(line)
        if match:
            return match.group(0).rstrip()
    raise AssertionError(f"server never printed its listening URL; got: {lines!r}")


def test_serve_starts_serves_the_dashboard_and_exits_after_inactivity_timeout(
    tmp_path: Path,
) -> None:
    root = _init(tmp_path)
    env = {**os.environ, "PYTHONUNBUFFERED": "1"}
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "strata.cli.main",
            "-C",
            str(root),
            "serve",
            "--port",
            "0",
            "--no-browser",
            "--inactivity-timeout",
            "2",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        env=env,
    )
    try:
        url = _wait_for_url(proc, time.monotonic() + 15.0)
        assert url.startswith("http://127.0.0.1:")

        # The URL is announced as soon as the port is *chosen*, slightly
        # before uvicorn has finished starting to actually accept
        # connections on it -- retry briefly rather than racing that gap.
        body = ""
        for _ in range(30):
            try:
                with urllib.request.urlopen(url, timeout=1) as resp:
                    body = resp.read().decode("utf-8")
                    assert resp.status == 200
                    break
            except OSError:
                time.sleep(0.2)
        assert "Serve Test" in body

        # The server should exit on its own once idle past the timeout --
        # no signal needed, unlike the SIGKILL scenario in E2E-09.
        proc.wait(timeout=15)
        assert proc.returncode == 0
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=10)


def test_serve_non_loopback_host_without_token_is_a_usage_error(tmp_path: Path) -> None:
    root = _init(tmp_path)
    result = runner.invoke(app, ["-C", str(root), "serve", "--host", "0.0.0.0", "--port", "0"])
    assert result.exit_code != EXIT_OK
    assert "token" in result.output.lower()


def test_serve_unknown_actor_is_a_usage_error(tmp_path: Path) -> None:
    root = _init(tmp_path)
    result = runner.invoke(app, ["-C", str(root), "serve", "--actor", "nobody", "--port", "0"])
    assert result.exit_code != EXIT_OK
    assert "unknown actor" in result.output.lower()


def test_serve_multiple_actors_without_choosing_one_is_a_usage_error(tmp_path: Path) -> None:
    root = _init(tmp_path)
    add = runner.invoke(
        app,
        [
            "--why",
            "Sam is joining the review team.",
            "-C",
            str(root),
            "actor",
            "add",
            "sam",
            "Sam",
            "--role",
            "screener",
        ],
    )
    assert add.exit_code == EXIT_OK, add.output
    result = runner.invoke(app, ["-C", str(root), "serve", "--port", "0"])
    assert result.exit_code != EXIT_OK
    assert "multiple actors" in result.output.lower()


def test_serve_prints_a_warning_when_binding_beyond_loopback(tmp_path: Path) -> None:
    root = _init(tmp_path)
    env = {**os.environ, "PYTHONUNBUFFERED": "1"}
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "strata.cli.main",
            "-C",
            str(root),
            "serve",
            "--host",
            "0.0.0.0",
            "--port",
            "0",
            "--token",
            "fixed-token-for-testing",
            "--no-browser",
            "--inactivity-timeout",
            "1",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        env=env,
    )
    try:
        url = _wait_for_url(proc, time.monotonic() + 15.0)
        assert url.startswith("http://0.0.0.0:")
        proc.wait(timeout=15)
        assert proc.returncode == 0
        assert "exposes this server" in (proc.stderr.read() if proc.stderr else "")
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=10)


# --- openspec:cli#serve-behind-a-public-url ------------------------------------------------------


def test_an_invalid_public_url_is_a_usage_error_naming_the_scheme(tmp_path: Path) -> None:
    from strata.cli.main import EXIT_USAGE

    root = _init(tmp_path)
    for bad in ("localhost", "localhost:8765", "ftp://example.org"):
        result = runner.invoke(app, ["-C", str(root), "serve", "--public-url", bad, "--port", "0"])
        assert result.exit_code == EXIT_USAGE, (bad, result.output)
        assert "scheme" in result.output.lower() or "host" in result.output.lower()
    from_env = runner.invoke(
        app, ["-C", str(root), "serve", "--port", "0"], env={"STRATA_PUBLIC_URL": "localhost"}
    )
    assert from_env.exit_code == EXIT_USAGE and "scheme" in from_env.output.lower()


def _get(url: str, host: str | None = None) -> tuple[int, str]:
    import urllib.error

    request = urllib.request.Request(url, headers={"Host": host} if host else {})
    try:
        with urllib.request.urlopen(request, timeout=2) as response:
            return response.status, response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8")


def test_serve_behind_a_public_url_announces_it_and_validates_against_it(tmp_path: Path) -> None:
    from strata.web.server import pick_ephemeral_port

    root = _init(tmp_path)
    port = pick_ephemeral_port("127.0.0.1")
    env = {**os.environ, "PYTHONUNBUFFERED": "1", "STRATA_TOKEN": "token-from-the-environment"}
    proc = subprocess.Popen(
        [
            sys.executable, "-m", "strata.cli.main", "-C", str(root), "serve",
            "--host", "0.0.0.0", "--port", str(port), "--no-browser", "--inactivity-timeout", "30",
            "--public-url", f"http://localhost:{port}",
        ],  # fmt: skip
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1, env=env,
    )  # fmt: skip
    try:
        url = _wait_for_url(proc, time.monotonic() + 15.0)
        # the announced URL is the one a browser outside the container uses, with the token
        assert url == f"http://localhost:{port}/?token=token-from-the-environment"
        reach = f"http://127.0.0.1:{port}"
        for _ in range(50):
            try:
                assert _get(f"{reach}/healthz")[0] == 200
                break
            except OSError:
                time.sleep(0.2)
        status, body = _get(f"{reach}/healthz", host="10.1.2.3:9999")
        assert status == 200 and '"ok"' in body  # an orchestrator's probe, any Host
        status, body = _get(f"{reach}/?token=token-from-the-environment", host=f"localhost:{port}")
        assert status == 200 and "Serve Test" in body
        status, body = _get(
            f"{reach}/?token=token-from-the-environment", host=f"attacker.example:{port}"
        )
        assert status == 400
        status, _ = _get(f"{reach}/?token=token-from-the-environment")  # Host: 127.0.0.1:<port>
        assert status == 400  # the bind-derived names are not accepted once a public URL is given
    finally:
        proc.kill()
        proc.wait(timeout=10)


# ----------------------------------------------------------------------------- upload limit


def test_serve_refuses_an_upload_limit_below_one_megabyte(tmp_path: Path) -> None:
    root = _init(tmp_path)

    result = runner.invoke(
        app, ["-C", str(root), "serve", "--port", "0", "--max-upload-mb", "0", "--no-browser"]
    )

    assert result.exit_code == 2
    assert "--max-upload-mb must be at least 1" in result.output


def test_serve_documents_the_upload_limit_in_its_help() -> None:
    result = runner.invoke(app, ["serve", "--help"])

    assert result.exit_code == EXIT_OK
    # Where colour is forced (CI on Windows) the option name arrives split by escape codes.
    assert "--max-upload-mb" in re.sub(r"\x1b\[[0-9;]*m", "", result.output)


def test_a_real_server_enforces_the_upload_limit_before_reading_the_body(tmp_path: Path) -> None:
    import http.client
    from urllib.parse import parse_qs, urlsplit

    root = _init(tmp_path)
    env = {**os.environ, "PYTHONUNBUFFERED": "1"}
    proc = subprocess.Popen(
        [sys.executable, "-m", "strata.cli.main", "-C", str(root), "serve", "--port", "0"]
        + ["--no-browser", "--max-upload-mb", "1", "--inactivity-timeout", "120"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        env=env,
    )
    try:
        url = _wait_for_url(proc, time.monotonic() + 30.0)
        parts = urlsplit(url)
        token = parse_qs(parts.query)["token"][0]
        host, port = parts.hostname or "127.0.0.1", parts.port or 80

        def connect() -> http.client.HTTPConnection:
            return http.client.HTTPConnection(host, port, timeout=30)

        cookie = ""
        for _ in range(50):
            try:
                conn = connect()
                conn.request("GET", f"/?token={token}")
                response = conn.getresponse()
                response.read()
                cookie = response.getheader("Set-Cookie", "").split(";")[0]
                conn.close()
                break
            except OSError:
                time.sleep(0.2)
        assert cookie.startswith("strata_session=")

        def multipart(size: int) -> bytes:
            return (
                b'--x\r\nContent-Disposition: form-data; name="csrf_token"\r\n\r\n'
                + token.encode()
                + b'\r\n--x\r\nContent-Disposition: form-data; name="files"; filename="a.ris"\r\n'
                + b"Content-Type: application/octet-stream\r\n\r\n"
                + b"x" * size
                + b"\r\n--x--\r\n"
            )

        headers = {"Cookie": cookie, "Content-Type": "multipart/form-data; boundary=x"}

        # Over the limit: refused from its declared size.
        conn = connect()
        conn.request("POST", "/nowhere", body=multipart(2 * 1024 * 1024), headers=headers)
        over = conn.getresponse()
        assert over.status == 413
        assert "limit is 1 MB" in over.read().decode()
        conn.close()

        # No declared size (chunked): refused, not read.
        conn = connect()
        conn.request(
            "POST", "/nowhere", body=iter([multipart(10)]), headers=headers, encode_chunked=True
        )
        chunked = conn.getresponse()
        assert chunked.status == 411
        conn.close()

        # Within the limit: passes the middleware (the path does not exist, hence 404).
        conn = connect()
        conn.request("POST", "/nowhere", body=multipart(1024), headers=headers)
        within = conn.getresponse()
        assert within.status == 404
        conn.close()
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=10)
