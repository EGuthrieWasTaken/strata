"""The container image's files (openspec:container-image): the entrypoint's behaviour, run for real
with a stand-in `strata`, and structural checks on the Dockerfile, compose file and CI jobs. The image
itself is not built here (that needs a container runtime; CI's `container` job does it)."""

# ruff: noqa: E501
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from strata import __version__
from strata.cli.main import app
from strata.core.canon import load_yaml_str

ROOT = Path(__file__).resolve().parents[2]
posix_shell = pytest.mark.skipif(sys.platform == "win32", reason="runs POSIX shell scripts")
ENTRYPOINT = ROOT / "docker" / "entrypoint.sh"
runner = CliRunner()

FAKE_STRATA = """#!/bin/sh
{
  for arg in "$@"; do printf 'ARG %s\\n' "$arg"; done
  printf 'TOKEN %s\\n' "${STRATA_TOKEN:-}"
  printf 'PUBLIC %s\\n' "${STRATA_PUBLIC_URL:-}"
} > "$OUT"
"""


def _entrypoint(tmp_path: Path, *args: str, **env: str) -> tuple[list[str], str, str]:
    """Run the entrypoint with a stand-in strata; returns (strata's arguments, token, public url)."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    fake = bin_dir / "strata"
    fake.write_text(FAKE_STRATA, encoding="utf-8")
    fake.chmod(0o755)
    python = bin_dir / "python"
    if not python.exists():
        python.symlink_to(sys.executable)
    out = tmp_path / "out.txt"
    base = {k: v for k, v in os.environ.items() if not k.startswith("STRATA_")}
    done = subprocess.run(
        ["sh", str(ENTRYPOINT), *args],
        env={**base, "PATH": f"{bin_dir}:{os.environ['PATH']}", "OUT": str(out), **env},
        capture_output=True, text=True, check=False,
    )  # fmt: skip
    assert done.returncode == 0, done.stderr
    lines = out.read_text(encoding="utf-8").splitlines()
    given = [line[4:] for line in lines if line.startswith("ARG ")]
    token = next(line[6:] for line in lines if line.startswith("TOKEN "))
    public = next(line[7:] for line in lines if line.startswith("PUBLIC "))
    return given, token, public


@posix_shell
def test_other_commands_go_straight_to_strata(tmp_path: Path) -> None:
    given, token, public = _entrypoint(tmp_path, "status", "--json")
    assert given == ["status", "--json"] and token == "" and public == ""


@posix_shell
def test_serve_listens_on_every_interface_with_a_new_token_and_the_localhost_url(
    tmp_path: Path,
) -> None:
    given, token, public = _entrypoint(tmp_path, "serve", "--actor", "ethan")
    assert given[:2] == ["serve", "--no-browser"]
    assert given[given.index("--host") + 1] == "0.0.0.0"
    assert given[given.index("--port") + 1] == "8765"
    assert given[given.index("--actor") + 1] == "ethan"
    assert len(token) >= 32 and re.fullmatch(r"[\w-]+", token)
    assert public == "http://localhost:8765"
    assert "--token" not in given  # it reaches strata in the environment, not on a command line


@posix_shell
def test_every_start_generates_a_different_token(tmp_path: Path) -> None:
    first = _entrypoint(tmp_path, "serve")[1]
    second = _entrypoint(tmp_path, "serve")[1]
    assert first and second and first != second


@pytest.mark.parametrize("flags", [["--port", "9000"], ["--port=9000"]])
@posix_shell
def test_the_public_url_follows_the_port_asked_for(tmp_path: Path, flags: list[str]) -> None:
    given, _token, public = _entrypoint(tmp_path, "serve", *flags)
    assert public == "http://localhost:9000"
    assert sum(1 for a in given if a.startswith("--port")) == 1  # not added a second time


@posix_shell
def test_the_port_can_come_from_the_environment(tmp_path: Path) -> None:
    given, _token, public = _entrypoint(tmp_path, "serve", STRATA_PORT="9100")
    assert given[given.index("--port") + 1] == "9100" and public == "http://localhost:9100"


@posix_shell
def test_a_token_that_was_supplied_is_kept(tmp_path: Path) -> None:
    _given, token, _public = _entrypoint(tmp_path, "serve", STRATA_TOKEN="from-the-environment")
    assert token == "from-the-environment"
    given, token, _public = _entrypoint(tmp_path, "serve", "--token", "on-the-command-line")
    assert token == "" and given[given.index("--token") + 1] == "on-the-command-line"


@posix_shell
def test_a_public_url_that_was_supplied_is_kept(tmp_path: Path) -> None:
    _given, _token, public = _entrypoint(
        tmp_path, "serve", STRATA_PUBLIC_URL="https://strata.example.edu"
    )
    assert public == "https://strata.example.edu"
    given, _token, public = _entrypoint(tmp_path, "serve", "--public-url", "https://x.example")
    assert public == "" and given[given.index("--public-url") + 1] == "https://x.example"


@posix_shell
def test_a_host_that_was_asked_for_is_respected(tmp_path: Path) -> None:
    given, *_ = _entrypoint(tmp_path, "serve", "--host", "127.0.0.1")
    assert given.count("--host") == 1 and given[given.index("--host") + 1] == "127.0.0.1"


# --- the files ------------------------------------------------------------------------------------


def _dockerfile() -> str:
    return (ROOT / "Dockerfile").read_text(encoding="utf-8")


def test_the_dockerfile_builds_a_small_non_root_image_around_the_lock_file() -> None:
    text = _dockerfile()
    stages = re.findall(
        r"^FROM\s+(\S+)(?:\s+AS\s+(\w+))?", text, flags=re.MULTILINE | re.IGNORECASE
    )
    assert len(stages) == 2 and stages[0][1] == "build"  # build tools never reach the runtime image
    assert "uv sync --frozen --no-dev" in text  # exactly the locked set, no dev dependencies
    assert re.search(r"^USER 10001:10001$", text, flags=re.MULTILINE)
    assert re.search(r"^WORKDIR /review$", text, flags=re.MULTILINE)
    assert re.search(r"^ENTRYPOINT \[\"strata-entrypoint\"\]$", text, flags=re.MULTILINE)
    assert "git config --system --add safe.directory '*'" in text
    assert "install -y --no-install-recommends git" in text
    assert "mkdir -m 1777 /home-strata" in text and "HOME=/home-strata" in text


def test_the_image_declares_a_health_check_on_healthz() -> None:
    health = re.search(
        r"^HEALTHCHECK .*?(?=^\S)", _dockerfile() + "\nEND", flags=re.MULTILINE | re.DOTALL
    )
    assert health and "/healthz" in health.group(0)


def test_no_credentials_are_asked_for_at_build_time() -> None:
    text = _dockerfile()
    assert not re.search(
        r"^(ARG|ENV)\s+\w*(TOKEN|PASSWORD|SECRET|KEY)\w*", text, flags=re.MULTILINE | re.IGNORECASE
    )
    assert "--mount=type=secret" not in text and "ssh-add" not in text


def test_the_build_context_is_only_what_the_image_needs() -> None:
    lines = [
        line.strip() for line in (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    ]
    assert lines[lines.index("*") + 1 :][:5] == [
        "!pyproject.toml", "!uv.lock", "!README.md", "!src/", "!docker/entrypoint.sh",
    ]  # fmt: skip
    assert all((ROOT / p.lstrip("!").rstrip("/")).exists() for p in lines if p.startswith("!"))


def test_compose_publishes_only_on_loopback_and_runs_as_the_host_user() -> None:
    compose = load_yaml_str((ROOT / "compose.yaml").read_text(encoding="utf-8"))
    service = compose["services"]["strata"]
    assert service["ports"] == ["127.0.0.1:8765:8765"]
    assert "UID" in service["user"] and service["command"][0] == "serve"
    assert any(v.endswith(":/review") for v in service["volumes"])


@posix_shell
def test_the_entrypoint_is_executable_and_the_smoke_script_parses() -> None:
    assert os.access(ENTRYPOINT, os.X_OK) and os.access(
        ROOT / "scripts" / "container_smoke.sh", os.X_OK
    )
    for script in (ENTRYPOINT, ROOT / "scripts" / "container_smoke.sh"):
        shell = "sh" if script == ENTRYPOINT else "bash"
        assert subprocess.run([shell, "-n", str(script)], check=False).returncode == 0


def test_ci_builds_both_architectures_and_the_gate_waits_for_it() -> None:
    ci = load_yaml_str((ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
    container = ci["jobs"]["container"]
    assert {m["arch"] for m in container["strategy"]["matrix"]["include"]} == {"amd64", "arm64"}
    assert container["if"] == "needs.container-changes.outputs.run == 'true'"
    assert "container" in ci["jobs"]["gate"]["needs"]  # a skipped job satisfies the gate
    steps = " ".join(step.get("run", "") for step in container["steps"])
    assert (
        "hadolint" in steps
        and "scripts/container_smoke.sh" in steps
        and "determinism_check.py" in steps
    )


def test_every_workflow_pins_third_party_actions_to_commits() -> None:
    for path in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        for ref in re.findall(
            r"^\s*(?:- )?uses:\s*(\S+)", path.read_text(encoding="utf-8"), re.MULTILINE
        ):
            if ref.startswith("./") or ".github/workflows/" in ref:
                continue
            assert re.fullmatch(r"[\w.-]+/[\w./-]+@[0-9a-f]{40}", ref), (path.name, ref)


def test_the_release_publishes_a_multi_architecture_image_with_an_sbom() -> None:
    release = load_yaml_str(
        (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    )
    container = release["jobs"]["container"]
    assert container["permissions"]["packages"] == "write"
    build = " ".join(step.get("run", "") for step in container["steps"])
    assert "--sbom=true" in build and "--provenance=mode=max" in build and "--push" in build
    manifest = " ".join(
        step.get("run", "") for step in release["jobs"]["container-manifest"]["steps"]
    )
    assert "imagetools create" in manifest and ":latest" in manifest


def test_the_nightly_builds_the_image_from_scratch() -> None:
    nightly = load_yaml_str(
        (ROOT / ".github" / "workflows" / "nightly.yml").read_text(encoding="utf-8")
    )
    steps = " ".join(
        step.get("run", "") for step in nightly["jobs"]["cold-install-container"]["steps"]
    )
    assert "--no-cache" in steps and "container_smoke.sh" in steps
    assert "cold-install-container" in nightly["jobs"]["open-issue-on-failure"]["needs"]


# --- strata --version -----------------------------------------------------------------------------


def test_the_standard_version_flag_reports_the_installed_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0 and result.output.strip() == f"strata {__version__}"


def test_the_ghcr_workflow_publishes_both_architectures_and_verifies_what_it_published() -> None:
    wf = load_yaml_str(
        (ROOT / ".github" / "workflows" / "container.yml").read_text(encoding="utf-8")
    )
    jobs = wf["jobs"]
    assert {"tag", "publish", "manifest", "verify"} <= set(jobs)
    for name in ("publish", "verify"):
        assert {m["arch"] for m in jobs[name]["strategy"]["matrix"]["include"]} == {
            "amd64",
            "arm64",
        }
    assert jobs["publish"]["permissions"]["packages"] == "write"
    assert jobs["verify"]["permissions"]["packages"] == "read"  # it only reads what was published
    publish = " ".join(step.get("run", "") for step in jobs["publish"]["steps"])
    assert "--sbom=true" in publish and "--provenance=mode=max" in publish and "--push" in publish
    verify = " ".join(step.get("run", "") for step in jobs["verify"]["steps"])
    assert "docker pull" in verify and "scripts/container_smoke.sh" in verify
    assert jobs["verify"]["needs"] == ["tag", "manifest"] and jobs["manifest"]["needs"] == [
        "tag",
        "publish",
    ]
    # a fork's pull request has no token that can write packages, so it is skipped, not failed
    assert "head.repo.full_name == github.repository" in jobs["tag"]["if"]
    trigger = _on_trigger(wf)
    assert "pull_request" in trigger and "pull_request_target" not in trigger
    assert trigger["push"]["branches"] == ["main"] and "workflow_dispatch" in trigger


def _on_trigger(workflow: dict) -> dict:  # type: ignore[type-arg]
    return workflow.get("on", workflow.get(True))  # YAML 1.1 reads a bare `on` as true


def test_the_base_image_is_pinned_by_digest_in_both_stages() -> None:
    from_lines = re.findall(r"^FROM\s+(\S+)", _dockerfile(), flags=re.MULTILINE)
    assert len(from_lines) == 2 and from_lines[0] == from_lines[1]
    assert re.fullmatch(r"python:3\.12-slim@sha256:[0-9a-f]{64}", from_lines[0])
