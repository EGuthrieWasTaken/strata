"""The drop zone in a real browser (OpenSpec change `add-web-ui-write-surfaces`, task 4.6).

Optional: it needs Node with Playwright and a Chromium, none of which the project depends on, so it
is skipped wherever they are not installed. Where they are, it drives the whole flow in a browser:
reach the chooser by keyboard, drop files on it, post the form, review, import, and check that the
page raised no script or CSP errors and does not scroll sideways at 320 px.
"""

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from strata.core.init import init_repository

pytestmark = pytest.mark.browser

SCRIPT = Path(__file__).with_name("dropzone_smoke.js")


def _playwright_available() -> bool:
    node = shutil.which("node")
    if node is None:
        return False
    probe = subprocess.run(
        [node, "-e", "require('playwright')"], capture_output=True, text=True, timeout=60
    )
    return probe.returncode == 0


@pytest.mark.skipif(not _playwright_available(), reason="needs Node with Playwright and Chromium")
def test_a_person_can_drop_files_on_a_search_and_import_them(tmp_path: Path) -> None:
    root = tmp_path / "review"
    init_repository(root, title="Browser Test", actor_handle="ethan", actor_name="Ethan")
    server = subprocess.Popen(
        [sys.executable, "-m", "strata.cli.main", "-C", str(root), "serve", "--port", "0"]
        + ["--no-browser", "--inactivity-timeout", "300"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )
    try:
        assert server.stdout is not None
        url = ""
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline and not url:
            line = server.stdout.readline()
            if "http://" in line:
                url = line[line.index("http://") :].split()[0]
        assert url, "the server never announced its address"
        time.sleep(1)  # the address is printed just before the port accepts connections

        result = subprocess.run(
            ["node", str(SCRIPT), url], capture_output=True, text=True, timeout=240
        )

        assert result.returncode == 0, result.stderr or result.stdout
        report = json.loads(result.stdout.strip().splitlines()[-1])
        assert report["existingFormStatus"] != 400  # a form from before searches, from a browser
        assert report["existingFormOrigin"].startswith("http://127.0.0.1:")
        assert report["keyboardReachesChooser"] and report["imported"]
        assert report["dropped"]["count"] == 2 and report["problems"] == []
        assert report["reviewOverflow"] <= 0 and report["formOverflow"] <= 0
        assert len(list((root / "imports").glob("*/manifest.yaml"))) == 2
    finally:
        server.kill()
        server.wait(timeout=30)
