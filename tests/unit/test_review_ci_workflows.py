"""The published review-repository workflow and action obey openspec:ci-gate#workflow-hygiene.

Static checks only: no runner is available in the test suite, so these pin the properties that
matter for security and for the coupling with `strata.core.review_ci`.
"""

import re
from pathlib import Path
from typing import Any

import pytest
from ruamel.yaml import YAML

from strata.core.review_ci import MARKER

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "review-ci.yml"
ACTION = ROOT / ".github" / "actions" / "verify" / "action.yml"
SHA = re.compile(r"^[0-9a-f]{40}$")


def _load(path: Path) -> dict[str, Any]:
    data = YAML(typ="safe").load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _steps(doc: dict[str, Any]) -> list[dict[str, Any]]:
    if "jobs" in doc:
        return [step for job in doc["jobs"].values() for step in job["steps"]]
    return list(doc["runs"]["steps"])


@pytest.mark.parametrize("path", [WORKFLOW, ACTION], ids=["workflow", "action"])
def test_third_party_actions_are_pinned_to_a_commit_sha(path: Path) -> None:
    for step in _steps(_load(path)):
        uses = step.get("uses")
        if uses is None or uses.startswith("./"):
            continue
        _, _, ref = uses.partition("@")
        assert SHA.match(ref), f"{uses} is not pinned to a commit SHA"


def test_workflow_is_only_callable_and_never_uses_pull_request_target() -> None:
    doc = _load(WORKFLOW)
    assert set(doc["on"]) == {"workflow_call"}
    code = [
        line
        for line in WORKFLOW.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("#")
    ]
    assert "pull_request_target" not in "\n".join(code)


def test_every_job_has_a_timeout_and_the_workflow_has_a_concurrency_group() -> None:
    doc = _load(WORKFLOW)
    assert doc["concurrency"]["cancel-in-progress"] is True
    for name, job in doc["jobs"].items():
        assert "timeout-minutes" in job, f"job {name} has no timeout-minutes"


def test_only_the_comment_job_can_write_to_the_pull_request_and_it_skips_forks() -> None:
    doc = _load(WORKFLOW)
    assert doc["permissions"] == {"contents": "read"}
    assert "permissions" not in doc["jobs"]["verify"]
    comment_job = doc["jobs"]["pool-impact"]
    assert comment_job["permissions"] == {"contents": "read", "pull-requests": "write"}
    assert "head.repo.full_name == github.repository" in comment_job["if"]


@pytest.mark.parametrize("path", [WORKFLOW, ACTION], ids=["workflow", "action"])
def test_no_expression_is_interpolated_into_a_run_script(path: Path) -> None:
    # Untrusted values (branch names, inputs) must reach scripts through `env`, never `${{ }}`.
    for step in _steps(_load(path)):
        assert "${{" not in step.get("run", ""), step.get("name")


def test_composite_action_declares_a_shell_for_every_run_step() -> None:
    doc = _load(ACTION)
    assert doc["runs"]["using"] == "composite"
    for step in _steps(doc):
        if "run" in step:
            assert step.get("shell") == "bash", step.get("name")


def test_workflow_and_python_module_agree_on_the_marker_and_the_subcommands() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert MARKER in text
    used = set(re.findall(r"-m strata\.core\.review_ci ([a-z-]+)", text))
    assert used == {"comment", "criteria-changed"}
