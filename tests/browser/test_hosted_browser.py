"""A hosted instance in a real browser (openspec:hosted-deployment), on a seeded instance.

`test_pages_browser.py` drives `strata serve`. A hosted instance (`strata host`) has pages of its
own and behaviour that only several signed-in people can show, and this drives those, with the
`hosted` scenario of `pages_smoke.js` over an instance built by `scripts/seed_hosted.py`:

* **its own pages** (sign-in, an invitation, the project list, the sync page, the member screen)
  and the review inside it: reflow at 320 px and 640 px, contrast in light and dark, reduced
  motion, and no Content-Security-Policy violation;
* **the session token**: no form that carries it can be sent with GET, on any page visited;
* **several people at once**, each in a browser context of their own: three are signed in
  together, a record one has yet to screen shows them nobody else's decision, an observer reads
  and is refused a write, a screener is refused the member screen and the adjudication queue;
* **the shared remote**: the dashboard says when the project was last synced, and a conflict with
  the remote is held, shown in the review's terms (the file, the criterion, both versions), offered
  only to a lead, and gone once the lead resolves it;
* **the end of a session**: the sign-in rate limit as a person meets it, and a project page that
  asks for sign-in and then returns to where the person was going.

Optional like the other browser tests (`support.py`); the `browser` CI job requires it.
"""

import json
import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from scripts import seed_hosted

from strata.hosted import accounts
from strata.hosted.instance import Instance
from tests.browser.support import needs_browser

pytestmark = pytest.mark.browser

SCRIPT = Path(__file__).with_name("pages_smoke.js")


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


@pytest.fixture
def instance(tmp_path: Path) -> Iterator[tuple[str, Path]]:
    """A seeded instance being served on a port of its own: its origin and its folder."""
    port = _free_port()
    origin = f"http://127.0.0.1:{port}"
    out = tmp_path / "hosted"
    seed_hosted.seed(out, public_url=origin)
    server = subprocess.Popen(
        [sys.executable, "-m", "strata.cli.main", "host", "--data", str(out / "data")]
        + ["--public-url", origin, "--port", str(port), "--insecure-local-testing"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )
    try:
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=1):
                    break
            except OSError:
                assert server.poll() is None, "strata host exited before it listened"
                time.sleep(0.3)
        else:
            raise AssertionError("strata host never listened")
        yield origin, out
    finally:
        server.kill()
        server.wait(timeout=30)


@needs_browser
def test_a_hosted_instance_in_a_real_browser(instance: tuple[str, Path]) -> None:
    origin, out = instance
    store = Instance(out / "data", environ={}).store
    invitation = "/invite/" + accounts.create_invitation(store, "olive")

    result = subprocess.run(
        ["node", str(SCRIPT), "hosted", origin, seed_hosted.PASSWORD, invitation],
        capture_output=True,
        text=True,
        timeout=900,
    )
    assert result.stdout.strip(), result.stderr
    report = json.loads(result.stdout.strip().splitlines()[-1])
    assert report["failures"] == [], "\n".join(report["failures"])
    assert result.returncode == 0, result.stderr
    found = report["report"]
    assert found["pages"] >= 16  # the instance's pages and the review's, for two people
    assert found["observerWrite"] == 403
    assert all(ratio >= 4.5 for ratio in found["contrast"].values())

    # What the browser did is in the repositories: the lead kept the instance's wording of
    # EXC-01, and it was pushed to the shared remote once the conflict was resolved.
    remote = subprocess.run(
        ["git", "-C", str(out / "remotes" / "disputed.git"), "show", "main:protocol/criteria.yaml"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert seed_hosted.INSTANCE_WORDING in remote and seed_hosted.REMOTE_WORDING not in remote


def test_the_hosted_seed_builds_what_it_says(tmp_path: Path) -> None:
    """Needs no browser: the seeded instance has its projects, members and a real divergence."""
    from strata.hosted import members as members_mod

    out = tmp_path / "hosted"
    built = seed_hosted.seed(out, public_url="http://127.0.0.1:8765", idle_minutes=5)
    instance = Instance(built["data"], environ={})
    assert sorted(p.id for p in instance.list_projects()) == ["disputed", "spacing"]
    assert instance.settings.session_idle_minutes == 5
    roles = {m.username: m.role for m in members_mod.members_of(instance, "spacing")}
    assert roles == {"ada": "lead", "sam": "screener", "olive": "observer"}
    here = (instance.project_dir("disputed") / "protocol" / "criteria.yaml").read_text()
    there = subprocess.run(
        ["git", "-C", str(built["remote:disputed"]), "show", "main:protocol/criteria.yaml"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert seed_hosted.INSTANCE_WORDING in here and seed_hosted.REMOTE_WORDING in there
    with pytest.raises(seed_hosted.SeedError, match="--force"):
        seed_hosted.seed(out)
