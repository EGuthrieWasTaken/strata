"""`strata init --ci`, `strata ci amendment|comment`, and the workflow files they are used by
(openspec:review-repository-ci)."""

# ruff: noqa: E501
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from strata import gitio
from strata.ci import workflows
from strata.cli.main import EXIT_GENERIC, EXIT_OK, EXIT_USAGE, EXIT_VALIDATION, app
from strata.core.canon import load_yaml_str
from strata.core.repo import Repo, open_repo
from strata.core.verify import verify_repository
from strata.protocol import criteria as criteria_mod
from tests.integration._sync import commit
from tests.unit._m5 import import_into, search

runner = CliRunner()
ROOT = Path(__file__).resolve().parents[2]
# The workflow's `run:` steps are bash on a Linux runner; they are run here with a fake `gh`.
posix_shell = pytest.mark.skipif(
    sys.platform == "win32", reason="runs the workflow's POSIX shell steps"
)


def _init(path: Path, *flags: str, code: int = EXIT_OK) -> Any:
    result = runner.invoke(
        app,
        [
            "init",
            str(path),
            "--title",
            "CI review",
            "--actor",
            "ethan",
            "--actor-name",
            "Ethan",
            *flags,
        ],
    )
    assert result.exit_code == code, result.output
    return result


def _cli(repo: Repo | Path, *args: str, code: int = EXIT_OK) -> Any:
    root = repo.root if isinstance(repo, Repo) else repo
    result = runner.invoke(app, ["-C", str(root), *args])
    assert result.exit_code == code, result.output
    return result


def _on(workflow: dict[str, Any]) -> Any:
    return workflow.get("on", workflow.get(True))  # YAML 1.1 reads a bare `on` as true


# --- strata init --ci ------------------------------------------------------------------------------


def test_init_ci_installs_a_workflow_that_runs_the_checks_on_pull_requests(tmp_path: Path) -> None:
    _init(tmp_path / "review", "--ci")
    path = tmp_path / "review" / ".github" / "workflows" / "strata.yml"
    assert path.is_file()
    workflow = load_yaml_str(path.read_text(encoding="utf-8"))
    assert "pull_request" in _on(workflow)
    job = workflow["jobs"]["strata"]
    assert (
        job["uses"]
        == f"{workflows.STRATA_REPOSITORY}/{workflows.REUSABLE_WORKFLOW}@{workflows.default_ref()}"
    )
    assert job["with"]["strata-ref"] == workflows.default_ref()
    assert job["permissions"] == {"contents": "read", "pull-requests": "write"}
    # in the repository's first commit, and the repository still verifies with it
    files = gitio.run(
        ["show", "--name-only", "--format=", "HEAD"], cwd=tmp_path / "review"
    ).stdout.split()
    assert ".github/workflows/strata.yml" in files
    assert verify_repository(open_repo(tmp_path / "review")).ok


def test_init_without_the_flag_writes_no_workflow(tmp_path: Path) -> None:
    _init(tmp_path / "review")
    assert not (tmp_path / "review" / ".github").exists()


def test_init_ci_takes_a_ref_and_a_methodologist(tmp_path: Path) -> None:
    _init(tmp_path / "review", "--ci", "--ci-ref", "main", "--methodologist", "@octocat")
    workflow = load_yaml_str(
        (tmp_path / "review" / ".github" / "workflows" / "strata.yml").read_text()
    )
    job = workflow["jobs"]["strata"]
    assert job["uses"].endswith("@main") and job["with"] == {
        "strata-ref": "main",
        "methodologist": "octocat",
    }


def test_the_ref_and_methodologist_need_ci(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "init",
            str(tmp_path / "r"),
            "--title",
            "T",
            "--actor",
            "ethan",
            "--methodologist",
            "octocat",
        ],
    )
    assert result.exit_code == EXIT_USAGE and "only apply with --ci" in result.output
    assert not (tmp_path / "r").exists()


# --- the files the installed workflow points at ------------------------------------------------------


def test_the_installed_workflow_calls_a_reusable_workflow_that_exists_with_the_inputs_it_passes() -> (
    None
):
    caller = load_yaml_str(workflows.caller_workflow(ref="v1.2.3", methodologist="octocat"))
    reusable_path = ROOT / workflows.REUSABLE_WORKFLOW
    assert caller["jobs"]["strata"]["uses"].split("@")[0].endswith(workflows.REUSABLE_WORKFLOW)
    reusable = load_yaml_str(reusable_path.read_text(encoding="utf-8"))
    inputs = _on(reusable)["workflow_call"]["inputs"]
    assert set(caller["jobs"]["strata"]["with"]) <= set(inputs)
    assert inputs["strata-ref"]["required"] is True
    assert {"verify", "pool-impact"} <= set(reusable["jobs"])
    # the caller's permissions cover what the called jobs ask for
    assert reusable["jobs"]["pool-impact"]["permissions"]["pull-requests"] == "write"
    assert caller["jobs"]["strata"]["permissions"]["pull-requests"] == "write"


def test_the_reusable_workflow_and_the_action_pin_third_party_actions_to_commits() -> None:
    for relative in (workflows.REUSABLE_WORKFLOW, "actions/verify/action.yml"):
        text = (ROOT / relative).read_text(encoding="utf-8")
        uses = re.findall(r"^\s*(?:- )?uses:\s*(\S+)", text, flags=re.MULTILINE)
        assert uses, relative
        for ref in uses:
            assert re.fullmatch(r"[\w.-]+/[\w./-]+@[0-9a-f]{40}", ref), (relative, ref)
    assert "pull_request_target" not in (ROOT / workflows.REUSABLE_WORKFLOW).read_text(
        encoding="utf-8"
    ).replace("never `pull_request_target`", "")


def test_the_verify_action_installs_strata_from_its_own_checkout_and_runs_verify() -> None:
    action = load_yaml_str((ROOT / "actions" / "verify" / "action.yml").read_text(encoding="utf-8"))
    assert action["runs"]["using"] == "composite" and action["inputs"]["path"]["default"] == "."
    scripts = " ".join(step.get("run", "") for step in action["runs"]["steps"])
    assert "$GITHUB_ACTION_PATH/../.." in scripts and "strata verify" in scripts
    assert (ROOT / "actions" / "verify" / ".." / ".." / "pyproject.toml").is_file()


def test_the_reusable_workflow_only_calls_commands_that_exist() -> None:
    reusable = load_yaml_str((ROOT / workflows.REUSABLE_WORKFLOW).read_text(encoding="utf-8"))
    scripts = "\n".join(
        step.get("run", "") for job in reusable["jobs"].values() for step in job["steps"]
    )
    commands = re.findall(r"^\s*strata (?:--json )?(?:-C \S+ )?([a-z]+(?: [a-z]+)?)", scripts, re.M)
    names = {c if c.startswith("ci ") else c.split()[0] for c in commands}
    assert {"verify", "status", "ci amendment", "ci comment"} <= names
    for command in commands:
        result = runner.invoke(app, [*command.split()[:2], "--help"])
        assert result.exit_code == 0, (command, result.output)
    assert "protocol-amendment" in scripts


# --- strata ci amendment / comment, composed as the workflow does ---------------------------------------


def _review_on_a_branch(tmp_path: Path) -> tuple[Repo, str]:
    _init(tmp_path / "review", "--ci", "--methodologist", "octocat")
    repo = open_repo(tmp_path / "review")
    for kind, label in (("inclusion", "Human participants"), ("exclusion", "Wrong population")):
        criteria_mod.add_criterion(
            repo, kind=kind, label=label, definition=label + ".",  # type: ignore[arg-type]
            applies_at=["title-abstract"], actor="ethan", rationale="Protocol.",
        )  # fmt: skip
    import_into(repo, tmp_path, "export.json", list(range(1, 9)), search_id=search(repo, "MEDLINE"))
    commit(repo, "seed: criteria and records")
    return repo, gitio.current_commit(repo.root)


def test_a_change_to_the_criteria_is_detected_and_described(tmp_path: Path) -> None:
    repo, base = _review_on_a_branch(tmp_path)
    assert json.loads(_cli(repo, "ci", "amendment", "--base", base).output)["changed"] is False
    criteria_mod.add_criterion(
        repo, kind="exclusion", label="Participants under 18", definition="Younger than 18.",
        applies_at=["title-abstract"], actor="ethan", rationale="Children were out of scope.",
    )  # fmt: skip
    commit(repo, "criteria: add an exclusion")
    found = json.loads(_cli(repo, "ci", "amendment", "--base", base, "--head", "HEAD").output)
    assert found["changed"] is True and found["added"] == ["EXC-02"]
    assert found["version_after"] == found["version_before"] + 1


def test_a_reformatted_criteria_file_is_not_an_amendment(tmp_path: Path) -> None:
    repo, base = _review_on_a_branch(tmp_path)
    path = repo.path("protocol", "criteria.yaml")
    path.write_text(
        "# a comment added by hand\n" + path.read_text(encoding="utf-8"), encoding="utf-8"
    )
    commit(repo, "criteria: comment only")
    assert json.loads(_cli(repo, "ci", "amendment", "--base", base).output)["changed"] is False


def test_an_unknown_base_is_an_error_not_a_crash(tmp_path: Path) -> None:
    repo, _base = _review_on_a_branch(tmp_path)
    result = runner.invoke(app, ["-C", str(repo.root), "ci", "amendment", "--base", "no-such-ref"])
    assert result.exit_code == 0  # a ref git cannot resolve reads as "no criteria file there"
    assert json.loads(result.output)["added"]  # so every criterion counts as added


def test_the_workflow_steps_compose_into_a_comment(tmp_path: Path) -> None:
    repo, base = _review_on_a_branch(tmp_path)
    criteria_mod.edit_criterion(
        repo, "EXC-01", direction="tightened", actor="ethan",
        rationale="Narrowing the population.", definition="Wrong population: adults only.",
    )  # fmt: skip
    commit(repo, "criteria: tighten EXC-01")
    out = tmp_path / "out"
    out.mkdir()
    (out / "head.json").write_text(_cli(repo, "--json", "status").output, encoding="utf-8")
    base_tree = tmp_path / "base"
    gitio.run(["worktree", "add", "--detach", str(base_tree), base], cwd=repo.root)
    (out / "base.json").write_text(_cli(base_tree, "--json", "status").output, encoding="utf-8")
    (out / "amendment.json").write_text(
        _cli(repo, "ci", "amendment", "--base", base).output, encoding="utf-8"
    )
    comment = _cli(
        repo, "ci", "comment", str(out / "base.json"), str(out / "head.json"),
        "--amendment", str(out / "amendment.json"), "--methodologist", "octocat",
    ).output  # fmt: skip
    assert comment.startswith("<!-- strata-review-ci -->")
    assert "**Records in the pool:** none enter or leave (8)." in comment
    assert "Changed: EXC-01 (definition)" in comment and "requested from @octocat" in comment
    # with a base that is not a strata repository the workflow writes `null`
    (out / "none.json").write_text("null", encoding="utf-8")
    assert (
        "no strata repository"
        in _cli(repo, "ci", "comment", str(out / "none.json"), str(out / "head.json")).output
    )


def test_comment_inputs_that_are_not_status_documents_are_usage_errors(tmp_path: Path) -> None:
    (tmp_path / "bad.json").write_text("{not json", encoding="utf-8")
    (tmp_path / "list.json").write_text("[]", encoding="utf-8")
    for args in (
        ["ci", "comment", str(tmp_path / "missing.json"), str(tmp_path / "bad.json")],
        ["ci", "comment", str(tmp_path / "bad.json"), str(tmp_path / "bad.json")],
        ["ci", "comment", "null", str(tmp_path / "list.json")],
    ):
        assert runner.invoke(app, args).exit_code == EXIT_USAGE, args
    assert EXIT_GENERIC and EXIT_VALIDATION  # exit codes the workflow does not rely on


# --- the workflow's shell steps, run for real against a fake `gh` ----------------------------------------

FAKE_GH = """#!/bin/bash
echo "$*" >> "$GH_LOG"
if [ "$1" = api ] && [[ "$*" == *--paginate* ]]; then printf '%s' "${EXISTING_COMMENT_ID:-}"; fi
if [[ "$*" == *--add-reviewer* ]] && [ -n "${GH_REFUSE_REVIEWER:-}" ]; then exit 1; fi
exit 0
"""


def _step(name: str) -> dict[str, Any]:
    reusable = load_yaml_str((ROOT / workflows.REUSABLE_WORKFLOW).read_text(encoding="utf-8"))
    steps = [s for job in reusable["jobs"].values() for s in job["steps"] if s.get("name") == name]
    assert len(steps) == 1, name
    return steps[0]


class _Runner:
    """Runs the workflow's `run:` steps the way a runner would: bash -e, with $GITHUB_ENV carried over."""

    def __init__(self, tmp_path: Path, repo: Repo, base_sha: str, **extra: str) -> None:
        import os
        import shutil

        self.repo = repo
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        gh = bin_dir / "gh"
        gh.write_text(FAKE_GH, encoding="utf-8")
        gh.chmod(0o755)
        strata = shutil.which("strata")
        assert strata, "the strata command must be on PATH to run the workflow's steps"
        self.log = tmp_path / "gh.log"
        self.github_env = tmp_path / "github-env"
        self.summary = tmp_path / "summary.md"
        for path in (self.log, self.github_env, self.summary):
            path.write_text("", encoding="utf-8")
        (tmp_path / "runner").mkdir()
        self.env = {
            **os.environ,
            "PATH": f"{bin_dir}:{Path(strata).parent}:{os.environ['PATH']}",
            "RUNNER_TEMP": str(tmp_path / "runner"),
            "GITHUB_ENV": str(self.github_env),
            "GITHUB_STEP_SUMMARY": str(self.summary),
            "GITHUB_REPOSITORY": "example/review",
            "GH_LOG": str(self.log),
            "GH_TOKEN": "unused",
            "PR": "7",
            "BASE_SHA": base_sha,
            "METHODOLOGIST": "octocat",
            "CAN_WRITE": "true",
            **extra,
        }

    def run(self, name: str) -> Any:
        import subprocess

        step = _step(name)
        for line in self.github_env.read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition("=")
            self.env[key] = value
        return subprocess.run(
            ["bash", "-e", "-c", step["run"]], cwd=self.repo.root, env=self.env,
            capture_output=True, text=True, check=False,
        )  # fmt: skip

    def gh_calls(self) -> list[str]:
        return self.log.read_text(encoding="utf-8").splitlines()


COMPARE = "Compare the review before and after"
POST = "Post the comment"
LABEL = "Label a change to the criteria and ask the methodologist"


@posix_shell
def test_the_workflow_posts_a_comment_and_labels_a_change_to_the_criteria(tmp_path: Path) -> None:
    repo, base = _review_on_a_branch(tmp_path)
    criteria_mod.add_criterion(
        repo, kind="exclusion", label="Participants under 18", definition="Younger than 18.",
        applies_at=["title-abstract"], actor="ethan", rationale="Children were out of scope.",
    )  # fmt: skip
    commit(repo, "criteria: add an exclusion")
    run = _Runner(tmp_path, repo, base)
    for step in (COMPARE, POST, LABEL):
        done = run.run(step)
        assert done.returncode == 0, (step, done.stderr)
    assert "Added: EXC-02" in run.summary.read_text(encoding="utf-8")
    calls = run.gh_calls()
    assert any(
        c.startswith("pr comment 7 --body-file ") and c.endswith("comment.md") for c in calls
    )
    assert "pr edit 7 --add-label protocol-amendment" in calls
    assert "pr edit 7 --add-reviewer octocat" in calls
    assert not any("--remove-label" in c for c in calls)


@posix_shell
def test_the_workflow_updates_its_one_comment_instead_of_adding_another(tmp_path: Path) -> None:
    repo, base = _review_on_a_branch(tmp_path)
    run = _Runner(tmp_path, repo, base, EXISTING_COMMENT_ID="4242")
    assert run.run(COMPARE).returncode == 0 and run.run(POST).returncode == 0
    calls = run.gh_calls()
    assert any(
        c.startswith("api --method PATCH repos/example/review/issues/comments/4242 -F body=@")
        for c in calls
    )
    assert not any(c.startswith("pr comment") for c in calls)


@posix_shell
def test_a_pull_request_that_leaves_the_criteria_alone_is_not_labelled(tmp_path: Path) -> None:
    repo, base = _review_on_a_branch(tmp_path)
    run = _Runner(tmp_path, repo, base)
    for step in (COMPARE, LABEL):
        assert run.run(step).returncode == 0
    calls = run.gh_calls()
    assert (
        "pr edit 7 --remove-label protocol-amendment" in calls
    )  # in case an earlier push added it
    assert not any("--add-label" in c or "--add-reviewer" in c for c in calls)


@posix_shell
def test_a_review_request_that_github_refuses_does_not_fail_the_check(tmp_path: Path) -> None:
    repo, base = _review_on_a_branch(tmp_path)
    criteria_mod.add_criterion(
        repo, kind="inclusion", label="Adults", definition="Adults only.",
        applies_at=["title-abstract"], actor="ethan", rationale="Protocol clarification.",
    )  # fmt: skip
    commit(repo, "criteria: add an inclusion")
    run = _Runner(tmp_path, repo, base, GH_REFUSE_REVIEWER="1")
    assert run.run(COMPARE).returncode == 0
    done = run.run(LABEL)
    assert done.returncode == 0 and "could not request a review from octocat" in done.stdout


@posix_shell
def test_without_a_methodologist_nobody_is_asked_to_review(tmp_path: Path) -> None:
    repo, base = _review_on_a_branch(tmp_path)
    criteria_mod.add_criterion(
        repo, kind="inclusion", label="Adults", definition="Adults only.",
        applies_at=["title-abstract"], actor="ethan", rationale="Protocol clarification.",
    )  # fmt: skip
    commit(repo, "criteria: add an inclusion")
    run = _Runner(tmp_path, repo, base, METHODOLOGIST="")
    assert run.run(COMPARE).returncode == 0 and run.run(LABEL).returncode == 0
    assert "no methodologist is configured" in run.summary.read_text(encoding="utf-8")
    assert not any("--add-reviewer" in c for c in run.gh_calls())


@posix_shell
def test_a_base_without_a_strata_repository_still_gets_a_comment(tmp_path: Path) -> None:
    repo, _base = _review_on_a_branch(tmp_path)
    empty_tree = gitio.run(
        ["hash-object", "-t", "tree", "-w", "/dev/null"], cwd=repo.root
    ).stdout.strip()
    bare_base = gitio.run(
        ["commit-tree", empty_tree, "-m", "before strata"], cwd=repo.root
    ).stdout.strip()
    run = _Runner(tmp_path, repo, bare_base)
    done = run.run(COMPARE)
    assert done.returncode == 0, done.stderr
    assert "no strata repository" in run.summary.read_text(encoding="utf-8")


def test_comment_and_label_steps_are_skipped_for_pull_requests_from_forks() -> None:
    for name in (POST, LABEL):
        assert _step(name)["if"] == "env.CAN_WRITE == 'true'"
    reusable = load_yaml_str((ROOT / workflows.REUSABLE_WORKFLOW).read_text(encoding="utf-8"))
    env = reusable["jobs"]["pool-impact"]["env"]
    assert (
        env["CAN_WRITE"]
        == "${{ github.event.pull_request.head.repo.full_name == github.repository }}"
    )
    assert reusable["jobs"]["verify"].get("if") is None  # verify runs for forks too
