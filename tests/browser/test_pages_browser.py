"""Every screen in a real browser (openspec:web-ui#accessibility), on seeded reviews.

Optional, like `test_dropzone_browser.py`: it needs Node with Playwright and a Chromium, and is
skipped where they are not installed (`support.py`; the `browser` CI job requires them). It drives
`pages_smoke.js`, which looks at what a script can
judge:

* **reflow**: no page scrolls sideways at 320 px or 640 px (200 % zoom on a 1280 px screen),
  nothing reaches past the right edge outside a box that scrolls itself, and no word is broken
  mid-word in a table (a squeezed column, "Yea/r", means the table should have scrolled);
* **contrast**: text 4.5:1 and component boundaries 3:1, in light and in dark, on the drop target
  (also while dragging), error messages, warning flags, the screening buttons and links;
* **motion**: with `prefers-reduced-motion: reduce` nothing transitions or animates;
* **no JavaScript**: record a search with a file, review, import, and screen, using only the
  ordinary controls;
* **hostile records**: markup in a title or abstract is shown as text and runs nothing;
* **the session token**: the criteria editor's Preview posts, with and without JavaScript, so
  neither the token nor the reason typed ever appears in an address;
* **Content-Security-Policy**: no page raises a script or style violation.

Building the reviews takes about fifteen seconds (the same commands a person runs, in-process), so
set `STRATA_BROWSER_SEED` to a folder made by `scripts/seed_review.py` to reuse one; the test works
on a copy and never changes it.
"""

import json
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from scripts import seed_review

from tests.browser.support import REQUIRED, needs_browser, playwright_available

pytestmark = pytest.mark.browser

SCRIPT = Path(__file__).with_name("pages_smoke.js")


@pytest.fixture(scope="module")
def master(tmp_path_factory: pytest.TempPathFactory) -> Path:
    existing = os.environ.get("STRATA_BROWSER_SEED")
    if existing:
        return Path(existing)
    out = tmp_path_factory.mktemp("browser-master") / "seed"
    seed_review.seed(out)
    return out


@pytest.fixture
def seeded(master: Path, tmp_path: Path) -> Path:
    """A private copy for one test: the no-JavaScript test imports into `blank`."""
    out = tmp_path / "seed"
    shutil.copytree(master, out)
    return out


def _serve(root: Path, actor: str) -> tuple[subprocess.Popen[str], str]:
    server = subprocess.Popen(
        [sys.executable, "-m", "strata.cli.main", "-C", str(root), "serve", "--port", "0"]
        + ["--no-browser", "--inactivity-timeout", "900", "--actor", actor],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )
    assert server.stdout is not None
    url = ""
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline and not url:
        line = server.stdout.readline()
        if "http://" in line:
            url = line[line.index("http://") :].split()[0]
    assert url, "the server never announced its address"
    time.sleep(1)  # the address is printed just before the port accepts connections
    return server, url


@pytest.fixture
def servers(seeded: Path) -> Iterator[dict[str, str]]:
    started = {
        "pipeline": _serve(seeded / "pipeline", "ada"),
        "dual": _serve(seeded / "dual", "sam"),
        "blank": _serve(seeded / "blank", "ada"),
    }
    try:
        yield {name: url for name, (_, url) in started.items()}
    finally:
        for server, _ in started.values():
            server.kill()
            server.wait(timeout=30)


def _scenario(name: str, *args: str) -> dict[str, object]:
    result = subprocess.run(
        ["node", str(SCRIPT), name, *args], capture_output=True, text=True, timeout=600
    )
    assert result.stdout.strip(), result.stderr
    report = json.loads(result.stdout.strip().splitlines()[-1])
    assert report["failures"] == [], "\n".join(report["failures"])
    assert result.returncode == 0, result.stderr
    return report  # type: ignore[no-any-return]


@needs_browser
def test_no_screen_scrolls_sideways_at_320px_or_200_percent_zoom(servers: dict[str, str]) -> None:
    report = _scenario("layout", servers["pipeline"], servers["dual"])
    assert report["report"]["pages"] >= 40  # type: ignore[index]  # it really did visit them all


@needs_browser
def test_contrast_holds_in_light_and_dark(servers: dict[str, str], seeded: Path) -> None:
    report = _scenario("contrast", servers["blank"], servers["dual"], str(seeded / "exports"))
    measured = report["report"]
    assert isinstance(measured, dict)
    assert measured["dark drop target border"] >= 3 and measured["light drop target border"] >= 3


@needs_browser
def test_reduced_motion_stops_the_drop_target_transitioning(servers: dict[str, str]) -> None:
    report = _scenario("motion", servers["blank"])
    assert report["report"]["reduce"] == []  # type: ignore[index]


@needs_browser
def test_a_search_can_be_recorded_imported_and_screened_without_javascript(
    servers: dict[str, str], seeded: Path
) -> None:
    _scenario("nojs", servers["blank"], str(seeded / "exports"))
    assert len(list((seeded / "blank" / "imports").glob("*/manifest.yaml"))) == 1


@needs_browser
def test_markup_in_a_record_is_shown_as_text_and_runs_nothing(servers: dict[str, str]) -> None:
    _scenario("hostile", servers["dual"])


@needs_browser
def test_the_criteria_preview_keeps_the_session_token_and_the_reason_out_of_the_address(
    servers: dict[str, str], seeded: Path
) -> None:
    _scenario("preview", servers["pipeline"])
    status = subprocess.run(
        ["git", "-C", str(seeded / "pipeline"), "status", "--porcelain"],
        capture_output=True,
        text=True,
    )
    assert status.stdout == "", "a preview must write nothing"


def test_the_browser_stack_is_installed_where_it_is_required() -> None:
    """In CI the `browser` job sets STRATA_REQUIRE_BROWSER after installing Playwright and Chromium,
    so a broken install fails here, loudly, instead of every test above being skipped."""
    if REQUIRED:
        assert playwright_available(), "Node cannot load the Playwright in tests/browser"
