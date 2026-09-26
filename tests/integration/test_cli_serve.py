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
