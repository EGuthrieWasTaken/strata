"""What the browser tests share: whether Node and Playwright are there, and when they must be.

Locally the browser tests are optional: without Node and Playwright they are skipped, so nobody has
to install a browser to run the suite. In CI the `browser` job installs the stack on purpose and
sets `STRATA_REQUIRE_BROWSER`; a missing stack then fails the tests instead of skipping them, so a
broken install cannot look like a pass.

To run them yourself: `cd tests/browser && npm ci && npx playwright install chromium`, then
`uv run pytest tests/browser`.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

HERE = Path(__file__).parent
REQUIRED = bool(os.environ.get("STRATA_REQUIRE_BROWSER"))


def playwright_available() -> bool:
    """Whether Node can load the Playwright installed under `tests/browser`."""
    node = shutil.which("node")
    if node is None:
        return False
    probe = subprocess.run(
        [node, "-e", "require('playwright')"],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=HERE,
    )
    return probe.returncode == 0


needs_browser = pytest.mark.skipif(
    not REQUIRED and not playwright_available(),
    reason="needs Node with Playwright and Chromium (tests/browser/package.json)",
)
