"""How CI runs the browser tests (`tests/browser`).

They need Node, Playwright and Chromium, which the test jobs do not install, so without a job of
their own they were skipped everywhere and nothing guarded the web interface's reflow, contrast and
token handling. The pull-request `browser` job and the nightly one install the stack on purpose;
these tests pin what makes that safe: the version is pinned, a missing stack fails instead of
skipping, and the job is part of the gate.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from strata.core.canon import load_yaml_str

ROOT = Path(__file__).resolve().parents[2]
BROWSER = ROOT / "tests" / "browser"


def _workflow(name: str) -> dict[str, Any]:
    return load_yaml_str((ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8"))


def _run_text(job: dict[str, Any]) -> str:
    return "\n".join(step.get("run", "") for step in job["steps"])


def test_playwright_is_pinned_exactly_and_locked() -> None:
    package = json.loads((BROWSER / "package.json").read_text(encoding="utf-8"))
    version = package["devDependencies"]["playwright"]
    assert version[0].isdigit(), f"{version!r} is a range; pin an exact version"
    lock = json.loads((BROWSER / "package-lock.json").read_text(encoding="utf-8"))
    locked = lock["packages"]["node_modules/playwright"]
    assert locked["version"] == version and locked["integrity"].startswith("sha512-")


@pytest.mark.parametrize("workflow", ["ci.yml", "nightly.yml"])
def test_the_browser_jobs_install_from_the_lockfile_and_require_the_stack(workflow: str) -> None:
    job = _workflow(workflow)["jobs"]["browser"]
    assert job["env"]["STRATA_REQUIRE_BROWSER"] == "1"  # a missing stack fails, never skips
    install = next(s for s in job["steps"] if "npm ci" in s.get("run", ""))
    assert install["working-directory"] == "tests/browser"
    assert "playwright install" in install["run"] and "chromium" in install["run"]
    assert "uv run pytest tests/browser" in _run_text(job)


def test_the_pull_request_browser_job_is_in_the_gate_and_skips_with_the_tests() -> None:
    ci = _workflow("ci.yml")["jobs"]
    assert "browser" in ci["gate"]["needs"]
    assert ci["browser"]["needs"] == ["lint", "test-fast"]
    assert "if" not in ci["browser"]  # the documentation-only skip comes from test-fast


def test_the_nightly_browser_job_covers_every_platform_and_reports_failures() -> None:
    nightly = _workflow("nightly.yml")["jobs"]
    assert set(nightly["browser"]["strategy"]["matrix"]["os"]) == {
        "ubuntu-latest",
        "macos-latest",
        "windows-latest",
    }
    assert "browser" in nightly["open-issue-on-failure"]["needs"]


def test_third_party_actions_in_the_browser_jobs_are_pinned_to_commits() -> None:
    for workflow in ("ci.yml", "nightly.yml"):
        for step in _workflow(workflow)["jobs"]["browser"]["steps"]:
            uses = step.get("uses")
            if uses:
                ref = uses.split("@", 1)[1]
                assert len(ref) == 40 and all(c in "0123456789abcdef" for c in ref), uses


def test_dependabot_keeps_playwright_current() -> None:
    config = load_yaml_str((ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8"))
    npm = [u for u in config["updates"] if u["package-ecosystem"] == "npm"]
    assert [u["directory"] for u in npm] == ["/tests/browser"]
