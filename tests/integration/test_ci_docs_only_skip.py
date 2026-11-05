"""How `.github/workflows/ci.yml` wires the documentation-only skip
(openspec:ci-gate#documentation-only-pull-requests-skip-the-test-jobs).

The classifier is tested in `tests/unit/test_ci_changes.py`. What those tests cannot see is whether
the workflow uses it so that a skip can never hide a test that should have run, and that is what
fails silently: a skipped job counts as a pass at the `gate`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from strata.core.canon import load_yaml_str

ROOT = Path(__file__).resolve().parents[2]

# Every job that runs the tests, directly or by waiting for `test-fast`.
TEST_JOBS = ["test", "statistical", "determinism", "coverage", "benchmark", "traceability"]


@pytest.fixture(scope="module")
def jobs() -> dict[str, Any]:
    text = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    return load_yaml_str(text)["jobs"]


def _needs(job: dict[str, Any]) -> list[str]:
    needs = job.get("needs", [])
    return [needs] if isinstance(needs, str) else list(needs)


def test_the_classifier_job_reads_the_whole_history_and_runs_the_script(
    jobs: dict[str, Any],
) -> None:
    job = jobs["code-changes"]
    assert job["outputs"] == {"code": "${{ steps.classify.outputs.code }}"}
    checkout, classify = job["steps"]
    assert checkout["with"]["fetch-depth"] == 0  # the base commit has to be there to diff against
    assert classify["id"] == "classify"
    assert classify["run"] == "python3 scripts/ci_changes.py"
    # Inputs reach the script through the environment, never spliced into the shell text.
    assert classify["env"] == {
        "EVENT": "${{ github.event_name }}",
        "BASE_SHA": "${{ github.event.pull_request.base.sha }}",
    }


def test_the_tests_wait_for_the_classifier_and_run_only_when_it_says_code(
    jobs: dict[str, Any],
) -> None:
    fast = jobs["test-fast"]
    assert _needs(fast) == ["code-changes"]
    assert fast["if"] == "needs.code-changes.outputs.code == 'true'"


@pytest.mark.parametrize("name", TEST_JOBS)
def test_every_other_test_job_is_skipped_with_test_fast(jobs: dict[str, Any], name: str) -> None:
    job = jobs[name]
    assert "test-fast" in _needs(job)
    # A job-level condition of its own (`always()`, `!cancelled()`, ...) would run it after a
    # skipped `test-fast`, so the documentation-only skip would silently stop skipping it.
    assert "if" not in job


def test_lint_runs_on_every_pull_request(jobs: dict[str, Any]) -> None:
    assert "if" not in jobs["lint"] and "needs" not in jobs["lint"]


def test_the_gate_always_runs_and_waits_for_the_classifier_and_every_job_it_can_skip(
    jobs: dict[str, Any],
) -> None:
    gate = jobs["gate"]
    assert gate["if"] == "always()"
    needs = set(_needs(gate))
    # `code-changes` is here so that a classifier that failed to run fails the gate: its dependants
    # would otherwise all be "skipped", and the gate accepts "skipped".
    assert {"code-changes", "lint", "test-fast", "test", "statistical", "determinism"} <= needs
    assert {"coverage", "container"} <= needs
    run = "\n".join(step.get("run", "") for step in gate["steps"])
    assert '("success", "skipped")' in run


def test_nothing_runs_the_tests_without_depending_on_the_classifier(jobs: dict[str, Any]) -> None:
    """Every job that is not a documentation or container job reaches `code-changes`."""
    unconditional = {"code-changes", "lint", "container-changes", "container", "gate"}

    def reaches_classifier(name: str, seen: frozenset[str] = frozenset()) -> bool:
        if name == "code-changes":
            return True
        if name in seen:
            return False
        return any(reaches_classifier(dep, seen | {name}) for dep in _needs(jobs[name]))

    for name in jobs:
        if name not in unconditional:
            assert reaches_classifier(name), f"{name} would run on a documentation-only change"
